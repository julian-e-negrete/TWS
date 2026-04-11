from config import ALERT_THRESHOLDS
from config import SMTP_SERVER, SMTP_PORT, EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER
import smtplib
from email.message import EmailMessage


def evaluate_alerts(rsi_value):
    if rsi_value > ALERT_THRESHOLDS["RSI_OVERBOUGHT"]:
        print("[ALERT] RSI Overbought - Consider Selling")
    elif rsi_value < ALERT_THRESHOLDS["RSI_OVERSOLD"]:
        print("[ALERT] RSI Oversold - Consider Buying")


def warning_price(price_series):
    latest_price = price_series.iloc[-1]  # Get the last closing price
    if(latest_price > 1350):
        
        # Create email message
        msg = EmailMessage()
        msg["Subject"] = "USDTARS ALERT > 1350"
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECEIVER
        msg.set_content("USDTARS > 1350")

        # Send the email
        try:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls()  # Secure the connection
                server.login(EMAIL_SENDER, EMAIL_PASSWORD)
                server.send_message(msg)
            print("Email sent successfully!")
        except Exception as e:
            print(f"Error: {e}")
        print("[ALERT] USDT/ARS > 1350!!!!")




def warning_price_BTC(price_series):
    latest_price = price_series.iloc[-1]  # Get the last closing price
    if(latest_price > 100000):
        
        # Create email message
        msg = EmailMessage()
        msg["Subject"] = "BTC ALERT > 100.000"
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECEIVER
        msg.set_content("BTC > 100.000")

        # Send the email
        try:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls()  # Secure the connection
                server.login(EMAIL_SENDER, EMAIL_PASSWORD)
                server.send_message(msg)
            print("Email sent successfully!")
        except Exception as e:
            print(f"Error: {e}")
        print("[ALERT] BTC > 100.000!!!!")
        
    elif(latest_price < 75000):
        # Create email message
        msg = EmailMessage()
        msg["Subject"] = "BTC ALERT < 75.000"
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECEIVER
        msg.set_content("BTC < 75.000")

        # Send the email
        try:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls()  # Secure the connection
                server.login(EMAIL_SENDER, EMAIL_PASSWORD)
                server.send_message(msg)
            print("Email sent successfully!")
        except Exception as e:
            print(f"Error: {e}")
        print("[ALERT] BTC < 75.000!!!!")
        