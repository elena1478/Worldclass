"""
Worldclass Booking Automation — Entry Point

Rulare:
  python main.py            # porneste serviciul continuu (verifica la fiecare 30 min)
  python main.py --once     # verifica o singura data si iese
  python main.py --dry-run  # afiseaza clasele disponibile fara sa rezerve
"""

import argparse
import asyncio
import sys

from loguru import logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import Config
from worldclass_client import WorldclassClient


# Configure structured logging: console + rotating file
logger.remove()
logger.add(sys.stderr, level="INFO", colorize=True,
           format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")
logger.add("worldclass_booking.log", rotation="7 days", retention="30 days",
           level="DEBUG", encoding="utf-8")


async def run_booking_check():
    """Single booking cycle: login → find classes → book → notify."""
    logger.info("=" * 55)
    logger.info("Verificare clase disponibile...")

    async with WorldclassClient() as client:
        if not await client.login():
            logger.error("Autentificare esuata. Incearca din nou mai tarziu.")
            return

        classes = await client.get_bookable_classes()

        if not classes:
            logger.info("Nicio clasa de pilates/stretching gasita la Lujerului.")
            return

        booked_count = 0
        skipped_booked = 0

        for cls in classes:
            if cls.already_booked:
                skipped_booked += 1
                logger.info(f"  [deja rezervata] {cls.name} {cls.date} {cls.time}")
                continue

            if not cls.can_book:
                logger.info(
                    f"  [nedisponibila] {cls.name} {cls.date} {cls.time} "
                    f"(fereastra de 26h nu s-a deschis inca)"
                )
                continue

            if Config.DRY_RUN:
                logger.info(f"  [dry-run] As rezerva: {cls.name} {cls.date} {cls.time}")
                continue

            result = await client.book_class(cls)
            if result:
                booked_count += 1

        logger.info(
            f"Sumar: {booked_count} rezervari noi | "
            f"{skipped_booked} deja rezervate | "
            f"{len(classes) - booked_count - skipped_booked} nedisponibile inca"
        )
        logger.info("=" * 55)


def main():
    parser = argparse.ArgumentParser(
        description="Worldclass Booking Automation — rezerva automat pilates si stretching la Lujerului"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Afiseaza clasele disponibile fara sa faca rezervari"
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Ruleaza o singura verificare si iese"
    )
    args = parser.parse_args()

    Config.DRY_RUN = args.dry_run

    if not Config.validate():
        sys.exit(1)

    if args.dry_run:
        logger.warning("DRY-RUN activ — nicio rezervare nu va fi facuta.")

    if args.once:
        asyncio.run(run_booking_check())
        return

    # --- Continuous service ---
    # Politica Worldclass: rezervarile se deschid cu 26 de ore inainte.
    # Rulam verificarea la fiecare CHECK_INTERVAL_MINUTES minute.
    # La fiecare verificare, orice clasa care tocmai a intrat in fereastra de
    # 26 de ore va fi rezervata imediat.

    scheduler = AsyncIOScheduler(timezone="Europe/Bucharest")
    scheduler.add_job(
        run_booking_check,
        trigger=IntervalTrigger(minutes=Config.CHECK_INTERVAL_MINUTES),
        id="booking_check",
        name="Verificare si rezervare clase Worldclass",
        replace_existing=True,
        max_instances=1,
    )

    logger.info(
        f"Serviciu pornit — verificare la fiecare {Config.CHECK_INTERVAL_MINUTES} minute. "
        f"Apasa Ctrl+C pentru a opri."
    )

    # Run once immediately at startup, then follow schedule
    scheduler.start()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(run_booking_check())

    try:
        loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Serviciu oprit de utilizator.")
        scheduler.shutdown()


if __name__ == "__main__":
    main()
