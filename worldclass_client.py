"""
Worldclass Romania booking automation using Playwright.

Flow per GitHub Actions run (every 5 min):
  1. Login to worldclass.ro
  2. Fetch the LIVE schedule for Lujerului (always fresh — handles trainer/holiday changes)
  3. For each pilates/stretching class in the next ~32 hours:
       - Calculate  booking_opens_at = class_datetime - 26h
       - If window opens in the next LOOKAHEAD seconds: sleep until exact moment, then book
       - If window just opened (within GRACE seconds): book immediately
  4. Worldclass sends confirmation email natively after each booking
"""

import asyncio
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from loguru import logger
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PWTimeout,
    async_playwright,
)

from config import Config

BUCHAREST_TZ = ZoneInfo("Europe/Bucharest")

# ---------------------------------------------------------------------------
# Romanian locale helpers
# ---------------------------------------------------------------------------

_RO_DAYS: dict[str, int] = {
    "luni": 0, "marti": 1, "marți": 1,
    "miercuri": 2, "joi": 3, "vineri": 4,
    "sambata": 5, "sâmbătă": 5, "duminica": 6, "duminică": 6,
}
_RO_MONTHS: dict[str, int] = {
    "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4,
    "mai": 5, "iunie": 6, "iulie": 7, "august": 8,
    "septembrie": 9, "octombrie": 10, "noiembrie": 11, "decembrie": 12,
}


def parse_ro_date(text: str, today: date) -> Optional[date]:
    """
    Parse a Romanian date string into a date object.
    Handles: 'DD.MM', 'DD.MM.YYYY', 'DD Aprilie', 'Luni', 'Marți 21 Aprilie', etc.
    Falls back to next occurrence of the named weekday relative to today.
    """
    t = text.lower().strip()

    # 1. Numeric: DD.MM[.YYYY] or DD/MM[/YYYY]
    m = re.search(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b", t)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        yr = int(m.group(3)) if m.group(3) else today.year
        if yr < 100:
            yr += 2000
        try:
            return date(yr, mo, d)
        except ValueError:
            pass

    # 2. Month name present: "21 Aprilie 2026" / "Aprilie 21"
    for name, num in _RO_MONTHS.items():
        if name in t:
            dm = re.search(r"\b(\d{1,2})\b", t)
            ym = re.search(r"\b(20\d{2})\b", t)
            if dm:
                yr = int(ym.group(1)) if ym else today.year
                try:
                    return date(yr, num, int(dm.group(1)))
                except ValueError:
                    pass

    # 3. Weekday name only → next occurrence (including today)
    for name, wd in _RO_DAYS.items():
        if name in t:
            days_ahead = (wd - today.weekday()) % 7
            return today + timedelta(days=days_ahead)

    return None


def build_class_datetime(date_str: str, time_str: str, today: date) -> Optional[datetime]:
    """Combine a parsed date string and HH:MM time string into an aware datetime."""
    if not time_str:
        return None
    d = parse_ro_date(date_str, today) if date_str else None
    if d is None:
        return None
    try:
        h, mi = map(int, time_str.split(":"))
        return datetime(d.year, d.month, d.day, h, mi, tzinfo=BUCHAREST_TZ)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ClassInfo:
    name: str
    date: str = ""
    time: str = ""
    duration: str = ""
    instructor: str = ""
    club: str = "World Class Lujerului"
    can_book: bool = False
    already_booked: bool = False
    class_datetime: Optional[datetime] = None
    raw_text: str = ""
    booked_at: str = ""
    confirmation: str = ""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class WorldclassClient:
    BASE_URL    = "https://www.worldclass.ro"
    LOGIN_URL   = "https://www.worldclass.ro/my-account/"
    SCHEDULE_URL = "https://www.worldclass.ro/rezervari/"

    _EMAIL_SELECTORS = [
        'input[name="username"]', 'input[name="email"]', 'input[type="email"]',
        "#username", "#email", ".woocommerce-Input--username",
    ]
    _PASSWORD_SELECTORS = [
        'input[name="password"]', 'input[type="password"]',
        "#password", ".woocommerce-Input--password",
    ]
    _SUBMIT_SELECTORS = [
        'button[name="login"]', 'button[type="submit"]',
        ".woocommerce-form-login__submit", 'input[type="submit"]',
    ]
    _SCHEDULE_ITEM_SELECTORS = [
        ".schedule-item", ".class-item", ".rezervare-item",
        ".group-fitness-class", '[class*="class-row"]', '[class*="schedule-row"]',
        ".wc-class", ".fitness-class", "[data-class]",
    ]
    _DATE_HEADER_SELECTORS = [
        ".schedule-day", ".day-header", ".calendar-day-header",
        '[class*="day-title"]', '[class*="date-header"]', "th.day",
    ]
    _BOOK_BTN_SELECTORS = [
        'button:has-text("Rezervă")', 'button:has-text("Rezerva")',
        'a:has-text("Rezervă")', 'a:has-text("Rezerva")',
        ".book-button", ".rezerva-btn", '[class*="book-btn"]', '[class*="rezerva"]',
    ]

    def __init__(self):
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._ctx: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def __aenter__(self):
        await self._start()
        return self

    async def __aexit__(self, *_):
        await self._stop()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _start(self):
        import pathlib
        _shell = pathlib.Path(
            "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell"
        )
        launch_kw: dict = dict(
            headless=Config.HEADLESS,
            args=["--no-sandbox", "--disable-setuid-sandbox",
                  "--disable-blink-features=AutomationControlled"],
        )
        if _shell.exists():
            launch_kw["executable_path"] = str(_shell)

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(**launch_kw)
        self._ctx = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="ro-RO",
            ignore_https_errors=True,
        )
        await self._ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        self.page = await self._ctx.new_page()

    async def _stop(self):
        if self._ctx:   await self._ctx.close()
        if self._browser: await self._browser.close()
        if self._pw:    await self._pw.stop()

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    async def login(self) -> bool:
        logger.info("Autentificare...")
        try:
            await self.page.goto(self.LOGIN_URL, wait_until="networkidle", timeout=40_000)
        except PWTimeout:
            pass

        if await self._is_logged_in():
            logger.info("Sesiune activa.")
            return True

        if not await self._try_fill(self._EMAIL_SELECTORS, Config.WC_EMAIL, "email"):
            return False
        if not await self._try_fill(self._PASSWORD_SELECTORS, Config.WC_PASSWORD, "parola"):
            return False

        submitted = False
        for sel in self._SUBMIT_SELECTORS:
            try:
                await self.page.click(sel, timeout=5_000)
                submitted = True
                break
            except Exception:
                continue

        if not submitted:
            logger.error("Butonul Login nu a fost gasit.")
            await self._screenshot("login_no_submit.png")
            return False

        try:
            await self.page.wait_for_load_state("networkidle", timeout=20_000)
        except PWTimeout:
            pass

        if await self._is_logged_in():
            logger.success("Autentificare reusita.")
            return True

        logger.error("Autentificare esuata — verifica email/parola.")
        await self._screenshot("login_failed.png")
        return False

    async def _try_fill(self, selectors: list, value: str, label: str) -> bool:
        for sel in selectors:
            try:
                el = self.page.locator(sel)
                if await el.count() > 0:
                    await el.first.fill(value, timeout=5_000)
                    return True
            except Exception:
                continue
        logger.error(f"Campul '{label}' nu a fost gasit.")
        await self._screenshot(f"missing_{label}.png")
        return False

    async def _is_logged_in(self) -> bool:
        try:
            for sel in ['a[href*="logout"]', 'a:has-text("Deconectare")',
                        ".logout", 'a[href*="customer-logout"]']:
                if await self.page.locator(sel).count() > 0:
                    return True
            url = self.page.url
            if "my-account" in url:
                if await self.page.locator('input[name="username"],input[name="password"]').count() == 0:
                    return True
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------
    # Schedule scraping — always fetches LIVE data
    # ------------------------------------------------------------------

    async def get_all_upcoming_classes(self) -> list[ClassInfo]:
        """
        Fetch the LIVE schedule from worldclass.ro and return all pilates/stretching
        classes at Lujerului for the next ~48 hours, with class_datetime populated.
        This is called on every GitHub Actions run so schedule changes are always reflected.
        """
        logger.info("Fetch program live de pe worldclass.ro...")
        try:
            await self.page.goto(self.SCHEDULE_URL, wait_until="networkidle", timeout=40_000)
        except PWTimeout:
            logger.warning("Timeout la incarcare program, continuam...")

        await self._select_lujerului()

        today = datetime.now(tz=BUCHAREST_TZ).date()
        classes = await self._scrape_schedule_with_dates(today)

        target = [kw.lower() for kw in Config.TARGET_CLASSES]
        result = [c for c in classes if any(kw in c.name.lower() for kw in target)]

        bookable  = sum(1 for c in result if c.can_book)
        with_dt   = sum(1 for c in result if c.class_datetime)
        logger.info(
            f"Program live: {len(result)} clase pilates/stretching la Lujerului "
            f"| {bookable} rezervabile acum | {with_dt} cu datetime determinat"
        )
        return result

    async def _select_lujerului(self):
        """Filter schedule to Lujerului club using every available mechanism."""
        # Dropdown
        for sel in ['select[name="club"]', "#club-filter", ".club-selector select"]:
            try:
                el = self.page.locator(sel)
                if await el.count() > 0:
                    await el.select_option(label=re.compile("Lujerului", re.I), timeout=5_000)
                    await self.page.wait_for_load_state("networkidle", timeout=10_000)
                    logger.info("Club Lujerului selectat (dropdown).")
                    return
            except Exception:
                continue
        # Clickable element
        for loc in [self.page.get_by_text("Lujerului", exact=False),
                    self.page.locator('a[href*="lujerului"]'),
                    self.page.locator('[data-club*="Lujerului"]')]:
            try:
                if await loc.count() > 0:
                    await loc.first.click(timeout=5_000)
                    await self.page.wait_for_load_state("networkidle", timeout=10_000)
                    logger.info("Club Lujerului selectat (click).")
                    return
            except Exception:
                continue
        # URL parameter fallback
        if "lujerului" not in self.page.url.lower():
            try:
                await self.page.goto(
                    f"{self.SCHEDULE_URL}?club=lujerului",
                    wait_until="networkidle", timeout=20_000,
                )
                return
            except Exception:
                pass
        logger.warning("Nu s-a putut selecta clubul Lujerului explicit.")

    async def _scrape_schedule_with_dates(self, today: date) -> list[ClassInfo]:
        """
        Scrape the schedule page and associate each class with its correct date.

        Strategy A — sectioned layout: the page is divided into sections, each
          starting with a date/day header, followed by class rows.
        Strategy B — table/grid layout: columns = days, rows = time slots.
        Strategy C — flat list: each class row contains its own date text.
        Strategy D — fallback: items found by booking keyword; date inferred
          from weekday name in the item text.
        """
        classes: list[ClassInfo] = []

        # ---- Strategy A: sectioned (div per day) ----
        classes = await self._scrape_sectioned(today)
        if classes:
            return classes

        # ---- Strategy B: table columns ----
        classes = await self._scrape_table(today)
        if classes:
            return classes

        # ---- Strategy C / D: flat list ----
        classes = await self._scrape_flat(today)
        return classes

    async def _scrape_sectioned(self, today: date) -> list[ClassInfo]:
        """Handle layouts where each day has its own container/section."""
        classes: list[ClassInfo] = []

        # Find all date header elements
        header_locs = []
        for sel in self._DATE_HEADER_SELECTORS:
            locs = self.page.locator(sel)
            count = await locs.count()
            if count > 0:
                header_locs = [locs.nth(i) for i in range(count)]
                logger.debug(f"Date headers found with '{sel}': {count}")
                break

        if not header_locs:
            return []

        for hdr in header_locs:
            hdr_text = (await hdr.inner_text()).strip()
            parsed_date = parse_ro_date(hdr_text, today)
            if parsed_date is None:
                continue

            # Items that follow this header (siblings or children of parent)
            # Try: next siblings until next header; or children of parent section
            section = hdr.locator("xpath=..")  # parent element
            items_in_section = []
            for sel in self._SCHEDULE_ITEM_SELECTORS:
                loc = section.locator(sel)
                n = await loc.count()
                if n > 0:
                    items_in_section = [loc.nth(i) for i in range(n)]
                    break

            for item in items_in_section:
                info = await self._parse_item(item, str(parsed_date), today)
                if info:
                    classes.append(info)

        return classes

    async def _scrape_table(self, today: date) -> list[ClassInfo]:
        """Handle calendar table layouts where columns represent days."""
        classes: list[ClassInfo] = []

        # Find column headers (th cells with date/day info)
        th_locs = self.page.locator("table th")
        n_th = await th_locs.count()
        if n_th == 0:
            return []

        # Build column_index → date mapping
        col_dates: dict[int, date] = {}
        for i in range(n_th):
            th_text = (await th_locs.nth(i).inner_text()).strip()
            d = parse_ro_date(th_text, today)
            if d:
                col_dates[i] = d

        if not col_dates:
            return []

        # For each row, each cell belongs to its column's date
        rows = self.page.locator("table tr")
        n_rows = await rows.count()
        for r in range(n_rows):
            cells = rows.nth(r).locator("td")
            n_cells = await cells.count()
            for c in range(n_cells):
                if c not in col_dates:
                    continue
                cell = cells.nth(c)
                # Each cell may contain one or more class items
                for sel in self._SCHEDULE_ITEM_SELECTORS:
                    items = cell.locator(sel)
                    n = await items.count()
                    if n > 0:
                        for i in range(n):
                            info = await self._parse_item(
                                items.nth(i), str(col_dates[c]), today
                            )
                            if info:
                                classes.append(info)
                        break
                else:
                    # Cell itself might be the class item
                    info = await self._parse_item(cell, str(col_dates[c]), today)
                    if info:
                        classes.append(info)

        return classes

    async def _scrape_flat(self, today: date) -> list[ClassInfo]:
        """
        Flat list fallback: find all class items (or elements with booking button)
        and extract date from within the item itself or nearby text.
        """
        classes: list[ClassInfo] = []

        items = []
        for sel in self._SCHEDULE_ITEM_SELECTORS:
            loc = self.page.locator(sel)
            n = await loc.count()
            if n > 0:
                items = [loc.nth(i) for i in range(n)]
                logger.debug(f"Flat scrape: {n} items with selector '{sel}'")
                break

        if not items:
            # Last resort: any element containing "Rezerva"
            loc = self.page.locator("*").filter(
                has_text=re.compile(r"Rezerv[aă]", re.I)
            )
            n = await loc.count()
            if n == 0:
                await self._screenshot("schedule_not_found.png")
                logger.error("Nu s-au gasit clase in program. Screenshot salvat.")
                return []
            items = [loc.nth(i) for i in range(min(n, 60))]
            logger.debug(f"Flat fallback via 'Rezerva' text: {n} elements")

        for item in items:
            info = await self._parse_item(item, "", today)
            if info:
                classes.append(info)

        return classes

    # ------------------------------------------------------------------
    # Item parser
    # ------------------------------------------------------------------

    async def _parse_item(self, locator, date_hint: str, today: date) -> Optional[ClassInfo]:
        try:
            text = await locator.inner_text()
            if not text.strip():
                return None

            # Name
            name = await self._extract_field(
                locator, [".class-name", ".name", "h3", "h4", ".title", ".class-title"]
            )
            if not name:
                lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
                name = lines[0] if lines else ""
            if not name:
                return None

            # Time
            tm = re.search(r"\b(\d{1,2}:\d{2})\b", text)
            time_str = tm.group(1) if tm else ""

            # Date: prefer explicit date_hint from outer context (section header / table column)
            # else try to parse from the item's own text
            date_str = date_hint
            if not date_str:
                dm = re.search(
                    r"\b(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?)\b"
                    r"|\b(luni|marti|marți|miercuri|joi|vineri|sambata|sâmbătă|duminica|duminică)\b",
                    text, re.I
                )
                date_str = dm.group(0) if dm else ""

            # Duration, instructor
            dur_m = re.search(r"(\d{2,3})\s*min", text, re.I)
            duration = f"{dur_m.group(1)} min" if dur_m else ""
            instructor = await self._extract_field(
                locator, [".instructor", ".trainer", ".profesor", '[class*="instructor"]']
            )

            # Booking state
            already_booked = bool(re.search(r"Anule[az][aă]|Rezervat|Booked", text, re.I))
            can_book = False
            if not already_booked:
                for sel in self._BOOK_BTN_SELECTORS:
                    try:
                        btn = locator.locator(sel)
                        if await btn.count() > 0:
                            disabled = await btn.first.get_attribute("disabled")
                            aria    = await btn.first.get_attribute("aria-disabled")
                            if disabled is None and aria != "true":
                                can_book = True
                            break
                    except Exception:
                        continue

            # Build aware datetime
            class_dt = build_class_datetime(date_str, time_str, today)

            return ClassInfo(
                name=name.strip(),
                date=date_str,
                time=time_str,
                duration=duration,
                instructor=instructor,
                can_book=can_book,
                already_booked=already_booked,
                class_datetime=class_dt,
                raw_text=text[:300],
            )
        except Exception as e:
            logger.debug(f"Eroare parsare item: {e}")
            return None

    async def _extract_field(self, parent, selectors: list) -> str:
        for sel in selectors:
            try:
                el = parent.locator(sel)
                if await el.count() > 0:
                    return (await el.first.inner_text()).strip()
            except Exception:
                continue
        return ""

    # ------------------------------------------------------------------
    # Booking — reload live page before clicking to avoid stale state
    # ------------------------------------------------------------------

    async def book_class(self, info: ClassInfo) -> Optional[ClassInfo]:
        """
        Reload the live schedule, find the class by name+time, click Rezerva.
        Called right after sleeping to the exact booking-window-open moment.
        """
        logger.info(f"Rezervare: {info.name} | {info.date} {info.time}")

        # Refresh page to get the live booking button state
        try:
            await self.page.goto(self.SCHEDULE_URL, wait_until="networkidle", timeout=30_000)
        except PWTimeout:
            pass
        await self._select_lujerului()

        confirmation = await self._click_book(info)

        if confirmation:
            info.booked_at     = datetime.now(tz=BUCHAREST_TZ).strftime("%Y-%m-%d %H:%M:%S")
            info.confirmation  = confirmation
            logger.success(f"Rezervare reusita: {info.name} ({info.date} {info.time})")
            return info

        logger.warning(f"Rezervare esuata pentru '{info.name}'.")
        await self._screenshot(f"booking_failed_{re.sub(r'\\W','_',info.name)}.png")
        return None

    async def _click_book(self, info: ClassInfo) -> Optional[str]:
        """Locate the class row on the current page and click its booking button."""
        anchors = [info.name.strip()]
        if info.time:
            anchors.append(info.time)

        for anchor in anchors:
            containers = self.page.locator("*").filter(has_text=anchor)
            count = await containers.count()
            for i in range(min(count, 10)):
                container = containers.nth(i)
                for sel in self._BOOK_BTN_SELECTORS:
                    try:
                        btn = container.locator(sel)
                        if await btn.count() > 0:
                            disabled = await btn.first.get_attribute("disabled")
                            if disabled is not None:
                                continue
                            await btn.first.click(timeout=8_000)
                            await asyncio.sleep(2)
                            return await self._detect_confirmation()
                    except Exception:
                        continue

        return None

    async def _detect_confirmation(self) -> Optional[str]:
        await asyncio.sleep(1)
        for phrase in ["Rezervare confirmata", "Rezervare efectuata",
                       "rezervat cu succes", "Confirmare"]:
            if await self.page.get_by_text(phrase, exact=False).count() > 0:
                return phrase
        if await self.page.get_by_text(re.compile(r"Anule[az][aă]", re.I)).count() > 0:
            return "Confirmat (buton Anuleaza vizibil)"
        content = await self.page.content()
        if re.search(r"rezervat|confirmat", content, re.I):
            return "Posibil confirmat"
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _screenshot(self, filename: str):
        try:
            await self.page.screenshot(path=filename, full_page=True)
            logger.debug(f"Screenshot: {filename}")
        except Exception:
            pass
