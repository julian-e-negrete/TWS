"""
RabbitMQ publisher for backtest results.
Publishes to queue 'backtest_results'; a consumer persists to DB asynchronously.
Falls back to direct DB write if RabbitMQ is unavailable.
"""
import json
import pika
from finance.config import settings
from finance.utils.logger import logger

QUEUE = "backtest_results"
_conn: pika.BlockingConnection | None = None
_ch = None


def _get_channel():
    global _conn, _ch
    try:
        if _conn is None or _conn.is_closed:
            creds = pika.PlainCredentials(settings.rabbitmq.user, settings.rabbitmq.password)
            params = pika.ConnectionParameters(
                host=settings.rabbitmq.host,
                port=settings.rabbitmq.port,
                virtual_host=settings.rabbitmq.vhost,
                credentials=creds,
                connection_attempts=1,
                socket_timeout=2,
            )
            _conn = pika.BlockingConnection(params)
            _ch = _conn.channel()
            _ch.queue_declare(queue=QUEUE, durable=True)
    except Exception as e:
        logger.warning("RabbitMQ unavailable: {e}", e=e)
        _conn = None
        _ch = None
    return _ch


def publish_result(payload: dict) -> bool:
    """Publish backtest result to RabbitMQ. Returns True if published."""
    ch = _get_channel()
    if ch is None:
        return False
    try:
        ch.basic_publish(
            exchange="",
            routing_key=QUEUE,
            body=json.dumps(payload),
            properties=pika.BasicProperties(delivery_mode=2),  # persistent
        )
        return True
    except Exception as e:
        logger.warning("RabbitMQ publish failed: {e}", e=e)
        return False
