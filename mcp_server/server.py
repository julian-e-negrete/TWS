"""
TWS MCP Server
==============
Exposes all project data sources and analytics as MCP tools so that
AI agents (Claude Code, Kiro, etc.) never need to re-read source files
to understand the schema or perform common queries.

DATA CONTRACTS (from DATA_SPEC.md):
  - All DB timestamps are UTC.  Use AT TIME ZONE 'America/Argentina/Buenos_Aires' for ART display.
  - `ticks` and `orders` are TimescaleDB hypertables — prefer time_bucket() for aggregations.
  - `total_volume` in `ticks` is cumulative daily, NOT incremental per tick.
    Volume per period = MAX(total_volume) - MIN(total_volume).
  - Instrument names in `ticks` carry an "M:" prefix (e.g. "M:bm_MERV_GGAL_24hs").
    The same instruments in `orders` have the prefix stripped (e.g. "bm_MERV_GGAL_24hs").
  - Active DLR futures contract changes monthly — always query dynamically.
  - No market data on weekends or Argentine holidays.

SECTIONS:
  1.  Schema / project context
  2.  Ticks  (BYMA real-time quotes)
  3.  Orders (BYMA executed trades)
  4.  Options chain
  5.  Futures / DLR
  6.  CCL (Contado con Liquidación)
  7.  Binance
  8.  US Futures & Global Markets
  9.  Solana DEX
  10. PPI (Portfolio Personal Inversiones)
  11. Backtest & ML results
  12. Math / analytics (Black-Scholes, Greeks, IV, DLR fair value)
  13. Redis live prices
  14. Write tools
"""

import os
import sys
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import importlib.util

import numpy as np
import psycopg2.extras
from mcp.server.fastmcp import FastMCP
from sqlalchemy import text

from data.cache import cache_get, cache_set, TTL_MARKET, TTL_HISTORICAL
from shared.db_pool import get_pg_engine, get_mysql_engine

# Load local math package by file path to avoid conflict with Python's
# built-in `math` C module (which is checked before sys.path entries).
# We register it under the alias `tws_math` in sys.modules so relative
# imports inside the sub-modules (e.g. `from .options import ...`) resolve.
_TWS_ROOT = os.path.dirname(os.path.dirname(__file__))
_math_pkg_dir = os.path.join(_TWS_ROOT, "math")

def _load_tws_math_pkg():
    pkg_spec = importlib.util.spec_from_file_location(
        "tws_math",
        os.path.join(_math_pkg_dir, "__init__.py"),
        submodule_search_locations=[_math_pkg_dir],
    )
    pkg = importlib.util.module_from_spec(pkg_spec)
    sys.modules["tws_math"] = pkg
    pkg_spec.loader.exec_module(pkg)

    for sub in ("options", "greeks", "dlr"):
        spec = importlib.util.spec_from_file_location(
            f"tws_math.{sub}",
            os.path.join(_math_pkg_dir, f"{sub}.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"tws_math.{sub}"] = mod
        spec.loader.exec_module(mod)
        setattr(pkg, sub, mod)

    return pkg

_tws_math = _load_tws_math_pkg()

black_scholes           = _tws_math.options.black_scholes
implied_volatility      = _tws_math.options.implied_volatility
greeks_scipy            = _tws_math.greeks.greeks_scipy
calculate_ccl           = _tws_math.dlr.calculate_ccl
estimate_dlr_fair_value = _tws_math.dlr.estimate_dlr_fair_value

logger = logging.getLogger(__name__)
mcp = FastMCP("tws-algotrading")

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _pg(sql: str, params=None) -> list[dict]:
    with get_pg_engine().connect() as conn:
        result = conn.execute(text(sql), params or {})
        rows = [dict(r._mapping) for r in result.fetchall()]
    # Convert Decimal → float for JSON serialisability
    for row in rows:
        for k, v in row.items():
            try:
                from decimal import Decimal
                if isinstance(v, Decimal):
                    row[k] = float(v)
            except Exception:
                pass
    return rows


def _pg_write(sql: str, params=None) -> int:
    with get_pg_engine().begin() as conn:
        result = conn.execute(text(sql), params or {})
        return result.rowcount


def _mysql(sql: str, params=None) -> list[dict]:
    with get_mysql_engine().connect() as conn:
        result = conn.execute(text(sql), params or {})
        return [dict(r._mapping) for r in result.fetchall()]


# ---------------------------------------------------------------------------
# 1. Schema / project context
# ---------------------------------------------------------------------------

@mcp.tool()
def get_project_schema() -> dict:
    """
    Returns the schema of every table in the PostgreSQL marketdata database,
    including which are TimescaleDB hypertables, their size, and row count estimates.

    Use this at the start of any session instead of reading source files.
    """
    tables = _pg("""
        SELECT
            c.relname                                                      AS table_name,
            pg_size_pretty(pg_total_relation_size(c.oid))                  AS total_size,
            c.reltuples::bigint                                             AS row_estimate,
            CASE WHEN h.hypertable_name IS NOT NULL THEN true ELSE false END AS is_hypertable
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN timescaledb_information.hypertables h ON h.hypertable_name = c.relname
        WHERE n.nspname = 'public' AND c.relkind = 'r'
        ORDER BY pg_total_relation_size(c.oid) DESC
    """)

    columns = _pg("""
        SELECT table_name, column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
    """)

    schema: dict[str, dict] = {}
    for t in tables:
        schema[t["table_name"]] = {
            "total_size": t["total_size"],
            "row_estimate": t["row_estimate"],
            "is_hypertable": t["is_hypertable"],
            "columns": [],
        }
    for col in columns:
        tname = col["table_name"]
        if tname in schema:
            schema[tname]["columns"].append({
                "name": col["column_name"],
                "type": col["data_type"],
                "nullable": col["is_nullable"] == "YES",
            })

    return schema


@mcp.tool()
def get_instrument_conventions() -> dict:
    """
    Returns naming conventions and key facts about instruments in this project.
    Use this to understand how to query for specific assets.
    """
    return {
        "ticks_prefix": "Instruments in `ticks` start with 'M:' e.g. 'M:bm_MERV_GGAL_24hs'",
        "orders_no_prefix": "The same instrument in `orders` has the 'M:' stripped: 'bm_MERV_GGAL_24hs'",
        "options_pattern": "GGAL calls: GFGC*, puts: GFGV*  e.g. 'M:bm_MERV_GFGC69029A_24hs'",
        "bonds_pattern": "AL30, GD30, AE38, AL35, GD35 — appear as e.g. 'M:bm_MERV_AL30_24hs'",
        "dlr_pattern": "DLR futures: 'M:rx_DDF_DLR_<MON><YY>' e.g. 'M:rx_DDF_DLR_ABR26'",
        "ccl_instruments": {
            "al30_ars": "M:bm_MERV_AL30_24hs",
            "al30_usd": "M:bm_MERV_AL30D_24hs",
        },
        "binance_symbols": ["BTCUSDT", "BTCARS", "ETHUSDT", "ETHARS", "ETHUSDC",
                            "SOLUSDT", "USDTARS", "USDCUSDT", "BNBUSDT"],
        "us_futures_symbols": ["ES=F", "NQ=F", "YM=F", "CL=F", "GC=F", "SI=F", "ZB=F"],
        "us_indices": ["^GSPC", "^NDX", "^DJI", "^FTSE", "^GDAXI", "^BVSP", "^MERV",
                       "^HSI", "^N225", "^STOXX50E", "000001.SS"],
        "fx_pairs": ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "USDCNH=X", "EURJPY=X",
                     "EURGBP=X", "ARS=X", "BRL=X"],
        "volume_note": "total_volume in ticks is CUMULATIVE daily. Volume per period = MAX - MIN.",
        "timezone": "All DB timestamps are UTC. Argentine market hours 11:00-17:00 ART (UTC-3).",
    }


# ---------------------------------------------------------------------------
# 2. Ticks — BYMA real-time quotes
# ---------------------------------------------------------------------------

@mcp.tool()
def get_ticks(instrument: str, limit: int = 100) -> list[dict]:
    """
    Latest ticks for a BYMA instrument from the `ticks` hypertable.

    Args:
        instrument: full name including 'M:' prefix, e.g. 'M:bm_MERV_GGAL_24hs'
        limit: rows to return (default 100, max 1000)
    """
    limit = min(limit, 1000)
    key = f"ticks:{instrument}:{limit}"
    cached = cache_get(key)
    if cached is not None:
        return cached
    result = _pg(
        """
        SELECT time, instrument, bid_price, ask_price, last_price,
               total_volume, high, low, prev_close
        FROM ticks
        WHERE instrument = :instrument
        ORDER BY time DESC LIMIT :limit
        """,
        {"instrument": instrument, "limit": limit},
    )
    cache_set(key, result, TTL_MARKET)
    return result


@mcp.tool()
def get_ohlcv(instrument: str, bucket: str = "1 minute", hours_back: int = 24) -> list[dict]:
    """
    OHLCV candles from `ticks` using TimescaleDB time_bucket().

    Volume = MAX(total_volume) - MIN(total_volume) per bucket
    because total_volume is cumulative daily.

    Args:
        instrument: e.g. 'M:bm_MERV_AL30_24hs'
        bucket: '1 minute', '5 minutes', '15 minutes', '1 hour', '1 day'
        hours_back: history window in hours (default 24)
    """
    key = f"ohlcv:{instrument}:{bucket}:{hours_back}"
    cached = cache_get(key)
    if cached is not None:
        return cached
    result = _pg(
        """
        SELECT
            time_bucket(:bucket, time) AS bucket,
            instrument,
            FIRST(last_price, time)               AS open,
            MAX(high)                             AS high,
            MIN(low)                              AS low,
            LAST(last_price, time)                AS close,
            MAX(total_volume) - MIN(total_volume) AS volume
        FROM ticks
        WHERE instrument = :instrument
          AND time > NOW() - (:hours || ' hours')::INTERVAL
        GROUP BY 1, instrument
        ORDER BY 1 DESC
        """,
        {"bucket": bucket, "instrument": instrument, "hours": str(hours_back)},
    )
    cache_set(key, result, TTL_HISTORICAL)
    return result


@mcp.tool()
def get_active_instruments(days_back: int = 3, filter_pattern: str = "") -> list[dict]:
    """
    Instruments with ticks in the last N days.
    Use this to find the current active DLR futures contract (changes monthly).

    Args:
        days_back: look-back window in days (default 3)
        filter_pattern: optional SQL LIKE pattern, e.g. '%DDF_DLR%'
    """
    if filter_pattern:
        return _pg(
            """
            SELECT DISTINCT instrument
            FROM ticks
            WHERE time > NOW() - (:days || ' days')::INTERVAL
              AND instrument LIKE :pat
            ORDER BY instrument
            """,
            {"days": str(days_back), "pat": filter_pattern},
        )
    return _pg(
        """
        SELECT DISTINCT instrument
        FROM ticks
        WHERE time > NOW() - (:days || ' days')::INTERVAL
        ORDER BY instrument
        """,
        {"days": str(days_back)},
    )


@mcp.tool()
def get_spread(instrument: str, bucket: str = "1 hour", days_back: int = 7) -> list[dict]:
    """
    Average bid-ask spread per time bucket for an instrument.

    Args:
        instrument: e.g. 'M:bm_MERV_AL30_24hs'
        bucket: e.g. '1 hour', '15 minutes'
        days_back: history in days (default 7)
    """
    return _pg(
        """
        SELECT
            time_bucket(:bucket, time) AS bucket,
            AVG(ask_price - bid_price) AS spread_avg,
            MIN(ask_price - bid_price) AS spread_min,
            MAX(ask_price - bid_price) AS spread_max
        FROM ticks
        WHERE instrument = :instrument
          AND time > NOW() - (:days || ' days')::INTERVAL
        GROUP BY 1
        ORDER BY 1 DESC
        """,
        {"bucket": bucket, "instrument": instrument, "days": str(days_back)},
    )


# ---------------------------------------------------------------------------
# 3. Orders — BYMA executed trades
# ---------------------------------------------------------------------------

@mcp.tool()
def get_orders(hours_back: int = 2, instrument: str = "") -> list[dict]:
    """
    Executed orders from the `orders` hypertable.
    NOTE: instrument names here have NO 'M:' prefix.
    side: 'B' = buy, 'S' = sell. Timestamps in UTC.

    Args:
        hours_back: history window in hours (default 2)
        instrument: optional filter e.g. 'bm_MERV_GGAL_24hs' (no M: prefix)
    """
    if instrument:
        return _pg(
            """
            SELECT time, instrument, price, volume, side
            FROM orders
            WHERE time > NOW() - (:hours || ' hours')::INTERVAL
              AND instrument = :instrument
            ORDER BY time DESC LIMIT 1000
            """,
            {"hours": str(hours_back), "instrument": instrument},
        )
    return _pg(
        """
        SELECT time, instrument, price, volume, side
        FROM orders
        WHERE time > NOW() - (:hours || ' hours')::INTERVAL
        ORDER BY time DESC LIMIT 1000
        """,
        {"hours": str(hours_back)},
    )


@mcp.tool()
def get_order_flow(days_back: int = 1, instrument_pattern: str = "") -> list[dict]:
    """
    Buy vs sell volume per instrument (order flow imbalance).

    Args:
        days_back: history in days (default 1)
        instrument_pattern: optional SQL LIKE filter e.g. '%GGAL%'
    """
    base = """
        SELECT
            instrument,
            SUM(CASE WHEN side = 'B' THEN volume ELSE 0 END) AS vol_buy,
            SUM(CASE WHEN side = 'S' THEN volume ELSE 0 END) AS vol_sell,
            COUNT(*) AS num_trades
        FROM orders
        WHERE time > NOW() - (:days || ' days')::INTERVAL
    """
    if instrument_pattern:
        base += " AND instrument LIKE :pat"
    base += " GROUP BY instrument ORDER BY num_trades DESC"
    params: dict = {"days": str(days_back)}
    if instrument_pattern:
        params["pat"] = instrument_pattern
    return _pg(base, params)


# ---------------------------------------------------------------------------
# 4. Options chain
# ---------------------------------------------------------------------------

@mcp.tool()
def get_options_chain(underlying: str = "GGAL", days_back: int = 7) -> list[dict]:
    """
    Live options chain for an underlying with Black-Scholes IV and Greeks.

    Fetches best bid/ask from `ticks` and last trade from `orders`.
    Greeks computed via scipy finite-difference BS.

    Args:
        underlying: equity ticker, e.g. 'GGAL', 'SUPV', 'PBRD'
        days_back: look-back window for option data (default 7)
    """
    # Underlying spot price from orders (last trade)
    spot_rows = _pg(
        """
        SELECT price FROM orders
        WHERE instrument LIKE :pat
          AND time > NOW() - INTERVAL '3 days'
        ORDER BY time DESC LIMIT 1
        """,
        {"pat": f"%{underlying}%", }
    )
    spot_rows = [r for r in spot_rows if not any(x in r.get("instrument", "") for x in ["GFG"])] if spot_rows else []

    # Try ticks as fallback
    spot_tick = _pg(
        """
        SELECT last_price FROM ticks
        WHERE instrument = :instr
        ORDER BY time DESC LIMIT 1
        """,
        {"instr": f"M:bm_MERV_{underlying}_24hs"},
    )
    spot = float(spot_tick[0]["last_price"]) if spot_tick else 0.0

    # Option ticks — calls (GFGC) and puts (GFGV)
    call_prefix = f"%GFGC%"
    put_prefix = f"%GFGV%"

    tick_rows = _pg(
        """
        SELECT instrument,
               MAX(bid_price)::float8              AS bid,
               MIN(NULLIF(ask_price, 0))::float8   AS ask
        FROM ticks
        WHERE (instrument LIKE :calls OR instrument LIKE :puts)
          AND time > NOW() - (:days || ' days')::INTERVAL
          AND bid_price > 0 AND ask_price > 0
        GROUP BY instrument
        """,
        {"calls": call_prefix, "puts": put_prefix, "days": str(days_back)},
    )

    order_rows = _pg(
        """
        SELECT DISTINCT ON (instrument) instrument, price::float8
        FROM orders
        WHERE (instrument LIKE :calls OR instrument LIKE :puts)
          AND time > NOW() - (:days || ' days')::INTERVAL
        ORDER BY instrument, time DESC
        """,
        {"calls": call_prefix.replace("M:bm_MERV_", "bm_MERV_"),
         "puts": put_prefix.replace("M:bm_MERV_", "bm_MERV_"),
         "days": str(days_back)},
    )
    last_map = {r["instrument"]: r["price"] for r in order_rows}

    r_f = 0.05  # approximate Argentine risk-free rate
    results = []
    from datetime import date as dt_date

    for row in tick_rows:
        instr: str = row["instrument"]
        bid = row["bid"] or 0.0
        ask = row["ask"] or 0.0
        if bid <= 0.0 or ask <= 0.0:
            continue

        order_key = instr.replace("M:bm_MERV_", "bm_MERV_").replace("M:rx_", "")
        last = last_map.get(order_key, (bid + ask) / 2)
        mid = (bid + ask) / 2

        opt_type = "C" if "GFGC" in instr else "P"

        # Parse strike and expiry from instrument name
        # e.g. GFGC69029A → strike 69029 or 690.29 depending on convention
        import re
        m = re.search(r"GFG[CV](\d+)([A-Z]+\d*)", instr)
        strike = float(m.group(1)) if m else 0.0
        expiry_days = 30.0  # fallback

        # Try to parse expiry month from suffix like ABR26, JUN26, etc.
        month_map = {"ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
                     "JUL": 7, "AGO": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DIC": 12}
        for mname, mnum in month_map.items():
            if mname in instr.upper():
                yr_m = re.search(rf"{mname}(\d{{2}})", instr.upper())
                if yr_m:
                    year = 2000 + int(yr_m.group(1))
                    from datetime import date as dt
                    import calendar
                    last_day = calendar.monthrange(year, mnum)[1]
                    exp_date = dt(year, mnum, last_day)
                    expiry_days = max((exp_date - dt.today()).days, 1)
                break

        T = expiry_days / 365.0

        iv = float("nan")
        greeks: dict = {}
        if spot > 0 and strike > 0 and last > 0:
            try:
                iv = implied_volatility(spot, strike, T, r_f, last, opt_type)
                if not np.isnan(iv):
                    delta, gamma, vega, theta, rho = greeks_scipy(spot, strike, T, r_f, iv, opt_type)
                    greeks = {"delta": round(delta, 4), "gamma": round(gamma, 6),
                              "vega": round(vega, 4), "theta": round(theta, 4),
                              "rho": round(rho, 4)}
            except Exception:
                pass

        short = re.sub(r"M:bm_MERV_|_24hs|_48hs", "", instr)
        results.append({
            "instrument": instr,
            "short": short,
            "type": opt_type,
            "strike": strike,
            "expiry_days": int(expiry_days),
            "last": round(last, 2),
            "bid": round(bid, 2),
            "ask": round(ask, 2),
            "iv": round(iv, 4) if not np.isnan(iv) else None,
            **greeks,
        })

    results.sort(key=lambda x: (x["type"], x["strike"]))
    return {"spot": round(spot, 2), "options": results}


@mcp.tool()
def get_active_options_instruments(underlying: str = "GGAL", days_back: int = 7) -> list[str]:
    """
    List of option instrument names active in the last N days for an underlying.

    Args:
        underlying: e.g. 'GGAL'
        days_back: look-back window (default 7)
    """
    rows = _pg(
        """
        SELECT DISTINCT instrument FROM ticks
        WHERE (instrument LIKE :calls OR instrument LIKE :puts)
          AND time > NOW() - (:days || ' days')::INTERVAL
        ORDER BY instrument
        """,
        {"calls": f"%GFG%C%", "puts": f"%GFG%V%", "days": str(days_back)},
    )
    return [r["instrument"] for r in rows]


# ---------------------------------------------------------------------------
# 5. Futures / DLR
# ---------------------------------------------------------------------------

@mcp.tool()
def get_futures_curve(days_back: int = 30) -> list[dict]:
    """
    DLR futures term structure — current active contracts sorted near to far.

    Returns last price, bid, ask for each contract.
    NOTE: active contract names change monthly; always use this tool, never hardcode.

    Args:
        days_back: look-back for 'active' definition (default 30)
    """
    rows = _pg(
        """
        SELECT DISTINCT ON (instrument) instrument,
               last_price::float8, bid_price::float8, ask_price::float8
        FROM ticks
        WHERE instrument LIKE 'M:%DDF_DLR%'
          AND instrument NOT LIKE '%A'
          AND time > NOW() - (:days || ' days')::INTERVAL
        ORDER BY instrument, time DESC
        """,
        {"days": str(days_back)},
    )

    month_map = {"ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
                 "JUL": 7, "AGO": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DIC": 12}

    def sort_key(r):
        import re
        name = r["instrument"].upper()
        for m, n in month_map.items():
            if m in name:
                yr = re.search(rf"{m}(\d{{2}})", name)
                year = int(yr.group(1)) if yr else 99
                return year * 100 + n
        return 9999

    rows.sort(key=sort_key)
    return rows


@mcp.tool()
def get_futures_ticks(instrument: str, limit: int = 200) -> list[dict]:
    """
    Tick-by-tick data for a specific DLR futures contract.

    Args:
        instrument: e.g. 'M:rx_DDF_DLR_ABR26'
        limit: rows (default 200)
    """
    return _pg(
        """
        SELECT time, instrument, bid_price, ask_price, last_price, total_volume
        FROM ticks WHERE instrument = :instrument
        ORDER BY time DESC LIMIT :limit
        """,
        {"instrument": instrument, "limit": limit},
    )


# ---------------------------------------------------------------------------
# 6. CCL (Contado con Liquidación)
# ---------------------------------------------------------------------------

@mcp.tool()
def get_ccl_rate() -> dict:
    """
    Current CCL (Contado con Liquidación) implied exchange rate.
    Calculated as AL30_ARS / AL30D_USD (mid, bid, ask).

    Returns spot prices for AL30 and AL30D plus derived CCL rates.
    """
    rows = _pg(
        """
        SELECT DISTINCT ON (instrument) instrument,
               bid_price::float8, ask_price::float8, last_price::float8
        FROM ticks
        WHERE instrument IN ('M:bm_MERV_AL30_24hs', 'M:bm_MERV_AL30D_24hs')
          AND time > NOW() - INTERVAL '3 days'
        ORDER BY instrument, time DESC
        """
    )
    data = {r["instrument"]: r for r in rows}
    al30  = data.get("M:bm_MERV_AL30_24hs",  {})
    al30d = data.get("M:bm_MERV_AL30D_24hs", {})

    if al30 and al30d:
        ccl_mid, ccl_bid, ccl_ask = calculate_ccl(
            al30["bid_price"], al30["ask_price"],
            al30d["bid_price"], al30d["ask_price"],
        )
        return {
            "al30_bid": al30["bid_price"], "al30_ask": al30["ask_price"],
            "al30d_bid": al30d["bid_price"], "al30d_ask": al30d["ask_price"],
            "ccl_mid": round(ccl_mid, 2),
            "ccl_bid": round(ccl_bid, 2),
            "ccl_ask": round(ccl_ask, 2),
        }
    return {"error": "AL30 or AL30D data not available", "raw": data}


# ---------------------------------------------------------------------------
# 7. Binance
# ---------------------------------------------------------------------------

@mcp.tool()
def get_binance_ticks(symbol: str, limit: int = 60) -> list[dict]:
    """
    Latest 1-minute OHLCV candles from Binance.

    Available symbols: BTCUSDT, BTCARS, ETHUSDT, ETHARS, ETHUSDC,
                       SOLUSDT, USDTARS, USDCUSDT, BNBUSDT

    Args:
        symbol: e.g. 'USDTARS', 'BTCUSDT'
        limit: number of candles (default 60, max 1440)
    """
    limit = min(limit, 1440)
    return _pg(
        """
        SELECT timestamp, open, high, low, close, volume
        FROM binance_ticks
        WHERE symbol = :symbol
        ORDER BY timestamp DESC LIMIT :limit
        """,
        {"symbol": symbol, "limit": limit},
    )


@mcp.tool()
def get_binance_latest() -> list[dict]:
    """
    Latest close price for every active Binance symbol.
    Use this to get a quick market snapshot without specifying a symbol.
    """
    return _pg(
        """
        SELECT DISTINCT ON (symbol) symbol, close::float8 AS price, timestamp
        FROM binance_ticks
        ORDER BY symbol, timestamp DESC
        """
    )


@mcp.tool()
def get_binance_trades(symbol: str, limit: int = 100) -> list[dict]:
    """
    Individual Binance trades (tick-by-tick, not OHLCV).
    This is a 2.4 GB table — always specify a small limit for quick queries.

    Args:
        symbol: e.g. 'BTCUSDT', 'SOLUSDT'
        limit: rows to return (default 100, max 500)
    """
    limit = min(limit, 500)
    return _pg(
        """
        SELECT time, symbol, price, qty, is_buyer_maker, trade_id
        FROM binance_trades
        WHERE symbol = :symbol
        ORDER BY time DESC LIMIT :limit
        """,
        {"symbol": symbol, "limit": limit},
    )


@mcp.tool()
def get_binance_ohlcv(symbol: str, bucket: str = "1 hour", days_back: int = 7) -> list[dict]:
    """
    OHLCV aggregation for a Binance symbol using time_bucket().

    Args:
        symbol: e.g. 'BTCUSDT'
        bucket: '1 minute', '5 minutes', '1 hour', '1 day'
        days_back: look-back in days (default 7)
    """
    return _pg(
        """
        SELECT
            time_bucket(:bucket, timestamp) AS bucket,
            symbol,
            FIRST(open, timestamp)   AS open,
            MAX(high)                AS high,
            MIN(low)                 AS low,
            LAST(close, timestamp)   AS close,
            SUM(volume)              AS volume
        FROM binance_ticks
        WHERE symbol = :symbol
          AND timestamp > NOW() - (:days || ' days')::INTERVAL
        GROUP BY 1, symbol
        ORDER BY 1 DESC
        """,
        {"bucket": bucket, "symbol": symbol, "days": str(days_back)},
    )


# ---------------------------------------------------------------------------
# 8. US Futures & Global Markets
# ---------------------------------------------------------------------------

@mcp.tool()
def get_us_futures_live() -> list[dict]:
    """
    Latest price for all US futures, indices, and FX pairs.

    Asset classes: futures (ES=F, NQ=F, YM=F, CL=F, GC=F, SI=F, ZB=F),
                   indices (^GSPC, ^NDX, ^DJI, ^FTSE, ^BVSP, ^MERV, ^HSI, etc.),
                   fx (EURUSD=X, USDJPY=X, ARS=X, BRL=X, etc.)
    """
    return _pg(
        """
        SELECT DISTINCT ON (symbol) symbol, last_price::float8 AS price,
               region, asset_class, time
        FROM us_futures_ticks
        WHERE region IS NOT NULL
        ORDER BY symbol, time DESC
        """
    )


@mcp.tool()
def get_us_futures_ohlcv(symbol: str, limit: int = 30) -> list[dict]:
    """
    Daily OHLCV bars for a US futures / index / FX symbol.

    Args:
        symbol: e.g. 'ES=F', '^GSPC', 'EURUSD=X'
        limit: bars to return (default 30)
    """
    return _pg(
        """
        SELECT time, symbol, open, high, low, close, volume, region, asset_class
        FROM us_futures_ohlcv
        WHERE symbol = :symbol
        ORDER BY time DESC LIMIT :limit
        """,
        {"symbol": symbol, "limit": limit},
    )


# ---------------------------------------------------------------------------
# 9. Solana DEX
# ---------------------------------------------------------------------------

@mcp.tool()
def get_solana_trades(symbol: str = "SOL/USDC", limit: int = 100) -> list[dict]:
    """
    Recent Solana DEX trades from Orca, Raydium, and Meteora.

    Args:
        symbol: 'SOL/USDC' or 'SOL/USDT'
        limit: rows (default 100, max 500)
    """
    limit = min(limit, 500)
    return _pg(
        """
        SELECT time, symbol, price, qty, source_dex, is_buyer_maker, pair_address
        FROM solana_dex_trades
        WHERE symbol = :symbol
        ORDER BY time DESC LIMIT :limit
        """,
        {"symbol": symbol, "limit": limit},
    )


@mcp.tool()
def get_solana_ohlcv(symbol: str = "SOL/USDC", bucket: str = "1 hour",
                     days_back: int = 3) -> list[dict]:
    """
    OHLCV from Solana DEX trades using time_bucket().

    Args:
        symbol: 'SOL/USDC' or 'SOL/USDT'
        bucket: e.g. '5 minutes', '1 hour'
        days_back: look-back in days (default 3)
    """
    return _pg(
        """
        SELECT
            time_bucket(:bucket, time) AS bucket,
            symbol,
            FIRST(price, time)   AS open,
            MAX(price)           AS high,
            MIN(price)           AS low,
            LAST(price, time)    AS close,
            SUM(qty)             AS volume
        FROM solana_dex_trades
        WHERE symbol = :symbol
          AND time > NOW() - (:days || ' days')::INTERVAL
        GROUP BY 1, symbol
        ORDER BY 1 DESC
        """,
        {"bucket": bucket, "symbol": symbol, "days": str(days_back)},
    )


# ---------------------------------------------------------------------------
# 10. PPI (Portfolio Personal Inversiones) historical data
# ---------------------------------------------------------------------------

@mcp.tool()
def get_ppi_ohlcv(ticker: str = "GGAL", limit: int = 60) -> list[dict]:
    """
    Daily OHLCV from PPI for Argentine equities.

    Args:
        ticker: e.g. 'GGAL'
        limit: trading days to return (default 60)
    """
    return _pg(
        """
        SELECT date, ticker, type, open, high, low, close, volume
        FROM ppi_ohlcv
        WHERE ticker = :ticker
        ORDER BY date DESC LIMIT :limit
        """,
        {"ticker": ticker, "limit": limit},
    )


@mcp.tool()
def get_ppi_options_chain(underlying: str = "GGAL", as_of_date: str = "") -> list[dict]:
    """
    Historical daily OHLCV for PPI options chain.

    Args:
        underlying: e.g. 'GGAL'
        as_of_date: 'YYYY-MM-DD' — if omitted uses the latest available date
    """
    if as_of_date:
        return _pg(
            """
            SELECT ticker, option_type, strike, expiry, date,
                   open, high, low, close, volume
            FROM ppi_options_chain
            WHERE underlying = :underlying AND date = :date
            ORDER BY option_type, strike, expiry
            """,
            {"underlying": underlying, "date": as_of_date},
        )
    return _pg(
        """
        SELECT ticker, option_type, strike, expiry, date,
               open, high, low, close, volume
        FROM ppi_options_chain
        WHERE underlying = :underlying
          AND date = (SELECT MAX(date) FROM ppi_options_chain WHERE underlying = :underlying)
        ORDER BY option_type, strike, expiry
        """,
        {"underlying": underlying},
    )


# ---------------------------------------------------------------------------
# 11. Backtest & ML results
# ---------------------------------------------------------------------------

@mcp.tool()
def get_backtest_results(instrument: str = "", strategy: str = "",
                         limit: int = 50) -> list[dict]:
    """
    Query bt_strategy_runs for backtest performance metrics.

    Args:
        instrument: filter by instrument, e.g. 'GGAL', 'AL30', 'BTCUSDT_MARGIN_5X'
        strategy: filter by strategy name, e.g. 'macd', 'rsi_reversion', 'bollinger'
        limit: rows (default 50)
    """
    filters = []
    params: dict = {"limit": limit}
    if instrument:
        filters.append("instrument LIKE :instrument")
        params["instrument"] = f"%{instrument}%"
    if strategy:
        filters.append("strategy LIKE :strategy")
        params["strategy"] = f"%{strategy}%"

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    return _pg(
        f"""
        SELECT id, run_at, instrument, strategy, date,
               total_return, sharpe, max_drawdown, win_rate,
               num_trades, profit_factor, expectancy, metadata
        FROM bt_strategy_runs
        {where}
        ORDER BY run_at DESC LIMIT :limit
        """,
        params,
    )


@mcp.tool()
def get_best_strategies(instrument: str, top_n: int = 10) -> list[dict]:
    """
    Rank strategies by Sharpe ratio for a given instrument.

    Args:
        instrument: exact name e.g. 'GGAL' or 'AL30'
        top_n: number of results (default 10)
    """
    return _pg(
        """
        SELECT strategy, instrument,
               AVG(sharpe)        AS avg_sharpe,
               AVG(total_return)  AS avg_return,
               AVG(max_drawdown)  AS avg_drawdown,
               AVG(win_rate)      AS avg_win_rate,
               COUNT(*)           AS run_count
        FROM bt_strategy_runs
        WHERE instrument = :instrument AND sharpe > 0
        GROUP BY strategy, instrument
        ORDER BY avg_sharpe DESC
        LIMIT :top_n
        """,
        {"instrument": instrument, "top_n": top_n},
    )


@mcp.tool()
def get_ml_episodes(instrument: str = "GGAL_OPTIONS", limit: int = 100) -> list[dict]:
    """
    Training episode history from ml_training_episodes.

    Args:
        instrument: e.g. 'GGAL_OPTIONS'
        limit: episodes to return (default 100)
    """
    return _pg(
        """
        SELECT ts, instrument, run_date, stage, episode,
               reward, steps, loss, accuracy, regimes_covered
        FROM ml_training_episodes
        WHERE instrument = :instrument
        ORDER BY ts DESC LIMIT :limit
        """,
        {"instrument": instrument, "limit": limit},
    )


@mcp.tool()
def get_signal_stats(run_id: int = 0) -> list[dict]:
    """
    Signal filter statistics for a backtest run.

    Args:
        run_id: if 0, returns stats for all runs
    """
    if run_id:
        return _pg(
            "SELECT * FROM signal_stats WHERE run_id = :run_id ORDER BY signal_count DESC",
            {"run_id": run_id},
        )
    return _pg("SELECT * FROM signal_stats ORDER BY run_id DESC, signal_count DESC")


# ---------------------------------------------------------------------------
# 12. Math / analytics
# ---------------------------------------------------------------------------

@mcp.tool()
def calculate_bs_price(S: float, K: float, T: float, r: float,
                       sigma: float, opt_type: str = "C") -> dict:
    """
    Black-Scholes option price.

    Args:
        S: spot price
        K: strike price
        T: time to expiry in years (e.g. 30 days = 30/365 ≈ 0.082)
        r: risk-free rate (decimal, e.g. 0.05)
        sigma: volatility (decimal, e.g. 0.45 = 45%)
        opt_type: 'C' for call, 'P' for put
    """
    price = black_scholes(S, K, T, r, sigma, opt_type)
    return {"price": round(price, 4), "S": S, "K": K, "T": T, "r": r,
            "sigma": sigma, "opt_type": opt_type}


@mcp.tool()
def calculate_greeks(S: float, K: float, T: float, r: float,
                     sigma: float, opt_type: str = "C") -> dict:
    """
    Black-Scholes Greeks via finite-difference (scipy).

    Returns delta, gamma, vega, theta (annualized), rho.

    Args:
        S: spot price
        K: strike price
        T: time to expiry in years
        r: risk-free rate (decimal)
        sigma: volatility (decimal)
        opt_type: 'C' or 'P'
    """
    delta, gamma, vega, theta, rho = greeks_scipy(S, K, T, r, sigma, opt_type)
    return {
        "delta": round(delta, 4), "gamma": round(gamma, 6),
        "vega": round(vega, 4), "theta": round(theta, 4), "rho": round(rho, 4),
        "S": S, "K": K, "T": T,
    }


@mcp.tool()
def calculate_implied_vol(S: float, K: float, T: float, r: float,
                          market_price: float, opt_type: str = "C") -> dict:
    """
    Implied volatility via Brent's method.

    Args:
        S: spot price
        K: strike price
        T: time to expiry in years
        r: risk-free rate (decimal)
        market_price: observed market price of the option
        opt_type: 'C' or 'P'
    """
    iv = implied_volatility(S, K, T, r, market_price, opt_type)
    result = {"iv": round(iv, 4) if not np.isnan(iv) else None,
              "S": S, "K": K, "T": T, "market_price": market_price}
    if not np.isnan(iv):
        delta, gamma, vega, theta, rho = greeks_scipy(S, K, T, r, iv, opt_type)
        result.update({"delta": round(delta, 4), "gamma": round(gamma, 6),
                       "vega": round(vega, 4), "theta": round(theta, 4)})
    return result


@mcp.tool()
def calculate_ccl_from_prices(al30_bid: float, al30_ask: float,
                               al30d_bid: float, al30d_ask: float) -> dict:
    """
    Compute CCL rate from AL30 (ARS) and AL30D (USD) bid/ask prices.

    CCL_mid  = AL30_mid / AL30D_mid
    CCL_bid  = AL30_bid / AL30D_ask   (worst-case buy)
    CCL_ask  = AL30_ask / AL30D_bid   (worst-case sell)
    """
    mid, bid, ask = calculate_ccl(al30_bid, al30_ask, al30d_bid, al30d_ask)
    return {"ccl_mid": round(mid, 2), "ccl_bid": round(bid, 2), "ccl_ask": round(ask, 2)}


@mcp.tool()
def calculate_dlr_fair_value(spot_ars_usd: float, days_to_expiry: int,
                              rate_ars: float, rate_usd: float = 0.0) -> dict:
    """
    Simple cost-of-carry fair value for DLR futures.
    F = S × e^((r_ars − r_usd) × T)

    Args:
        spot_ars_usd: current ARS/USD spot rate (e.g. from CCL mid)
        days_to_expiry: calendar days until contract expires
        rate_ars: Argentine peso interest rate (decimal, e.g. 0.40 = 40%)
        rate_usd: USD rate (decimal, default 0.0)
    """
    fv = estimate_dlr_fair_value(spot_ars_usd, days_to_expiry, rate_ars, rate_usd)
    return {
        "fair_value": round(fv, 2),
        "spot": spot_ars_usd,
        "days": days_to_expiry,
        "rate_ars": rate_ars,
        "rate_usd": rate_usd,
    }


# ---------------------------------------------------------------------------
# 13. Redis live prices
# ---------------------------------------------------------------------------

@mcp.tool()
def get_redis_live_snapshot(timeout_ms: int = 2000) -> dict:
    """
    Samples Redis pub/sub channels for a short window and returns
    the latest message from each channel.

    Channels: binance:ticks, binance:trades, us_futures:ticks,
              matriz:ticks, matriz:orders

    Args:
        timeout_ms: how long to listen in milliseconds (default 2000)
    """
    import redis as redis_lib
    import json as _json
    from collections import defaultdict

    host = os.getenv("REDIS_HOST", "100.112.16.115")
    port = int(os.getenv("REDIS_PORT", "6379"))

    channels = ["binance:ticks", "binance:trades", "us_futures:ticks",
                "matriz:ticks", "matriz:orders"]
    latest: dict[str, dict] = {}

    try:
        r = redis_lib.Redis(host=host, port=port, socket_connect_timeout=2)
        r.ping()
        ps = r.pubsub()
        ps.subscribe(*channels)

        import time
        deadline = time.time() + timeout_ms / 1000.0

        for msg in ps.listen():
            if time.time() > deadline:
                break
            if msg["type"] != "message":
                continue
            ch = msg["channel"].decode() if isinstance(msg["channel"], bytes) else msg["channel"]
            data_raw = msg["data"].decode() if isinstance(msg["data"], bytes) else msg["data"]
            try:
                latest[ch] = _json.loads(data_raw)
            except Exception:
                latest[ch] = {"raw": data_raw}

        ps.unsubscribe()
        r.close()
        return {"status": "ok", "channels_received": list(latest.keys()), "data": latest}

    except Exception as e:
        return {"status": "error", "error": str(e),
                "note": "Set REDIS_HOST=100.112.16.115 if running outside Docker"}


# ---------------------------------------------------------------------------
# 14. Write tools
# ---------------------------------------------------------------------------

@mcp.tool()
def save_backtest_result(
    strategy_name: str,
    instrument: str,
    sharpe_ratio: float,
    total_return: float,
    max_drawdown: float,
    win_rate: float = 0.0,
    num_trades: int = 0,
    profit_factor: float = 0.0,
    metadata: str = "",
) -> dict:
    """
    Persist a backtest run to `bt_strategy_runs`.

    Args:
        strategy_name: e.g. 'rsi_reversion'
        instrument: e.g. 'GGAL', 'AL30'
        sharpe_ratio: annualised Sharpe
        total_return: decimal e.g. 0.15 = 15%
        max_drawdown: decimal e.g. -0.10 = -10%
        win_rate: decimal e.g. 0.55 = 55%
        num_trades: total number of trades
        profit_factor: gross profit / gross loss
        metadata: JSON string with extra params
    """
    import json as _json
    meta = metadata if metadata else "{}"
    rows = _pg_write(
        """
        INSERT INTO bt_strategy_runs
            (run_at, instrument, strategy, date,
             total_return, sharpe, max_drawdown, win_rate,
             num_trades, profit_factor, expectancy, metadata)
        VALUES
            (NOW(), :instrument, :strategy, CURRENT_DATE,
             :total_return, :sharpe, :max_drawdown, :win_rate,
             :num_trades, :profit_factor, 0, :metadata::jsonb)
        """,
        {
            "instrument": instrument, "strategy": strategy_name,
            "total_return": total_return, "sharpe": sharpe_ratio,
            "max_drawdown": max_drawdown, "win_rate": win_rate,
            "num_trades": num_trades, "profit_factor": profit_factor,
            "metadata": meta,
        },
    )
    return {"saved": rows == 1}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
