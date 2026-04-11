"""
BT-06: Backtest report — reads bt_strategy_runs and prints comparative table.
Usage:
  python3 -m finance.HFT.backtest.bt_report
  python3 -m finance.HFT.backtest.bt_report --strategy vwap
  python3 -m finance.HFT.backtest.bt_report --instrument rx_DDF_DLR_OCT25
  python3 -m finance.HFT.backtest.bt_report --from-date 2025-10-01 --to-date 2025-10-31
  python3 -m finance.HFT.backtest.bt_report --best
"""
import argparse
import pandas as pd
from sqlalchemy import text
from finance.utils.db_pool import get_pg_engine


def _load(strategy=None, instrument=None, from_date=None, to_date=None) -> pd.DataFrame:
    filters, params = [], {}
    if strategy:
        filters.append("strategy = :strategy"); params["strategy"] = strategy
    if instrument:
        filters.append("instrument ILIKE :instrument"); params["instrument"] = f"%{instrument}%"
    if from_date:
        filters.append("date >= :from_date"); params["from_date"] = from_date
    if to_date:
        filters.append("date <= :to_date"); params["to_date"] = to_date
    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    with get_pg_engine().connect() as conn:
        return pd.read_sql(text(f"""
            SELECT strategy, instrument, date, total_return, sharpe, win_rate,
                   profit_factor, num_trades, run_at
            FROM bt_strategy_runs {where}
            ORDER BY run_at DESC
        """), conn, params=params)


def _fmt(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "total_return" in df:
        df["return%"] = df["total_return"].apply(
            lambda x: f"{x*100:.2f}%" if x is not None and abs(x) < 10 else f"{x:.2f}" if x is not None else "-"
        )
    for col in ["sharpe", "win_rate", "profit_factor"]:
        if col in df:
            df[col] = df[col].apply(lambda x: f"{x:.3f}" if x is not None else "-")
    return df


ML_STRATEGIES = {'lgbm', 'ppo', 'ppo_live'}


def print_table(df: pd.DataFrame):
    if df.empty:
        print("No results found.")
        return
    df = _fmt(df.copy())
    df['type'] = df['strategy'].apply(lambda s: 'ML/RL' if s in ML_STRATEGIES else 'rule')
    display = df[["type", "strategy", "instrument", "date", "return%", "sharpe", "win_rate", "profit_factor", "num_trades"]]
    print(display.to_string(index=False))


def print_best(df: pd.DataFrame):
    """Best strategy per instrument by total_return (or sharpe if available)."""
    if df.empty:
        print("No results found.")
        return
    df = df.copy()
    df["score"] = df["sharpe"].where(df["sharpe"].notna(), df["total_return"])
    best = df.sort_values("score", ascending=False).groupby("instrument").first().reset_index()
    print("\n=== Best strategy per instrument ===")
    print(_fmt(best)[["instrument", "strategy", "return%", "sharpe", "win_rate", "num_trades"]].to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy")
    parser.add_argument("--instrument")
    parser.add_argument("--from-date")
    parser.add_argument("--to-date")
    parser.add_argument("--best", action="store_true", help="Show best strategy per instrument")
    args = parser.parse_args()

    df = _load(args.strategy, args.instrument, args.from_date, args.to_date)
    print(f"\n=== Backtest Results ({len(df)} runs) ===")
    print_table(df)
    if args.best or (not args.strategy and not args.instrument):
        print_best(df)
