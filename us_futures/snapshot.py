"""
US Futures / Markets direct fetch via yfinance — no Redis or DB dependency.

Modes
-----
snapshot (default)
    Batch-fetch last_price / last_volume for the futures symbols list.
    Output: JSON array  [{symbol, last_price, last_volume}, ...]

ohlcv --symbol <SYM> [--limit N]
    Daily OHLCV bars for one symbol (default 200 bars).
    Output: JSON array  [{time, symbol, open, high, low, close, volume}, ...]

markets
    Batch-fetch last_price and daily change % for all Markets-tab symbols
    (indices, futures, FX, LatAm).
    Output: JSON array  [{symbol, last_price, change_pct, region, asset_class}, ...]
"""

from __future__ import annotations

import argparse
import json
import sys

import yfinance as yf

from finance.utils.logger import logger

# ── Futures live-feed symbols ──────────────────────────────────────────────────
FUTURES_SYMBOLS = ["ES=F", "NQ=F", "YM=F", "CL=F", "GC=F", "SI=F", "ZB=F"]

# ── All symbols shown in the Markets tab ──────────────────────────────────────
MARKETS_SYMBOLS = [
    # USA
    "^GSPC", "^NDX", "^DJI",
    "ES=F", "NQ=F", "YM=F", "RTY=F",
    "CL=F", "GC=F", "SI=F", "NG=F", "ZB=F", "ZN=F",
    "EURUSD=X", "USDJPY=X", "GBPUSD=X",
    # Europe
    "^STOXX50E", "^FTSE", "^GDAXI",
    "EURGBP=X", "EURJPY=X",
    # Asia
    "^N225", "^HSI", "000001.SS", "USDCNH=X",
    # LatAm
    "^MERV", "ARS=X",
    "^BVSP", "BRL=X",
]


def _asset_class(sym: str) -> str:
    if sym.endswith("=F"):   return "Future"
    if sym.endswith("=X"):   return "FX"
    if sym.startswith("^"):  return "Index"
    return "Equity"


def cmd_snapshot(_args: argparse.Namespace) -> None:
    tickers = yf.Tickers(" ".join(FUTURES_SYMBOLS))
    result: list[dict] = []
    for sym in FUTURES_SYMBOLS:
        try:
            fi = tickers.tickers[sym].fast_info
            result.append({
                "symbol": sym,
                "last_price": float(fi.last_price or 0.0),
                "last_volume": int(fi.last_volume or 0),
            })
        except Exception as exc:
            logger.debug(f"us_futures snapshot {sym}: {exc}")
    json.dump(result, sys.stdout)
    sys.stdout.flush()


def cmd_ohlcv(args: argparse.Namespace) -> None:
    sym: str = args.symbol
    limit: int = args.limit
    try:
        hist = yf.Ticker(sym).history(period="1y", interval="1d")
        if hist.empty:
            print("[]")
            return
        hist = hist.tail(limit)
        bars: list[dict] = []
        for dt, row in hist.iterrows():
            dt_utc = dt.tz_convert("UTC")
            bars.append({
                "time":   dt_utc.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                "symbol": sym,
                "open":   float(row["Open"]),
                "high":   float(row["High"]),
                "low":    float(row["Low"]),
                "close":  float(row["Close"]),
                "volume": int(row["Volume"]),
            })
        json.dump(bars, sys.stdout)
        sys.stdout.flush()
    except Exception as exc:
        logger.error(f"us_futures ohlcv {sym}: {exc}")
        print("[]")


def cmd_markets(_args: argparse.Namespace) -> None:
    tickers = yf.Tickers(" ".join(MARKETS_SYMBOLS))
    result: list[dict] = []
    for sym in MARKETS_SYMBOLS:
        try:
            fi = tickers.tickers[sym].fast_info
            last  = float(fi.last_price or 0.0)
            prev  = float(fi.previous_close or 0.0)
            pct   = (last - prev) / prev * 100.0 if prev else 0.0
            result.append({
                "symbol":      sym,
                "last_price":  last,
                "change_pct":  pct,
                "region":      "",
                "asset_class": _asset_class(sym),
            })
        except Exception as exc:
            logger.debug(f"markets {sym}: {exc}")
    json.dump(result, sys.stdout)
    sys.stdout.flush()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="US Futures / Markets yfinance fetcher")
    sub = p.add_subparsers(dest="mode")
    sub.add_parser("snapshot", help="Live snapshot for futures symbols")
    sub.add_parser("markets",  help="Live snapshot for all Markets-tab symbols")
    ohlcv_p = sub.add_parser("ohlcv", help="Daily OHLCV for one symbol")
    ohlcv_p.add_argument("--symbol", required=True, help="e.g. ES=F")
    ohlcv_p.add_argument("--limit", type=int, default=200, help="Max bars (default 200)")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    if args.mode == "ohlcv":
        cmd_ohlcv(args)
    elif args.mode == "markets":
        cmd_markets(args)
    else:
        cmd_snapshot(args)
