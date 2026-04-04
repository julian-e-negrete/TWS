# T-ERR-1 / SPEC §4 I-4 — email notifier for unhandled exceptions
import smtplib
from email.message import EmailMessage
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.settings import SMTP_SERVER, SMTP_PORT, EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER
from core.scrapers.logger import get_logger

_log = get_logger("notifier")

def notify(platform: str, error: Exception) -> None:
    msg = EmailMessage()
    msg["Subject"] = f"[scraper] {platform} error: {type(error).__name__}"
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    msg.set_content(str(error))
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as s:
            s.starttls()
            s.login(EMAIL_SENDER, EMAIL_PASSWORD)
            s.send_message(msg)
    except Exception as e:
        _log.error("notifier failed to send: %s", e)
    _log.error("[%s] %s: %s", platform, type(error).__name__, error)
