"""
DB poller — queries row counts from the scraper server (244) and exposes
them as Prometheus gauges on :8004. Scraped by Prometheus as ingestion metrics.
Runs as a background thread; no FastAPI needed.
"""
import time
import threading
from datetime import datetime, timezone
import httpx
from prometheus_client import Gauge, start_http_server
from sqlalchemy import text
from finance.utils.db_pool import get_pg_engine
from finance.utils.logger import logger

PORT = 8004
INTERVAL = 30  # seconds between polls

TICKS_TOTAL = Gauge("algotrading_db_ticks_total", "Total rows in ticks table", ["instrument"])
ORDERS_TOTAL = Gauge("algotrading_db_orders_total", "Total rows in orders table", ["instrument"])
ORDERS_LAST_5M = Gauge("algotrading_db_orders_last_5m", "Orders inserted in last 5 minutes", ["instrument"])
BINANCE_TOTAL = Gauge("algotrading_db_binance_ticks_total", "Total rows in binance_ticks table", ["symbol"])
TICKS_LAST_5M = Gauge("algotrading_db_ticks_last_5m", "Ticks inserted in last 5 minutes", ["instrument"])
BINANCE_LAST_5M = Gauge("algotrading_db_binance_last_5m", "Binance ticks inserted in last 5 minutes", ["symbol"])

BINANCE_OPEN  = Gauge("algotrading_binance_ohlcv_open",  "Binance 1h bar open",  ["symbol"])
BINANCE_HIGH  = Gauge("algotrading_binance_ohlcv_high",  "Binance 1h bar high",  ["symbol"])
BINANCE_LOW   = Gauge("algotrading_binance_ohlcv_low",   "Binance 1h bar low",   ["symbol"])
BINANCE_CLOSE = Gauge("algotrading_binance_ohlcv_close", "Binance 1h bar close", ["symbol"])
BINANCE_VOL   = Gauge("algotrading_binance_ohlcv_volume","Binance 1h bar volume",["symbol"])
BINANCE_BUY_VOL  = Gauge("algotrading_binance_buy_volume",  "Binance buy volume last 5m",  ["symbol"])
BINANCE_SELL_VOL = Gauge("algotrading_binance_sell_volume", "Binance sell volume last 5m", ["symbol"])

SCRAPER_ACTIVE     = Gauge("algotrading_scraper_active",      "Scraper service active (1=up, 0=down)", ["service"])
SCRAPER_LAST_INSERT = Gauge("algotrading_scraper_last_insert", "Unix timestamp of last DB insert",      ["table"])

SCRAPER_STATUS_URL = "http://100.112.16.115:9000/status"


def _poll_scraper_status():
    try:
        data = httpx.get(SCRAPER_STATUS_URL, timeout=5).json()
        for svc, info in data["services"].items():
            SCRAPER_ACTIVE.labels(service=svc).set(1 if info["active"] else 0)
        for table, ts in data["last_insert"].items():
            if ts:
                dt = datetime.fromisoformat(ts).astimezone(timezone.utc)
                SCRAPER_LAST_INSERT.labels(table=table).set(dt.timestamp())
    except Exception as e:
        logger.error("Scraper status poll error: {e}", e=e)


def _poll():
    engine = get_pg_engine()
    while True:
        try:
            with engine.connect() as conn:
                conn.execute(text("SET statement_timeout = '25s'"))
                for row in conn.execute(text(
                    "SELECT instrument, COUNT(*) FROM ticks "
                    "WHERE instrument NOT LIKE '[%' GROUP BY instrument"
                )):
                    TICKS_TOTAL.labels(instrument=row[0]).set(row[1])

                # last-5m: get all known instruments, set 0 for inactive ones
                recent = {}
                for row in conn.execute(text(
                    "SELECT instrument, COUNT(*) FROM ticks "
                    "WHERE instrument NOT LIKE '[%' "
                    "AND time > NOW() - INTERVAL '5 minutes' GROUP BY instrument"
                )):
                    recent[row[0]] = row[1]

                for row in conn.execute(text(
                    "SELECT DISTINCT instrument FROM ticks WHERE instrument NOT LIKE '[%'"
                )):
                    inst = row[0]
                    TICKS_LAST_5M.labels(instrument=inst).set(recent.get(inst, 0))

                # orders last-5m: same pattern as ticks
                recent_orders = {}
                for row in conn.execute(text(
                    "SELECT instrument, COUNT(*) FROM orders "
                    "WHERE time > NOW() - INTERVAL '5 minutes' GROUP BY instrument"
                )):
                    recent_orders[row[0]] = row[1]

                known_order_instruments = []
                for row in conn.execute(text(
                    "SELECT instrument, COUNT(*) FROM orders GROUP BY instrument"
                )):
                    ORDERS_TOTAL.labels(instrument=row[0]).set(row[1])
                    known_order_instruments.append(row[0])

                for inst in known_order_instruments:
                    ORDERS_LAST_5M.labels(instrument=inst).set(recent_orders.get(inst, 0))

                for row in conn.execute(text(
                    "SELECT symbol, COUNT(*) FROM binance_ticks GROUP BY symbol"
                )):
                    BINANCE_TOTAL.labels(symbol=row[0]).set(row[1])

                for row in conn.execute(text(
                    "SELECT symbol, COUNT(*) FROM binance_ticks "
                    "WHERE timestamp > NOW() - INTERVAL '5 minutes' GROUP BY symbol"
                )):
                    BINANCE_LAST_5M.labels(symbol=row[0]).set(row[1])

                # Latest 1h OHLCV bar per symbol (for candlestick)
                for row in conn.execute(text("""
                    SELECT symbol,
                        FIRST(open, timestamp)  AS open,
                        MAX(high)               AS high,
                        MIN(low)                AS low,
                        LAST(close, timestamp)  AS close,
                        SUM(volume)             AS volume
                    FROM binance_ticks
                    WHERE timestamp > NOW() - INTERVAL '1 hour'
                    GROUP BY symbol
                """)):
                    s = row[0]
                    BINANCE_OPEN.labels(symbol=s).set(float(row[1] or 0))
                    BINANCE_HIGH.labels(symbol=s).set(float(row[2] or 0))
                    BINANCE_LOW.labels(symbol=s).set(float(row[3] or 0))
                    BINANCE_CLOSE.labels(symbol=s).set(float(row[4] or 0))
                    BINANCE_VOL.labels(symbol=s).set(float(row[5] or 0))

                # Buy/sell volume last 5m from binance_trades
                for row in conn.execute(text("""
                    SELECT symbol,
                        SUM(CASE WHEN NOT is_buyer_maker THEN qty ELSE 0 END) AS buy_vol,
                        SUM(CASE WHEN is_buyer_maker THEN qty ELSE 0 END) AS sell_vol
                    FROM binance_trades
                    WHERE time > NOW() - INTERVAL '5 minutes'
                    GROUP BY symbol
                """)):
                    s = row[0]
                    BINANCE_BUY_VOL.labels(symbol=s).set(float(row[1] or 0))
                    BINANCE_SELL_VOL.labels(symbol=s).set(float(row[2] or 0))

        except Exception as e:
            logger.error("DB poller error: {e}", e=e)

        _poll_scraper_status()
        time.sleep(INTERVAL)


if __name__ == "__main__":
    start_http_server(PORT)
    logger.info("DB poller metrics server started on :{port}", port=PORT)
    _poll()
