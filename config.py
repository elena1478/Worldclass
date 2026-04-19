import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Worldclass account credentials
    WC_EMAIL: str = os.getenv("WC_EMAIL", "")
    WC_PASSWORD: str = os.getenv("WC_PASSWORD", "")

    # Email notification settings
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    NOTIFY_EMAIL: str = os.getenv("NOTIFY_EMAIL", "")

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
        if not cls.SMTP_USER:
            missing.append("SMTP_USER")
        if not cls.SMTP_PASSWORD:
            missing.append("SMTP_PASSWORD")
        if not cls.NOTIFY_EMAIL:
            missing.append("NOTIFY_EMAIL")

        if missing:
            from loguru import logger
            logger.error(f"Configuratie lipsa in .env: {', '.join(missing)}")
            logger.error("Copiaza .env.example in .env si completeaza credentialele tale.")
            return False
        return True
