#!/usr/bin/env python3
"""
Live terminal dashboard — polls ticks table every second and renders
bid/ask/last/spread/OFI for active DDF_DLR instruments.

Usage:
    python finance/HFT/dashboard/live_terminal.py
    python finance/HFT/dashboard/live_terminal.py --interval 2
"""
import argparse
import curses
import time
from datetime import datetime, timezone

from sqlalchemy import text

from finance.utils.db_pool import get_pg_engine

QUERY = text("""
    WITH latest AS (
        SELECT DISTINCT ON (instrument)
            instrument, time, bid_price, ask_price, last_price,
            bid_volume, ask_volume, total_volume
        FROM ticks
        WHERE instrument LIKE :pattern
        ORDER BY instrument, time DESC
    ),
    vol_window AS (
        SELECT instrument,
            MAX(total_volume) - MIN(total_volume) AS vol_1m,
            SUM(CASE WHEN bid_price > lag_bid THEN bid_volume ELSE 0 END) AS buy_vol,
            SUM(CASE WHEN ask_price < lag_ask THEN ask_volume ELSE 0 END) AS sell_vol
        FROM (
            SELECT instrument, bid_price, ask_price, bid_volume, ask_volume, total_volume,
                LAG(bid_price) OVER (PARTITION BY instrument ORDER BY time) AS lag_bid,
                LAG(ask_price) OVER (PARTITION BY instrument ORDER BY time) AS lag_ask
            FROM ticks
            WHERE instrument LIKE :pattern
              AND time > NOW() - INTERVAL '1 minute'
        ) sub
        GROUP BY instrument
    )
    SELECT l.instrument,
           l.time AT TIME ZONE 'America/Argentina/Buenos_Aires' AS time_art,
           l.bid_price, l.ask_price, l.last_price,
           l.bid_volume, l.ask_volume,
           COALESCE(v.vol_1m, 0) AS vol_1m,
           COALESCE(v.buy_vol, 0) AS buy_vol,
           COALESCE(v.sell_vol, 0) AS sell_vol
    FROM latest l
    LEFT JOIN vol_window v USING (instrument)
    ORDER BY l.instrument
""")


def fetch(engine, pattern: str) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(QUERY, {"pattern": f"%{pattern}%"}).mappings().all()
    return [dict(r) for r in rows]


def ofi(buy_vol: float, sell_vol: float) -> float:
    total = buy_vol + sell_vol
    return (buy_vol - sell_vol) / total if total > 0 else 0.0


def draw(stdscr, rows: list[dict], interval: int, last_update: str):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    curses.start_color()
    curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_CYAN, curses.COLOR_BLACK)
    curses.init_pair(4, curses.COLOR_YELLOW, curses.COLOR_BLACK)

    header = f" LIVE TICKS — DDF_DLR  |  refresh: {interval}s  |  {last_update}  |  q=quit"
    stdscr.addstr(0, 0, header[:w-1], curses.color_pair(3) | curses.A_BOLD)

    col_fmt = "{:<36} {:>10} {:>10} {:>10} {:>8} {:>8} {:>8} {:>7} {:>6}"
    hdr = col_fmt.format("INSTRUMENT", "BID", "ASK", "LAST", "SPREAD", "VOL_1M", "BUY_V", "SELL_V", "OFI")
    stdscr.addstr(2, 0, hdr[:w-1], curses.A_UNDERLINE)

    for i, r in enumerate(rows):
        if 3 + i >= h - 1:
            break
        spread = (r["ask_price"] or 0) - (r["bid_price"] or 0)
        o = ofi(float(r["buy_vol"]), float(r["sell_vol"]))
        ofi_color = curses.color_pair(1) if o > 0 else curses.color_pair(2)
        t_art = r["time_art"].strftime("%H:%M:%S") if r["time_art"] else "--"
        line = col_fmt.format(
            f"{r['instrument'][:35]}",
            f"{r['bid_price']:.2f}" if r["bid_price"] else "-",
            f"{r['ask_price']:.2f}" if r["ask_price"] else "-",
            f"{r['last_price']:.2f}" if r["last_price"] else "-",
            f"{spread:.2f}",
            f"{int(r['vol_1m'])}",
            f"{int(r['buy_vol'])}",
            f"{int(r['sell_vol'])}",
            f"{o:+.2f}",
        )
        stdscr.addstr(3 + i, 0, line[:w-1])
        # colour OFI column
        ofi_str = f"{o:+.2f}"
        ofi_col = w - 7
        if ofi_col > 0:
            stdscr.addstr(3 + i, min(ofi_col, w - len(ofi_str) - 1), ofi_str, ofi_color)

    stdscr.addstr(h - 1, 0, " press q to quit"[:w-1], curses.color_pair(4))
    stdscr.refresh()


def run(stdscr, interval: int, pattern: str):
    curses.curs_set(0)
    stdscr.nodelay(True)
    engine = get_pg_engine()

    rows: list[dict] = []
    last_update = "--"
    next_fetch = 0.0

    while True:
        key = stdscr.getch()
        if key in (ord("q"), ord("Q"), 27):
            break

        now = time.monotonic()
        if now >= next_fetch:
            try:
                rows = fetch(engine, pattern)
                last_update = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
            except Exception as e:
                last_update = f"ERR: {e}"
            next_fetch = now + interval

        draw(stdscr, rows, interval, last_update)
        time.sleep(0.1)


def main():
    parser = argparse.ArgumentParser(description="Live terminal ticker dashboard")
    parser.add_argument("--interval", type=int, default=1, help="Refresh interval in seconds (default: 1)")
    parser.add_argument("--pattern", default="DDF_DLR", help="Instrument filter pattern (default: DDF_DLR)")
    args = parser.parse_args()
    curses.wrapper(run, args.interval, args.pattern)


if __name__ == "__main__":
    main()
