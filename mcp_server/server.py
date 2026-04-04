"""
AlgoTrading MCP Server

Provides read access to PostgreSQL (marketdata) and MySQL (investments).
Data contract defined in DATA_SPEC.md.

Key rules from DATA_SPEC.md:
- All timestamps are UTC. Use AT TIME ZONE 'America/Argentina/Buenos_Aires' for ART.
- `ticks` and `orders` are TimescaleDB hypertables — use time_bucket() for aggregations.
- `total_volume` in `ticks` is cumulative daily, NOT incremental.
  Volume per period = MAX(total_volume) - MIN(total_volume).
- Compressed chunks (>7 days) are transparent to queries but prefer time_bucket() for performance.
- No data on weekends or Argentine market holidays.
- Active futures instrument changes monthly — query dynamically, don't hardcode.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import psycopg2.extras
from mcp.server.fastmcp import FastMCP
from sqlalchemy import text
from data.cache import cache_get, cache_set, TTL_MARKET, TTL_HISTORICAL
from shared.db_pool import get_pg_engine, get_mysql_engine

mcp = FastMCP("algotrading-db")

# ---------------------------------------------------------------------------
# Connection helpers — use pooled engines
# ---------------------------------------------------------------------------

def _pg_query(sql: str, params=None) -> list[dict]:
    with get_pg_engine().connect() as conn:
        result = conn.execute(text(sql), params or {})
        return [dict(r._mapping) for r in result.fetchall()]


def _mysql_query(sql: str, params=None) -> list[dict]:
    with get_mysql_engine().connect() as conn:
        result = conn.execute(text(sql), params or {})
        return [dict(r._mapping) for r in result.fetchall()]


def _pg_write(sql: str, params=None) -> int:
    with get_pg_engine().begin() as conn:
        result = conn.execute(text(sql), params or {})
        return result.rowcount


# ---------------------------------------------------------------------------
# PostgreSQL tools — ticks (BYMA real-time quotes)
# ---------------------------------------------------------------------------

@mcp.tool()
def get_ticks(instrument: str, limit: int = 100) -> list[dict]:
    """
    Latest ticks for an instrument from the `ticks` hypertable.

    NOTE: total_volume is cumulative daily — NOT incremental per tick.
    Timestamps are UTC.

    Args:
        instrument: e.g. 'M:bm_MERV_AL30_24hs'
        limit: number of rows (default 100, max 1000)
    """
    limit = min(limit, 1000)
    key = f"ticks:{instrument}:{limit}"
    cached = cache_get(key)
    if cached is not None:
        return cached
    result = _pg_query(
        """
        SELECT time, instrument, bid_price, ask_price, last_price,
               total_volume, high, low, prev_close
        FROM ticks
        WHERE instrument = :instrument
        ORDER BY time DESC
        LIMIT :limit
        """,
        {"instrument": instrument, "limit": limit},
    )
    cache_set(key, result, TTL_MARKET)
    return result


@mcp.tool()
def get_ohlcv(instrument: str, bucket: str = "1 minute", hours_back: int = 24) -> list[dict]:
    """
    OHLCV candles from `ticks` using time_bucket().

    Volume = MAX(total_volume) - MIN(total_volume) per bucket
    (because total_volume is cumulative daily).
    Timestamps returned in UTC.

    Args:
        instrument: e.g. 'M:bm_MERV_AL30_24hs'
        bucket: time bucket size, e.g. '1 minute', '5 minutes', '1 hour'
        hours_back: how many hours of history (default 24)
    """
    key = f"ohlcv:{instrument}:{bucket}:{hours_back}"
    cached = cache_get(key)
    if cached is not None:
        return cached
    result = _pg_query(
        """
        SELECT
            time_bucket(:bucket, time) AS bucket,
            instrument,
            FIRST(last_price, time)                        AS open,
            MAX(high)                                      AS high,
            MIN(low)                                       AS low,
            LAST(last_price, time)                         AS close,
            MAX(total_volume) - MIN(total_volume)          AS volume
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
def get_active_instruments() -> list[dict]:
    """
    Returns all instruments with ticks in the last 3 days.
    Use this to find the current active futures contract (changes monthly).
    """
    return _pg_query(
        """
        SELECT DISTINCT instrument
        FROM ticks
        WHERE time > NOW() - INTERVAL '3 days'
        ORDER BY instrument
        """
    )


@mcp.tool()
def get_spread(instrument: str, bucket: str = "1 hour", days_back: int = 7) -> list[dict]:
    """
    Average bid-ask spread per time bucket.

    Args:
        instrument: e.g. 'M:bm_MERV_AL30_24hs'
        bucket: e.g. '1 hour', '15 minutes'
        days_back: history in days (default 7)
    """
    return _pg_query(
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
# PostgreSQL tools — orders (executed trades)
# ---------------------------------------------------------------------------

@mcp.tool()
def get_orders(hours_back: int = 2, instrument: str | None = None) -> list[dict]:
    """
    Executed orders from the `orders` hypertable.
    side: 'B' = buy, 'S' = sell. Timestamps in UTC.

    Args:
        hours_back: history window in hours (default 2)
        instrument: optional filter, e.g. 'rx_DDF_DLR_MAR26'
    """
    if instrument:
        return _pg_query(
            """
            SELECT time, instrument, price, volume, side
            FROM orders
            WHERE time > NOW() - (:hours || ' hours')::INTERVAL
              AND instrument = :instrument
            ORDER BY time DESC
            LIMIT 1000
            """,
            {"hours": str(hours_back), "instrument": instrument},
        )
    return _pg_query(
        """
        SELECT time, instrument, price, volume, side
        FROM orders
        WHERE time > NOW() - (:hours || ' hours')::INTERVAL
        ORDER BY time DESC
        LIMIT 1000
        """,
        {"hours": str(hours_back)},
    )


@mcp.tool()
def get_order_flow(days_back: int = 1) -> list[dict]:
    """
    Buy vs sell volume per instrument (order flow imbalance).

    Args:
        days_back: history in days (default 1)
    """
    return _pg_query(
        """
        SELECT
            instrument,
            SUM(CASE WHEN side = 'B' THEN volume ELSE 0 END) AS vol_buy,
            SUM(CASE WHEN side = 'S' THEN volume ELSE 0 END) AS vol_sell,
            COUNT(*) AS num_trades
        FROM orders
        WHERE time > NOW() - (:days || ' days')::INTERVAL
        GROUP BY instrument
        ORDER BY num_trades DESC
        """,
        {"days": str(days_back)},
    )


# ---------------------------------------------------------------------------
# PostgreSQL tools — binance_ticks
# ---------------------------------------------------------------------------

@mcp.tool()
def get_binance_ticks(symbol: str, limit: int = 60) -> list[dict]:
    """
    Latest 1-minute OHLCV candles from Binance.

    Args:
        symbol: e.g. 'USDTARS', 'BTCUSDT'
        limit: number of candles (default 60, max 1000)
    """
    limit = min(limit, 1000)
    return _pg_query(
        """
        SELECT timestamp, open, high, low, close, volume
        FROM binance_ticks
        WHERE symbol = :symbol
        ORDER BY timestamp DESC
        LIMIT :limit
        """,
        {"symbol": symbol, "limit": limit},
    )


# ---------------------------------------------------------------------------
# PostgreSQL tools — backtest results (write)
# ---------------------------------------------------------------------------

@mcp.tool()
def save_backtest_result(
    strategy_name: str,
    instrument: str,
    sharpe_ratio: float,
    total_return: float,
    max_drawdown: float,
    metadata: str = "",
) -> dict:
    """
    Save a backtest result to PostgreSQL.
    Creates the table if it doesn't exist.

    Args:
        strategy_name: name of the strategy
        instrument: instrument traded
        sharpe_ratio: annualized Sharpe ratio
        total_return: total return as decimal (e.g. 0.15 = 15%)
        max_drawdown: max drawdown as decimal (e.g. -0.10 = -10%)
        metadata: optional JSON string with extra params
    """
    _pg_write(
        """
        CREATE TABLE IF NOT EXISTS backtest_results (
            id           SERIAL PRIMARY KEY,
            created_at   TIMESTAMPTZ DEFAULT NOW(),
            strategy     TEXT NOT NULL,
            instrument   TEXT NOT NULL,
            sharpe       NUMERIC(10,4),
            total_return NUMERIC(10,4),
            max_drawdown NUMERIC(10,4),
            metadata     TEXT
        )
        """
    )
    rows = _pg_write(
        """
        INSERT INTO backtest_results
            (strategy, instrument, sharpe, total_return, max_drawdown, metadata)
        VALUES (:strategy, :instrument, :sharpe, :total_return, :max_drawdown, :metadata)
        """,
        {"strategy": strategy_name, "instrument": instrument, "sharpe": sharpe_ratio,
         "total_return": total_return, "max_drawdown": max_drawdown, "metadata": metadata},
    )
    return {"saved": rows == 1}


# ---------------------------------------------------------------------------
# MySQL tools — market_data (historical OHLCV)
# ---------------------------------------------------------------------------

@mcp.tool()
def get_market_data(ticker: str, limit: int = 100) -> list[dict]:
    """
    Historical OHLCV data from MySQL `market_data` table.

    Args:
        ticker: e.g. 'GGAL'
        limit: number of rows (default 100, max 5000)
    """
    limit = min(limit, 5000)
    return _mysql_query(
        "SELECT * FROM market_data WHERE ticker = :ticker ORDER BY timestamp DESC LIMIT :limit",
        {"ticker": ticker, "limit": limit},
    )


@mcp.tool()
def get_market_data_range(ticker: str, date_from: str, date_to: str) -> list[dict]:
    """
    Historical OHLCV for a ticker between two dates.

    Args:
        ticker: e.g. 'GGAL'
        date_from: 'YYYY-MM-DD'
        date_to: 'YYYY-MM-DD'
    """
    return _mysql_query(
        """
        SELECT * FROM market_data
        WHERE ticker = :ticker AND timestamp BETWEEN :date_from AND :date_to
        ORDER BY timestamp ASC
        """,
        {"ticker": ticker, "date_from": date_from, "date_to": date_to},
    )


@mcp.tool()
def get_available_tickers() -> list[dict]:
    """List all distinct tickers available in MySQL market_data."""
    return _mysql_query("SELECT DISTINCT ticker FROM market_data ORDER BY ticker")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
