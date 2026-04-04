import websocket
import json
import requests
import locale
from datetime import datetime
# SPEC §6.4 T-DB-2 — use connection pool
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.db_pool import get_conn, put_conn
from shared.get_cookies import get_cookies, get_ws_url, get_active_gfgc_topics

header = [
    "instrument",       # M:<instrument>
    "internal_id",      # 1
    "seq_or_phase",     # 2
    "bid_price",        # Compra
    "ask_price",        # Venta
    "bid_size",         # Vol. C
    "last_price",       # Últ
    "timestamp",        # Hora
    "turnover",         # Vol. Nominal
    "ask_size",         # Vol. V
    "open",             # Apertura
    "high",             # Máx
    "low",              # Mín
    "reserved2",        # empty
    "prev_close",       # Cie/Set Ant
    "prev_date",        # Fecha Cierre Anterior
    "r1", "r2", "r3",   # unknown
    "settlement_price", # Cie/Set
    "settlement_date"   # Fecha Cie/Set
]


# SPEC §1 P2 — WS URL fetched at runtime from Matriz profile (session_id + conn_id)
url = get_ws_url()

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache"
}



def on_message(ws, message):
    # SPEC §2.3 — Matriz WS messages are JSON arrays wrapping a pipe-delimited string
    try:
        inner = json.loads(message)
        if not isinstance(inner, list) or not inner:
            return
        raw = inner[0]
    except (json.JSONDecodeError, IndexError):
        raw = message  # fallback: treat as raw pipe string

    fields = raw.split("|")
    try:
        output = {
            "instrument": fields[0],
            "bid_volume": int(fields[2]),
            "bid_price": float(fields[3]),
            "ask_price": float(fields[4]),
            "ask_volume": int(fields[5]),
            "last_price": float(fields[6]),
            "total_volume": int(fields[10]),
            "low": float(fields[12]),   # SPEC §2.3 I-20 T-DB-8: index 12 = low
            "high": float(fields[11]),  # SPEC §2.3 I-20 T-DB-8: index 11 = high
            "prev_close": float(fields[13]),
            "timestamp": fields[7],
        }
    except (IndexError, ValueError):
        return  # malformed message — skip silently

    conn = get_conn()
    try:
        cur = conn.cursor()
        query = """
    INSERT INTO ticks (
        time, instrument, bid_volume, bid_price,
        ask_price, ask_volume, last_price, total_volume,
        low, high, prev_close
    )
    VALUES (
        %(timestamp)s, %(instrument)s, %(bid_volume)s, %(bid_price)s,
        %(ask_price)s, %(ask_volume)s, %(last_price)s, %(total_volume)s,
        %(low)s, %(high)s, %(prev_close)s
    )
    """
        cur.execute(query, output)
        conn.commit()
        cur.close()
    finally:
        put_conn(conn)

    #headers = output.keys()
    #print(tabulate([output.values()], headers=headers, tablefmt="plain"))
    #    print("Parsed data:", output)


def on_error(ws, error):
    print("Error:", error)

def on_close(ws, close_status_code, close_msg):
    print("Closed")


def on_open(ws):
    # SPEC §1 P2 — subscribe to active DLR futures contract; year derived at runtime
    locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')
    now = datetime.now()
    month_name = now.strftime('%B')[:3].upper()
    year = now.strftime('%y')  # 2-digit year, e.g. "26"

    cookie = get_cookies()
    gfgc_topics = get_active_gfgc_topics(cookie)

    ws.send(json.dumps({
        "_req": "S",
        "topicType": "md",
        "topics": [
            f"md.rx_DDF_DLR_{month_name}{year}",
            f"md.rx_DDF_DLR_{month_name}{year}A",
            "md.bm_MERV_AL30_24hs",
            "md.bm_MERV_AL30D_24hs",
            "md.bm_MERV_PESOS_1D",
            "md.bm_MERV_SUPV_24hs",
            "md.bm_MERV_GGAL_24hs",
            "md.bm_MERV_GGALD_24hs",
            "md.bm_MERV_BBDD_24hs",
            "md.bm_MERV_PBRD_24hs",
            *gfgc_topics,
        ],
        "replace": True
    }))

if __name__ == "__main__":
    
    ws = websocket.WebSocketApp(url,
                                header=[f"{k}: {v}" for k, v in headers.items()],
                                on_open=on_open,
                                on_message=on_message,
                                on_error=on_error,
                                on_close=on_close)
    ws.run_forever()
