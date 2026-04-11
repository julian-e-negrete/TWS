"""
RabbitMQ message queue integration — Tarea 10.2
Publisher: send market events to queues.
Consumer: receive and persist via ingestion microservice.
"""
import json
import threading
from typing import Callable

import pika
import pika.exceptions

from finance.config.settings import settings
from finance.utils.logger import logger

EXCHANGE = "algotrading"
QUEUE_TICKS = "ticks.ingest"
QUEUE_OHLCV = "ohlcv.ingest"


def _connection() -> pika.BlockingConnection:
    mq = settings.rabbitmq
    params = pika.ConnectionParameters(
        host=mq.host,
        port=mq.port,
        virtual_host=mq.vhost,
        credentials=pika.PlainCredentials(mq.user, mq.password),
        heartbeat=60,
        blocked_connection_timeout=30,
    )
    return pika.BlockingConnection(params)


def _declare(channel: pika.adapters.blocking_connection.BlockingChannel):
    channel.exchange_declare(exchange=EXCHANGE, exchange_type="direct", durable=True)
    for queue in (QUEUE_TICKS, QUEUE_OHLCV):
        channel.queue_declare(queue=queue, durable=True)
        channel.queue_bind(queue=queue, exchange=EXCHANGE, routing_key=queue)


# ---------------------------------------------------------------------------
# Publisher
# ---------------------------------------------------------------------------

class Publisher:
    """Thread-safe RabbitMQ publisher."""

    def __init__(self):
        self._lock = threading.Lock()
        self._conn = None
        self._channel = None

    def _ensure_connected(self):
        if self._conn is None or self._conn.is_closed:
            self._conn = _connection()
            self._channel = self._conn.channel()
            _declare(self._channel)

    def publish(self, routing_key: str, payload: dict):
        with self._lock:
            try:
                self._ensure_connected()
                self._channel.basic_publish(
                    exchange=EXCHANGE,
                    routing_key=routing_key,
                    body=json.dumps(payload, default=str),
                    properties=pika.BasicProperties(
                        delivery_mode=2,  # persistent
                        content_type="application/json",
                    ),
                )
                logger.debug("Published to {rk}: {payload}", rk=routing_key, payload=payload)
            except pika.exceptions.AMQPError as e:
                logger.error("RabbitMQ publish failed: {e}", e=e)
                self._conn = None  # force reconnect next time
                raise

    def publish_tick(self, tick: dict):
        self.publish(QUEUE_TICKS, tick)

    def publish_ohlcv(self, bar: dict):
        self.publish(QUEUE_OHLCV, bar)

    def close(self):
        with self._lock:
            if self._conn and self._conn.is_open:
                self._conn.close()


# ---------------------------------------------------------------------------
# Consumer
# ---------------------------------------------------------------------------

class Consumer:
    """Blocking RabbitMQ consumer. Run in a dedicated thread."""

    def __init__(self, queue: str, handler: Callable[[dict], None], prefetch: int = 10):
        self.queue = queue
        self.handler = handler
        self.prefetch = prefetch

    def _on_message(self, channel, method, properties, body):
        try:
            payload = json.loads(body)
            self.handler(payload)
            channel.basic_ack(delivery_tag=method.delivery_tag)
        except Exception as e:
            logger.error("Consumer handler error: {e}", e=e)
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def run(self):
        conn = _connection()
        channel = conn.channel()
        _declare(channel)
        channel.basic_qos(prefetch_count=self.prefetch)
        channel.basic_consume(queue=self.queue, on_message_callback=self._on_message)
        logger.info("Consumer started on queue={queue}", queue=self.queue)
        try:
            channel.start_consuming()
        except KeyboardInterrupt:
            channel.stop_consuming()
        finally:
            conn.close()
