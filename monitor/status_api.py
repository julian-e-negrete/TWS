# monitor/status_api.py — SPEC §6 service health endpoint
import subprocess
from datetime import datetime, timezone
from fastapi import FastAPI
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.db_pool import get_conn, put_conn

app = FastAPI()

def _systemd_status(unit: str) -> dict:
    r = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True)
    active = r.stdout.strip() == "active"
    r2 = subprocess.run(["systemctl", "show", unit, "--property=ActiveEnterTimestamp"],
                        capture_output=True, text=True)
    ts = r2.stdout.strip().replace("ActiveEnterTimestamp=", "") or None
    return {"active": active, "since": ts}

def _last_insert(table: str, time_col: str) -> str | None:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT MAX({time_col}) FROM {table}")
        row = cur.fetchone()
        cur.close()
        return row[0].isoformat() if row and row[0] else None
    finally:
        put_conn(conn)

def _binance_last_5m() -> int:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM binance_ticks WHERE timestamp > now() - interval '5 minutes'")
        row = cur.fetchone()
        cur.close()
        return row[0] if row else 0
    finally:
        put_conn(conn)

@app.get("/metrics", response_class=__import__("fastapi").responses.PlainTextResponse)
def metrics():
    val = _binance_last_5m()
    return f"# HELP algotrading_db_binance_last_5m Binance ticks inserted in last 5 minutes\n# TYPE algotrading_db_binance_last_5m gauge\nalgotrading_db_binance_last_5m {val}\n"

@app.get("/status")
def status():
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {
            "wsclient":         _systemd_status("wsclient.service"),
            "binance_monitor":  _systemd_status("binance_monitor.service"),
        },
        "last_insert": {
            "ticks":         _last_insert("ticks", "time"),
            "orders":        _last_insert("orders", "time"),
            "binance_ticks": _last_insert("binance_ticks", "timestamp"),
            "cookies":       _last_insert("cookies", "time"),
        },
    }
