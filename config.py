import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Worldclass account credentials
    WC_EMAIL: str = os.getenv("WC_EMAIL", "")
    WC_PASSWORD: str = os.getenv("WC_PASSWORD", "")

    # Booking preferences
    TARGET_CLUB: str = "Lujerului"
    TARGET_CLASSES: list = ["pilates", "fit pilates", "stretching", "stretch"]

    # Worldclass policy: bookings open 26 hours before class start
    BOOKING_WINDOW_HOURS: int = 26

    # How often to poll for new bookable classes (minutes)
    CHECK_INTERVAL_MINUTES: int = int(os.getenv("CHECK_INTERVAL_MINUTES", "30"))

    # Run headless browser (False = visible window, useful for debugging)
    HEADLESS: bool = os.getenv("HEADLESS", "true").lower() == "true"

    # Set at runtime by CLI argument
    DRY_RUN: bool = False

    @classmethod
    def validate(cls) -> bool:
        missing = []
        if not cls.WC_EMAIL:
            missing.append("WC_EMAIL")
        if not cls.WC_PASSWORD:
            missing.append("WC_PASSWORD")

        if missing:
            from loguru import logger
            logger.error(f"Configuratie lipsa in .env: {', '.join(missing)}")
            return False
        return True
