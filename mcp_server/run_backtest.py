"""
HFT Backtest Agent

Rol: Experto en arquitectura HFT y procesamiento de datos financieros.
Objetivo: Mantener la integridad de finance/HFT/backtest/ según AUDITORIA_ARQUITECTURA_v2.md.

Reglas:
- Nunca hardcodear instrumentos de futuros — consultar ticks dinámicamente.
- Reutilizar clases de finance/HFT/dashboard/calcultions.py y finance/PPI/classes/.
- Datos de entrada siempre via MarketDataBacktester.load_market_data().
- Resultados siempre registrados en backtest_runs (PostgreSQL).
"""

import os
import sys
import json
import asyncio
from datetime import datetime

import psycopg2
import psycopg2.extras
import pandas as pd
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Internal imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from finance.HFT.backtest.main import MarketDataBacktester
from finance.HFT.dashboard.calcultions import (
    RollingOFITFIProcessor,
    HybridFlowAnalyzer,
    calculate_spread_stats,
    enhanced_order_flow_imbalance,
)

# ---------------------------------------------------------------------------
# MCP client helpers
# ---------------------------------------------------------------------------

MCP_SERVER = StdioServerParameters(
    command=os.path.join(os.path.dirname(__file__), "../venv/bin/python"),
    args=[os.path.join(os.path.dirname(__file__), "../mcp_server/server.py")],
    env={
        "POSTGRES_HOST": os.environ.get("POSTGRES_HOST", "100.112.16.115"),
        "POSTGRES_PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "POSTGRES_DB": os.environ.get("POSTGRES_DB", "marketdata"),
        "POSTGRES_USER": os.environ.get("POSTGRES_USER", "postgres"),
        "POSTGRES_PASSWORD": os.environ["POSTGRES_PASSWORD"],
        "DB_HOST": os.environ.get("DB_HOST", "100.112.16.115"),
        "DB_PORT": os.environ.get("DB_PORT", "3306"),
        "DB_USER": os.environ.get("DB_USER", "haraidasan"),
        "DB_PASSWORD": os.environ["DB_PASSWORD"],
        "DB_NAME": os.environ.get("DB_NAME", "investments"),
    },
)


async def _call(session: ClientSession, tool: str, **kwargs):
    result = await session.call_tool(tool, kwargs)
    return json.loads(result.content[0].text)


# ---------------------------------------------------------------------------
# Audit DB — backtest_runs table
# ---------------------------------------------------------------------------

def _ensure_backtest_runs_table():
    conn = psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "100.112.16.115"),
        port=int(os.environ.get("POSTGRES_PORT", 5432)),
        dbname=os.environ.get("POSTGRES_DB", "marketdata"),
        user=os.environ.get("POSTGRES_USER", "postgres"),
        password=os.environ["POSTGRES_PASSWORD"],
        sslmode="disable",
    )
    with conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS backtest_runs (
                    id           SERIAL PRIMARY KEY,
                    run_at       TIMESTAMPTZ DEFAULT NOW(),
                    instrument   TEXT NOT NULL,
                    strategy     TEXT NOT NULL,
                    hours_back   INT,
                    bucket       TEXT,
                    total_return NUMERIC(10,4),
                    sharpe       NUMERIC(10,4),
                    max_drawdown NUMERIC(10,4),
                    win_rate     NUMERIC(10,4),
                    num_trades   INT,
                    metadata     JSONB
                )
            """)
    conn.close()


def _save_run(instrument: str, strategy: str, metrics: dict, hours_back: int, bucket: str):
    _ensure_backtest_runs_table()
    conn = psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "100.112.16.115"),
        port=int(os.environ.get("POSTGRES_PORT", 5432)),
        dbname=os.environ.get("POSTGRES_DB", "marketdata"),
        user=os.environ.get("POSTGRES_USER", "postgres"),
        password=os.environ["POSTGRES_PASSWORD"],
        sslmode="disable",
    )
    with conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO backtest_runs
                    (instrument, strategy, hours_back, bucket,
                     total_return, sharpe, max_drawdown, win_rate, num_trades, metadata)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                instrument, strategy, hours_back, bucket,
                metrics.get("total_return"), metrics.get("sharpe_ratio"),
                metrics.get("max_drawdown"), metrics.get("win_rate"),
                metrics.get("num_trades"), json.dumps(metrics),
            ))
    conn.close()
    print(f"[agent] Run saved to backtest_runs for {instrument} / {strategy}")


# ---------------------------------------------------------------------------
# Core agent logic
# ---------------------------------------------------------------------------

async def run_backtest_agent(
    strategy_name: str = "debug_strategy",
    hours_back: int = 24,
    bucket: str = "1 minute",
):
    """
    Main agent entry point.

    1. Queries active instrument dynamically (never hardcoded).
    2. Fetches ticks + orders via MCP.
    3. Loads data through MarketDataBacktester.load_market_data().
    4. Computes OFI/TFI/spread using existing classes (no duplication).
    5. Runs backtest and saves results to backtest_runs.
    """
    async with stdio_client(MCP_SERVER) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # ── Step 1: Discover active futures instrument ──────────────────
            print("[agent] Querying active instruments...")
            active = await _call(session, "get_active_instruments")
            futures = [r["instrument"] for r in active if "DDF_DLR" in r["instrument"]]
            if not futures:
                print("[agent] No active futures instrument found. Aborting.")
                return
            instrument = futures[0]
            print(f"[agent] Active instrument: {instrument}")

            # ── Step 2: Fetch data via MCP ───────────────────────────────────
            print(f"[agent] Fetching OHLCV ({bucket}, {hours_back}h)...")
            ohlcv_rows = await _call(session, "get_ohlcv",
                                     instrument=instrument,
                                     bucket=bucket,
                                     hours_back=hours_back)

            print(f"[agent] Fetching raw ticks (1000)...")
            tick_rows = await _call(session, "get_ticks",
                                    instrument=instrument,
                                    limit=1000)

            print(f"[agent] Fetching orders ({hours_back}h)...")
            order_rows = await _call(session, "get_orders",
                                     hours_back=hours_back,
                                     instrument=instrument.replace("M:", ""))

            # ── Step 3: Build DataFrames ─────────────────────────────────────
            ticks_df = pd.DataFrame(tick_rows)
            orders_df = pd.DataFrame(order_rows)

            if ticks_df.empty:
                print("[agent] No tick data available. Aborting.")
                return

            for df in (ticks_df, orders_df):
                if "time" in df.columns:
                    df["time"] = pd.to_datetime(df["time"], utc=True)

            # ── Step 4: Compute indicators using existing classes ────────────
            print("[agent] Computing spread stats (calcultions.py)...")
            spread_stats = calculate_spread_stats(ticks_df)
            print(f"  spread avg={spread_stats['avg_spread']:.4f}  "
                  f"std={spread_stats['spread_std']:.4f}")

            if not orders_df.empty:
                print("[agent] Computing OFI/TFI (calcultions.py)...")
                ofi_df = enhanced_order_flow_imbalance(orders_df, window="10min")
                analyzer = HybridFlowAnalyzer()
                for _, row in ticks_df.iterrows():
                    analyzer.update_lob({
                        "time": row["time"],
                        "bid_price": row.get("bid_price", 0),
                        "bid_size": row.get("bid_volume", 0),
                        "ask_price": row.get("ask_price", 0),
                        "ask_size": row.get("ask_volume", 0),
                    })
                for _, row in orders_df.iterrows():
                    analyzer.process_trade({
                        "time": row["time"],
                        "side": row.get("side", "B"),
                        "volume": row.get("volume", 0),
                    })
                flow_stats = analyzer.get_current_stats()
                print(f"  ofi_10min={flow_stats['ofi_10min']:.4f}  "
                      f"tfi_10min={flow_stats['tfi_10min']:.4f}")
            else:
                flow_stats = {}
                print("[agent] No order data — skipping OFI/TFI.")

            # ── Step 5: Run backtest via MarketDataBacktester ────────────────
            print("[agent] Running backtest...")
            backtester = MarketDataBacktester(initial_capital=2_000_000)

            # Rename columns to match load_market_data expectations
            trades_input = ticks_df.rename(columns={
                "time": "time",
                "last_price": "price",
                "total_volume": "volume",
            }).copy()
            trades_input["instrument"] = instrument

            orderbook_input = ticks_df.rename(columns={
                "time": "time",
                "bid_price": "bid_price",
                "ask_price": "ask_price",
                "bid_volume": "bid_volume",
                "ask_volume": "ask_volume",
            }).copy()
            orderbook_input["instrument"] = instrument

            backtester.load_market_data(trades_input, orderbook_input)

            strategy_func = backtester.debug_strategy
            metrics = backtester.run_backtest(strategy_func)

            print(f"[agent] Backtest complete: {metrics}")

            # ── Step 6: Persist results ──────────────────────────────────────
            full_metrics = {
                **metrics,
                "spread_avg": spread_stats["avg_spread"],
                "ofi_10min": flow_stats.get("ofi_10min"),
                "tfi_10min": flow_stats.get("tfi_10min"),
            }
            _save_run(instrument, strategy_name, full_metrics, hours_back, bucket)

            return full_metrics


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="HFT Backtest Agent")
    parser.add_argument("--strategy", default="debug_strategy")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--bucket", default="1 minute")
    args = parser.parse_args()

    results = asyncio.run(run_backtest_agent(
        strategy_name=args.strategy,
        hours_back=args.hours,
        bucket=args.bucket,
    ))
    print("\n=== Final Metrics ===")
    print(json.dumps(results, indent=2, default=str))
