import smtplib
from email.message import EmailMessage
from finance.utils.logger import logger
from finance.config import settings

RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
USDTARS_ALERT_THRESHOLD = 1350


def evaluate_alerts(rsi_value: float):
    if rsi_value > RSI_OVERBOUGHT:
        logger.warning("RSI Overbought ({rsi:.2f}) — Consider Selling", rsi=rsi_value)
    elif rsi_value < RSI_OVERSOLD:
        logger.warning("RSI Oversold ({rsi:.2f}) — Consider Buying", rsi=rsi_value)


def warning_price(price: float):
    if price <= USDTARS_ALERT_THRESHOLD:
        return
    logger.warning("USDTARS > {threshold} (current: {price})", threshold=USDTARS_ALERT_THRESHOLD, price=price)
    try:
        msg = EmailMessage()
        msg["Subject"] = f"USDTARS ALERT > {USDTARS_ALERT_THRESHOLD}"
        msg["From"] = settings.mail.username
        msg["To"] = settings.mail.receiver
        msg.set_content(f"USDTARS = {price} > {USDTARS_ALERT_THRESHOLD}")
        with smtplib.SMTP(settings.mail.smtp_server, settings.mail.smtp_port) as server:
            server.starttls()
            server.login(settings.mail.username, settings.mail.password)
            server.send_message(msg)
        logger.info("Alert email sent for USDTARS={price}", price=price)
    except Exception as e:
        logger.error("Failed to send alert email: {e}", e=e)
