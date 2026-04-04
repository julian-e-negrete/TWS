# scrapers/matriz/run.py — P2 Matriz WS tick ingestor / SPEC §1 P2 / T-MOD-1
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
import json
from datetime import datetime
import websocket
from scrapers.logger import get_logger
from scrapers.fetch import log_ws_message
from scrapers.notifier import notify
from shared.db_pool import get_conn, put_conn
from shared.models import Tick
from pydantic import ValidationError

_log = get_logger("matriz")

WS_URL = "wss://matriz.eco.xoms.com.ar/ws"
WS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
}
TOPICS = [
    "md.bm_MERV_AL30_24hs", "md.bm_MERV_AL30D_24hs",
    "md.bm_MERV_GGAL_24hs", "md.bm_MERV_GGALD_24hs",
    "md.bm_MERV_BBDD_24hs", "md.bm_MERV_PBRD_24hs",
]
INSERT_SQL = """
    INSERT INTO ticks (time, instrument, bid_volume, bid_price,
        ask_price, ask_volume, last_price, total_volume, low, high, prev_close)
    VALUES (%(time)s, %(instrument)s, %(bid_volume)s, %(bid_price)s,
        %(ask_price)s, %(ask_volume)s, %(last_price)s, %(total_volume)s,
        %(low)s, %(high)s, %(prev_close)s)
"""


def _on_message(ws, message):
    log_ws_message("matriz", message)
    fields = message.split("|")
    if len(fields) < 14:
        return
    try:
        tick = Tick(
            time=datetime.now(),
            instrument=fields[0],
            bid_volume=int(fields[2]),
            bid_price=fields[3],
            ask_price=fields[4],
            ask_volume=int(fields[5]),
            last_price=fields[6],
            total_volume=int(fields[10]),
            high=fields[11],  # SPEC §2.3: index 11 = high (was swapped, I-20)
            low=fields[12],   # SPEC §2.3: index 12 = low
            prev_close=fields[13],
        )
    except ValidationError as e:
        _log.error("tick validation failed: %s | raw=%s", e, message[:200])
        return

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(INSERT_SQL, tick.model_dump())
        conn.commit()
    except Exception as e:
        conn.rollback()
        _log.error("DB insert failed: %s", e)
    finally:
        put_conn(conn)


def _on_open(ws):
    ws.send(json.dumps({"_req": "S", "topicType": "md", "topics": TOPICS, "replace": True}))
    _log.info("matriz WS subscribed to %d topics", len(TOPICS))


def _on_error(ws, error):
    _log.error("matriz WS error: %s", error)


def _on_close(ws, code, msg):
    _log.info("matriz WS closed: %s %s", code, msg)


def run():
    ws = websocket.WebSocketApp(
        WS_URL,
        header=[f"{k}: {v}" for k, v in WS_HEADERS.items()],
        on_open=_on_open,
        on_message=_on_message,
        on_error=_on_error,
        on_close=_on_close,
    )
    ws.run_forever()


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        notify("matriz", e)
        raise
