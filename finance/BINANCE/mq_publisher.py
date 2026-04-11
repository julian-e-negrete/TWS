"""
BT-15: RabbitMQ publisher for Binance kline ticks.
Publishes to exchange 'market.ticks', routing key 'binance.<symbol>'.
Non-blocking: failures are logged and skipped, never crash the monitor.
"""
import json
import pika
from finance.config import settings
from finance.utils.logger import logger

EXCHANGE = "market.ticks"


def _get_channel():
    creds = pika.PlainCredentials(
        settings.rabbitmq.user,
        settings.rabbitmq.password,
    )
    conn = pika.BlockingConnection(
        pika.ConnectionParameters(host="localhost", port=5672, credentials=creds)
    )
    ch = conn.channel()
    ch.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)
    return conn, ch


def publish_tick(symbol: str, tick: dict) -> None:
    """Publish a single kline tick. Silently skips if RabbitMQ is unavailable."""
    try:
        conn, ch = _get_channel()
        ch.basic_publish(
            exchange=EXCHANGE,
            routing_key=f"binance.{symbol}",
            body=json.dumps(tick, default=str),
            properties=pika.BasicProperties(delivery_mode=2),  # persistent
        )
        conn.close()
    except Exception as e:
        logger.warning("RabbitMQ publish failed for {s}: {e}", s=symbol, e=e)
