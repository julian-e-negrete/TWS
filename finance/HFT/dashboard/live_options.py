#!/usr/bin/env python3
"""
Live terminal dashboard — GGAL options chain.

Shows: underlying last/bid/ask, then per-expiry option rows with
bid/ask/last/IV/delta/theta/spread, colour-coded by moneyness.

Usage:
    python finance/HFT/dashboard/live_options.py
    python finance/HFT/dashboard/live_options.py --interval 5
"""
import argparse
import curses
import time
from datetime import date, datetime, timezone

import numpy as np
from scipy.optimize import brentq
from scipy.stats import norm
from sqlalchemy import text

from finance.config import settings
from finance.utils.db_pool import get_pg_engine
from ppi_client.ppi import PPI

UNDERLYING   = "GGAL"
OPT_TYPE_MAP = {"ACCIONES": "ACCIONES", "OPCIONES": "OPCIONES"}
SETTLEMENT   = "A-24HS"
RISK_FREE    = 0.40   # ARS reference rate


# ── Black-Scholes helpers ────────────────────────────────────────────────────

def _bs(S, K, T, r, sigma, kind):
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return np.nan
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if kind == "C":
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def _iv(S, K, T, r, mkt, kind):
    try:
        return brentq(lambda s: _bs(S, K, T, r, s, kind) - mkt, 1e-5, 5.0)
    except Exception:
        return np.nan


def _delta(S, K, T, r, sigma, kind):
    if T <= 0 or sigma <= 0:
        return np.nan
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    return norm.cdf(d1) if kind == "C" else norm.cdf(d1) - 1


def _theta(S, K, T, r, sigma, kind):
    if T <= 0 or sigma <= 0:
        return np.nan
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    t1 = -(S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T))
    if kind == "C":
        return (t1 - r * K * np.exp(-r * T) * norm.cdf(d2)) / 365
    return (t1 + r * K * np.exp(-r * T) * norm.cdf(-d2)) / 365


# ── PPI helpers ──────────────────────────────────────────────────────────────

def _login() -> PPI:
    ppi = PPI(sandbox=False)
    ppi.account.login_api(settings.ppi.public_key, settings.ppi.private_key)
    return ppi


def _current(ppi: PPI, ticker: str, kind: str) -> dict:
    try:
        return ppi.marketdata.current(ticker, kind, SETTLEMENT) or {}
    except Exception:
        return {}


def _fetch_chain_tickers(engine) -> list[dict]:
    """Load active option tickers from ppi_options_chain (expiry >= today)."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT ticker, option_type, strike, expiry
            FROM ppi_options_chain
            WHERE underlying = :u AND expiry >= CURRENT_DATE
            ORDER BY expiry, option_type, strike
        """), {"u": UNDERLYING}).mappings().all()
    return [dict(r) for r in rows]


def _fetch_all(ppi: PPI, engine) -> tuple[dict, list[dict]]:
    """Return (underlying_quote, list_of_option_rows)."""
    underlying = _current(ppi, UNDERLYING, "ACCIONES")

    chain = _fetch_chain_tickers(engine)
    S = float(underlying.get("price") or underlying.get("last") or 0)
    today = date.today()
    rows = []
    for opt in chain:
        q = _current(ppi, opt["ticker"], "OPCIONES")
        last  = float(q.get("price") or q.get("last") or 0)
        bid   = float(q.get("bid")   or 0)
        ask   = float(q.get("ask")   or 0)
        vol   = float(q.get("volume") or 0)
        mid   = (bid + ask) / 2 if bid and ask else last

        K = float(opt["strike"] or 0)
        expiry = opt["expiry"]
        T = max((expiry - today).days, 0) / 365.0

        iv  = _iv(S, K, T, RISK_FREE, mid, opt["option_type"]) if mid > 0 and S > 0 else np.nan
        dlt = _delta(S, K, T, RISK_FREE, iv, opt["option_type"]) if not np.isnan(iv) else np.nan
        tht = _theta(S, K, T, RISK_FREE, iv, opt["option_type"]) if not np.isnan(iv) else np.nan

        rows.append({
            "ticker":   opt["ticker"],
            "type":     opt["option_type"],
            "strike":   K,
            "expiry":   expiry,
            "days":     (expiry - today).days,
            "bid":      bid,
            "ask":      ask,
            "last":     last,
            "vol":      vol,
            "spread":   ask - bid if bid and ask else 0,
            "iv":       iv,
            "delta":    dlt,
            "theta":    tht,
            "itm":      (S > K) if opt["option_type"] == "C" else (S < K),
        })
    return underlying, rows


# ── Curses rendering ─────────────────────────────────────────────────────────

COL_FMT = "{:<12} {:>1} {:>8} {:>7} {:>7} {:>7} {:>7} {:>6} {:>6} {:>6} {:>6}"

def _draw(stdscr, underlying: dict, rows: list[dict], last_update: str, interval: int):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    curses.start_color()
    curses.init_pair(1, curses.COLOR_GREEN,  curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_RED,    curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_CYAN,   curses.COLOR_BLACK)
    curses.init_pair(4, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(5, curses.COLOR_WHITE,  curses.COLOR_BLACK)

    S     = float(underlying.get("price") or underlying.get("last") or 0)
    s_bid = float(underlying.get("bid")   or 0)
    s_ask = float(underlying.get("ask")   or 0)
    s_vol = float(underlying.get("volume") or 0)

    hdr = (f" GGAL OPTIONS  |  {UNDERLYING}: last={S:.2f}  bid={s_bid:.2f}  ask={s_ask:.2f}"
           f"  vol={int(s_vol)}  |  {last_update}  |  q=quit")
    stdscr.addstr(0, 0, hdr[:w-1], curses.color_pair(3) | curses.A_BOLD)

    col_hdr = COL_FMT.format("TICKER", "T", "STRIKE", "BID", "ASK", "LAST", "SPREAD", "IV%", "DELTA", "THETA", "VOL")
    stdscr.addstr(2, 0, col_hdr[:w-1], curses.A_UNDERLINE)

    line_n = 3
    current_expiry = None
    for r in rows:
        if line_n >= h - 1:
            break
        if r["expiry"] != current_expiry:
            current_expiry = r["expiry"]
            exp_label = f" ── {current_expiry}  ({r['days']}d) ──"
            stdscr.addstr(line_n, 0, exp_label[:w-1], curses.color_pair(4) | curses.A_BOLD)
            line_n += 1
            if line_n >= h - 1:
                break

        iv_str  = f"{r['iv']*100:.1f}"  if not np.isnan(r["iv"])    else "  -"
        dlt_str = f"{r['delta']:.3f}"   if not np.isnan(r["delta"]) else "  -"
        tht_str = f"{r['theta']:.3f}"   if not np.isnan(r["theta"]) else "  -"

        line = COL_FMT.format(
            r["ticker"][:12],
            r["type"],
            f"{r['strike']:.0f}",
            f"{r['bid']:.2f}"    if r["bid"]  else "-",
            f"{r['ask']:.2f}"    if r["ask"]  else "-",
            f"{r['last']:.2f}"   if r["last"] else "-",
            f"{r['spread']:.2f}" if r["spread"] else "-",
            iv_str, dlt_str, tht_str,
            f"{int(r['vol'])}"   if r["vol"]  else "-",
        )
        color = curses.color_pair(1) if r["itm"] else curses.color_pair(5)
        stdscr.addstr(line_n, 0, line[:w-1], color)
        line_n += 1

    stdscr.addstr(h - 1, 0, f" refresh={interval}s  |  press q to quit"[:w-1], curses.color_pair(4))
    stdscr.refresh()


def _run(stdscr, interval: int):
    curses.curs_set(0)
    stdscr.nodelay(True)
    engine = get_pg_engine()
    ppi    = _login()

    underlying: dict    = {}
    rows:       list    = []
    last_update         = "--"
    next_fetch          = 0.0

    while True:
        key = stdscr.getch()
        if key in (ord("q"), ord("Q"), 27):
            break

        now = time.monotonic()
        if now >= next_fetch:
            try:
                underlying, rows = _fetch_all(ppi, engine)
                last_update = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
            except Exception as e:
                last_update = f"ERR: {e}"
            next_fetch = now + interval

        _draw(stdscr, underlying, rows, last_update, interval)
        time.sleep(0.1)


def main():
    parser = argparse.ArgumentParser(description="Live GGAL options terminal")
    parser.add_argument("--interval", type=int, default=5, help="Refresh interval in seconds (default: 5)")
    args = parser.parse_args()
    curses.wrapper(_run, args.interval)


if __name__ == "__main__":
    main()
