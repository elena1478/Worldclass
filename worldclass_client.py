"""
Worldclass Romania booking automation using Playwright.

Flow:
  1. Login to worldclass.ro member account
  2. Navigate to the Group Fitness schedule
  3. Select club "Lujerului" and filter for pilates / stretching
  4. For every bookable slot (booking window already open), click "Rezerva"
  5. Return a dict with booking details for the email notifier
"""

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

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
    raw_text: str = ""
    booked_at: str = ""
    confirmation: str = ""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class WorldclassClient:
    BASE_URL = "https://www.worldclass.ro"
    LOGIN_URL = "https://www.worldclass.ro/my-account/"
    SCHEDULE_URL = "https://www.worldclass.ro/rezervari/"

    # Candidate selectors tried in order; first match wins
    _EMAIL_SELECTORS = [
        'input[name="username"]',
        'input[name="email"]',
        'input[type="email"]',
        "#username",
        "#email",
        ".woocommerce-Input--username",
    ]
    _PASSWORD_SELECTORS = [
        'input[name="password"]',
        'input[type="password"]',
        "#password",
        ".woocommerce-Input--password",
    ]
    _SUBMIT_SELECTORS = [
        'button[name="login"]',
        'button[type="submit"]',
        '.woocommerce-form-login__submit',
        'input[type="submit"]',
    ]
    _SCHEDULE_ITEM_SELECTORS = [
        ".schedule-item",
        ".class-item",
        ".rezervare-item",
        ".group-fitness-class",
        '[class*="class-row"]',
        '[class*="schedule-row"]',
        ".wc-class",
        ".fitness-class",
        "[data-class]",
    ]
    _BOOK_BTN_SELECTORS = [
        'button:has-text("Rezervă")',
        'button:has-text("Rezerva")',
        'a:has-text("Rezervă")',
        'a:has-text("Rezerva")',
        ".book-button",
        ".rezerva-btn",
        '[class*="book-btn"]',
        '[class*="rezerva"]',
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
        # Use pre-installed headless shell if the default playwright browser isn't downloadable
        _headless_shell = pathlib.Path(
            "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell"
        )
        launch_kwargs = dict(
            headless=Config.HEADLESS,
            args=["--no-sandbox", "--disable-setuid-sandbox",
                  "--disable-blink-features=AutomationControlled"],
        )
        if _headless_shell.exists():
            launch_kwargs["executable_path"] = str(_headless_shell)

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(**launch_kwargs)
        self._ctx = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="ro-RO",
            ignore_https_errors=True,
        )
        # Hide webdriver flag
        await self._ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        self.page = await self._ctx.new_page()

    async def _stop(self):
        if self._ctx:
            await self._ctx.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    async def login(self) -> bool:
        logger.info("Navigare catre pagina de autentificare...")
        try:
            await self.page.goto(self.LOGIN_URL, wait_until="networkidle", timeout=40_000)
        except PWTimeout:
            logger.warning("Timeout la incarcare pagina login, continuam...")

        if await self._is_logged_in():
            logger.info("Sesiune activa detectata — nu este necesara autentificarea.")
            return True

        # Fill email
        if not await self._try_fill(self._EMAIL_SELECTORS, Config.WC_EMAIL, "email"):
            return False

        # Fill password
        if not await self._try_fill(self._PASSWORD_SELECTORS, Config.WC_PASSWORD, "parola"):
            return False

        # Submit
        submitted = False
        for sel in self._SUBMIT_SELECTORS:
            try:
                await self.page.click(sel, timeout=5_000)
                submitted = True
                break
            except Exception:
                continue

        if not submitted:
            logger.error("Butonul de login nu a fost gasit.")
            await self._screenshot("login_no_submit.png")
            return False

        try:
            await self.page.wait_for_load_state("networkidle", timeout=20_000)
        except PWTimeout:
            pass

        if await self._is_logged_in():
            logger.success("Autentificare reusita!")
            return True

        logger.error("Autentificare esuata — verifica email/parola.")
        await self._screenshot("login_failed.png")
        return False

    async def _try_fill(self, selectors: list, value: str, field_name: str) -> bool:
        for sel in selectors:
            try:
                el = self.page.locator(sel)
                if await el.count() > 0:
                    await el.first.fill(value, timeout=5_000)
                    logger.debug(f"Campul '{field_name}' completat cu selectorul: {sel}")
                    return True
            except Exception:
                continue
        logger.error(f"Campul '{field_name}' nu a fost gasit in pagina.")
        await self._screenshot(f"missing_{field_name}.png")
        return False

    async def _is_logged_in(self) -> bool:
        try:
            indicators = [
                'a[href*="logout"]',
                'a:has-text("Deconectare")',
                'a:has-text("Iesire")',
                ".logout",
                ".user-account",
                ".my-account-nav a",
                'a[href*="customer-logout"]',
            ]
            for sel in indicators:
                if await self.page.locator(sel).count() > 0:
                    return True

            # If login form is absent and we're past /my-account/, assume logged in
            url = self.page.url
            if "my-account" in url:
                form_present = await self.page.locator('input[name="username"], input[name="password"]').count()
                if form_present == 0:
                    return True
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------
    # Schedule scraping
    # ------------------------------------------------------------------

    async def get_bookable_classes(self) -> list[ClassInfo]:
        """Return pilates/stretching classes at Lujerului that can be booked now."""
        logger.info("Incarcare program clase...")
        try:
            await self.page.goto(self.SCHEDULE_URL, wait_until="networkidle", timeout=40_000)
        except PWTimeout:
            logger.warning("Timeout la incarcare pagina rezervari, continuam...")

        await self._select_lujerului()

        items = await self._find_schedule_items()
        classes: list[ClassInfo] = []

        for item in items:
            info = await self._parse_class_item(item)
            if info is None:
                continue
            name_lower = info.name.lower()
            if any(kw in name_lower for kw in Config.TARGET_CLASSES):
                classes.append(info)

        logger.info(
            f"Gasite {len(classes)} clase pilates/stretching la Lujerului "
            f"({sum(1 for c in classes if c.can_book)} disponibile pentru rezervare)"
        )
        return classes

    async def _select_lujerului(self):
        """Try every reasonable way to filter by Lujerului club."""
        # 1. Dropdown / select element
        for sel in ['select[name="club"]', "#club-filter", ".club-selector select", "select.location"]:
            try:
                el = self.page.locator(sel)
                if await el.count() > 0:
                    # Try by label containing "Lujerului"
                    await el.select_option(label=re.compile("Lujerului", re.IGNORECASE), timeout=5_000)
                    await self.page.wait_for_load_state("networkidle", timeout=10_000)
                    logger.info("Club Lujerului selectat (dropdown).")
                    return
            except Exception:
                continue

        # 2. Clickable tab / button / link
        for locator in [
            self.page.get_by_text("Lujerului", exact=False),
            self.page.locator('[data-club*="Lujerului"]'),
            self.page.locator('a[href*="lujerului"]'),
        ]:
            try:
                if await locator.count() > 0:
                    await locator.first.click(timeout=5_000)
                    await self.page.wait_for_load_state("networkidle", timeout=10_000)
                    logger.info("Club Lujerului selectat (click).")
                    return
            except Exception:
                continue

        # 3. URL parameter
        current = self.page.url
        if "lujerului" not in current.lower():
            try:
                await self.page.goto(
                    f"{self.SCHEDULE_URL}?club=lujerului",
                    wait_until="networkidle",
                    timeout=20_000,
                )
                logger.info("Pagina reincarcata cu parametrul ?club=lujerului.")
                return
            except Exception:
                pass

        logger.warning("Nu s-a putut selecta clubul Lujerului — pagina afisata poate include mai multe cluburi.")

    async def _find_schedule_items(self):
        """Return a list of element locators for individual class rows."""
        for sel in self._SCHEDULE_ITEM_SELECTORS:
            loc = self.page.locator(sel)
            count = await loc.count()
            if count > 0:
                logger.debug(f"Gasite {count} randuri in program cu selectorul '{sel}'")
                return [loc.nth(i) for i in range(count)]

        # Fallback: look for elements that contain known booking keywords
        logger.warning("Selectori standard negasiti — folosesc fallback pe text.")
        fallback = self.page.locator("*").filter(has_text=re.compile(r"Rezerv[aă]", re.IGNORECASE))
        count = await fallback.count()
        if count > 0:
            logger.debug(f"Fallback: {count} elemente cu text 'Rezerva'")
            return [fallback.nth(i) for i in range(min(count, 50))]

        await self._screenshot("schedule_not_found.png")
        logger.error("Nu s-au gasit elemente in programul de clase. Screenshot salvat.")
        return []

    async def _parse_class_item(self, locator) -> Optional[ClassInfo]:
        try:
            text = await locator.inner_text()
            if not text.strip():
                return None

            name = await self._extract_field(locator, [".class-name", ".name", "h3", "h4", ".title", ".class-title"])
            if not name:
                # Use first non-empty line as name
                lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
                name = lines[0] if lines else ""

            time_match = re.search(r"\b(\d{1,2}:\d{2})\b", text)
            time_str = time_match.group(1) if time_match else ""

            date_match = re.search(
                r"\b(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?)\b"
                r"|\b(luni|marti|miercuri|joi|vineri|sambata|duminica)\b",
                text, re.IGNORECASE
            )
            date_str = date_match.group(0) if date_match else ""

            duration_match = re.search(r"(\d{2,3})\s*min", text, re.IGNORECASE)
            duration = f"{duration_match.group(1)} min" if duration_match else ""

            instructor = await self._extract_field(
                locator, [".instructor", ".trainer", ".profesor", "[class*='instructor']"]
            )

            # Can book?
            can_book = False
            for sel in self._BOOK_BTN_SELECTORS:
                try:
                    btn = locator.locator(sel)
                    if await btn.count() > 0:
                        # Check it's not disabled
                        disabled = await btn.first.get_attribute("disabled")
                        aria = await btn.first.get_attribute("aria-disabled")
                        if disabled is None and aria != "true":
                            can_book = True
                        break
                except Exception:
                    continue

            # Already booked?
            already_booked = any(
                kw in text for kw in ["Anulează", "Anuleaza", "Rezervat", "Booked", "rezervat"]
            )
            if already_booked:
                can_book = False

            return ClassInfo(
                name=name,
                date=date_str,
                time=time_str,
                duration=duration,
                instructor=instructor,
                can_book=can_book,
                already_booked=already_booked,
                raw_text=text[:300],
            )

        except Exception as e:
            logger.debug(f"Eroare la parsarea unui element din program: {e}")
            return None

    async def _extract_field(self, parent_locator, selectors: list) -> str:
        for sel in selectors:
            try:
                el = parent_locator.locator(sel)
                if await el.count() > 0:
                    return (await el.first.inner_text()).strip()
            except Exception:
                continue
        return ""

    # ------------------------------------------------------------------
    # Booking
    # ------------------------------------------------------------------

    async def book_class(self, info: ClassInfo) -> Optional[ClassInfo]:
        """Click the reservation button for a class. Returns updated ClassInfo on success."""
        if not info.can_book:
            logger.info(f"Clasa '{info.name}' nu este disponibila pentru rezervare acum.")
            return None

        logger.info(f"Rezerv clasa: {info.name} | {info.date} {info.time}")

        # Re-locate the item on the live page (locators may be stale)
        booked = await self._click_book_for_class(info)

        if booked:
            info.booked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            info.confirmation = booked
            logger.success(f"Rezervare reusita: {info.name} ({info.date} {info.time})")
            return info

        logger.warning(f"Rezervarea pentru '{info.name}' nu a putut fi confirmata.")
        await self._screenshot(f"booking_failed_{info.name.replace(' ', '_')}.png")
        return None

    async def _click_book_for_class(self, info: ClassInfo) -> Optional[str]:
        """Find the booking button for a specific class and click it."""
        # Strategy 1: find a parent container that contains the class name,
        # then click the booking button inside it.
        name_clean = info.name.strip()

        # Try to locate the class row by name text
        containers = self.page.locator("*").filter(has_text=name_clean)
        count = await containers.count()

        for i in range(min(count, 10)):
            container = containers.nth(i)
            for sel in self._BOOK_BTN_SELECTORS:
                try:
                    btn = container.locator(sel)
                    if await btn.count() > 0:
                        await btn.first.click(timeout=8_000)
                        await asyncio.sleep(1.5)
                        return await self._detect_confirmation()
                except Exception:
                    continue

        # Strategy 2: use time as extra anchor
        if info.time:
            time_containers = self.page.locator("*").filter(
                has_text=re.compile(re.escape(info.time))
            )
            count2 = await time_containers.count()
            for i in range(min(count2, 5)):
                container = time_containers.nth(i)
                for sel in self._BOOK_BTN_SELECTORS:
                    try:
                        btn = container.locator(sel)
                        if await btn.count() > 0:
                            await btn.first.click(timeout=8_000)
                            await asyncio.sleep(1.5)
                            return await self._detect_confirmation()
                    except Exception:
                        continue

        return None

    async def _detect_confirmation(self) -> Optional[str]:
        """Check page state after clicking the booking button."""
        await asyncio.sleep(1)

        confirmation_phrases = [
            "Rezervare confirmata",
            "Rezervare efectuata",
            "Clasa a fost rezervata",
            "rezervat cu succes",
            "Confirmare rezervare",
            "Success",
        ]
        try:
            for phrase in confirmation_phrases:
                if await self.page.get_by_text(phrase, exact=False).count() > 0:
                    return phrase

            # Button changed to "Anulează" = booking succeeded
            if await self.page.get_by_text(re.compile(r"Anule[az][aă]", re.IGNORECASE)).count() > 0:
                return "Rezervare confirmata (buton Anuleaza vizibil)"

            # Check page source as last resort
            content = await self.page.content()
            if re.search(r"rezervat|confirmat", content, re.IGNORECASE):
                return "Rezervare posibil confirmata"

        except Exception:
            pass

        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _screenshot(self, filename: str):
        try:
            await self.page.screenshot(path=filename, full_page=True)
            logger.debug(f"Screenshot salvat: {filename}")
        except Exception:
            pass
