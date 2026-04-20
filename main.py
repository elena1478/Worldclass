"""
Worldclass Booking Automation — Entry Point

Rulare locala:
  python main.py --once     # o singura verificare
  python main.py --dry-run  # verifica fara sa rezerve

Pe GitHub Actions ruleaza automat la fiecare 5 minute (vezi .github/workflows/booking.yml).
"""

import argparse
import asyncio
import sys
from datetime import datetime, timedelta

from loguru import logger
from zoneinfo import ZoneInfo

from config import Config
from worldclass_client import BUCHAREST_TZ, WorldclassClient

# ---------------------------------------------------------------------------
# Timing constants
# ---------------------------------------------------------------------------

# GitHub Actions cron runs every 5 min but can start with 1-3 min jitter.
# We look ahead 8 min to always catch the window that opens in this interval.
LOOKAHEAD_SECONDS = 8 * 60

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger.remove()
logger.add(
    sys.stderr, level="INFO", colorize=True,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
)
logger.add(
    "worldclass_booking.log", rotation="7 days", retention="30 days",
    level="DEBUG", encoding="utf-8",
)

# ---------------------------------------------------------------------------
# Core booking logic
# ---------------------------------------------------------------------------

async def run_smart_booking():
    """
    One execution cycle (called every 5 min by GitHub Actions):

    1. Fetch the LIVE schedule from worldclass.ro — always fresh, handles
       trainer changes and holiday cancellations automatically.
    2. For every pilates/stretching class at Lujerului in the next ~32 h:
         booking_opens_at = class_datetime - 26h
         a) Window opened 0-5 min ago  → book immediately (grace period)
         b) Window opens in 0-8 min    → sleep until EXACT moment, then book
         c) Anything else              → skip (handled by a future run)
    3. Worldclass sends its own confirmation email after each booking.
    """
    now = datetime.now(tz=BUCHAREST_TZ)
    logger.info("=" * 60)
    logger.info(f"Verificare la {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    async with WorldclassClient() as client:
        if not await client.login():
            logger.error("Login esuat — run abandonat.")
            return

        # Always fetch the live schedule (handles any programme changes)
        classes = await client.get_all_upcoming_classes()

        if not classes:
            logger.info("Nicio clasa pilates/stretching gasita la Lujerului.")
            logger.info("=" * 60)
            return

        booked_this_run   = 0
        skipped_booked    = 0
        upcoming_count    = 0

        for cls in classes:
            label = f"{cls.name} | {cls.date} {cls.time}"

            if cls.already_booked:
                skipped_booked += 1
                logger.info(f"  [deja rezervata]  {label}")
                continue

            # ----------------------------------------------------------------
            # If we have a class_datetime we can do precise scheduling.
            # If not (datetime couldn't be parsed), fall back to checking
            # whether the booking button is currently active.
            # ----------------------------------------------------------------
            if cls.class_datetime is not None:
                booking_opens = cls.class_datetime - timedelta(hours=Config.BOOKING_WINDOW_HOURS)
                wait_sec = (booking_opens - now).total_seconds()
                class_sec = (cls.class_datetime - now).total_seconds()

                # Class already happened — skip
                if class_sec <= 0:
                    logger.debug(f"  [clasa trecuta]  {label}")
                    continue

                # Booking window opens too far in the future — skip, next run handles it
                if wait_sec > LOOKAHEAD_SECONDS:
                    upcoming_count += 1
                    logger.debug(
                        f"  [viitor]  {label} — fereastra se deschide "
                        f"la {booking_opens.strftime('%H:%M')} "
                        f"(in {wait_sec/3600:.1f}h)"
                    )
                    continue

                # Window opens within LOOKAHEAD — sleep to the exact second
                if wait_sec > 0:
                    logger.info(
                        f"  [astept {wait_sec:.0f}s]  {label} — "
                        f"rezervare exacta la {booking_opens.strftime('%H:%M:%S')}"
                    )
                    if not Config.DRY_RUN:
                        await asyncio.sleep(wait_sec)
                    else:
                        logger.info(f"  [dry-run] As astepta {wait_sec:.0f}s si as rezerva.")
                        continue

                # wait_sec <= 0: fereastra e deschisa (de secunde sau de ore) —
                # daca clasa n-a trecut inca, incercam rezervarea
                if Config.DRY_RUN:
                    logger.info(f"  [dry-run] As rezerva: {label}")
                    continue

            else:
                # No datetime parsed — use booking button presence as signal
                if not cls.can_book:
                    logger.info(f"  [nedisponibila]  {label} (fara datetime, buton inactiv)")
                    continue
                if Config.DRY_RUN:
                    logger.info(f"  [dry-run] As rezerva (buton activ): {label}")
                    continue

            result = await client.book_class(cls)
            if result:
                booked_this_run += 1
                logger.success(
                    f"  [REZERVAT]  {result.name} | {result.date} {result.time} "
                    f"la {result.booked_at}"
                )
            else:
                logger.warning(f"  [EROARE rezervare]  {label}")

        logger.info(
            f"Sumar: {booked_this_run} rezervari noi | "
            f"{skipped_booked} deja rezervate | "
            f"{upcoming_count} clase viitoare (tratate de run-uri ulterioare)"
        )
        logger.info("=" * 60)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Worldclass booking automation — pilates & stretching la Lujerului"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Ruleaza fara rezervari reale")
    parser.add_argument("--once", action="store_true",
                        help="Un singur run si iese (comportamentul GitHub Actions)")
    args = parser.parse_args()

    Config.DRY_RUN = args.dry_run

    if not Config.validate():
        sys.exit(1)

    if args.dry_run:
        logger.warning("DRY-RUN — nicio rezervare nu va fi efectuata.")

    # GitHub Actions always calls --once; locally you can omit it to loop.
    if args.once or True:   # always run once; scheduler is handled externally by GHA cron
        asyncio.run(run_smart_booking())


if __name__ == "__main__":
    main()
