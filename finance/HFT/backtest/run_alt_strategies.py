"""
BT-03 / BT-04: Run strategies on BYMA equities and Binance crypto.
Reuses dlr_strategies with multiplier=1 (BYMA) and 0.1% commission (Binance).

Usage:
    PYTHONPATH=. python3 -m finance.HFT.backtest.run_alt_strategies --market byma --days 10
    PYTHONPATH=. python3 -m finance.HFT.backtest.run_alt_strategies --market binance --days 30
"""
import argparse
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import text

from finance.utils.logger import logger
from finance.utils.db_pool import get_pg_engine
from finance.HFT.backtest.main import MarketDataBacktester
from finance.HFT.backtest.db.load_byma import load_byma_data, BYMA_INSTRUMENTS
from finance.HFT.backtest.db.load_binance import load_binance_data, BINANCE_SYMBOLS
from finance.HFT.backtest.strategies.alt_strategies import (
    byma_vwap, byma_mean_reversion, binance_vwap, binance_mean_reversion
)
from finance.HFT.backtest.run_strategies import _save_result

BYMA_STRATEGIES = {'vwap': byma_vwap, 'mean_reversion': byma_mean_reversion}
BINANCE_STRATEGIES = {'vwap': binance_vwap, 'mean_reversion': binance_mean_reversion}

# Binance commission override (0.1% vs 0.5% for BYMA/DLR)
BINANCE_COMMISSION = 0.001


def _available_dates(market: str, days: int) -> list[str]:
    """Get trading dates from DB for the given market."""
    engine = get_pg_engine()
    with engine.connect() as conn:
        if market == 'byma':
            r = conn.execute(text(f"""
                SELECT DISTINCT DATE(time AT TIME ZONE 'America/Argentina/Buenos_Aires') AS d
                FROM ticks WHERE instrument = 'M:bm_MERV_GGALD_24hs'
                ORDER BY d DESC LIMIT {days}
            """))
        else:
            r = conn.execute(text(f"""
                SELECT DISTINCT timestamp::date AS d
                FROM binance_ticks WHERE symbol = 'BTCUSDT'
                ORDER BY d DESC LIMIT {days}
            """))
        return sorted(str(row[0]) for row in r.fetchall())


def run_one(market: str, instrument: str, date_str: str, strategy_name: str,
            initial_capital: float = 2_000_000) -> dict:
    strategies = BYMA_STRATEGIES if market == 'byma' else BINANCE_STRATEGIES
    if strategy_name not in strategies:
        return {}

    if market == 'byma':
        trades_df, ticks_df = load_byma_data(date_str, instrument)
    else:
        trades_df, ticks_df = load_binance_data(date_str, instrument)

    if trades_df.empty or ticks_df.empty:
        logger.warning("No data: {m} {i} {d}", m=market, i=instrument, d=date_str)
        return {}

    bt = MarketDataBacktester(initial_capital=initial_capital)
    if market == 'binance':
        bt.commission_rate = BINANCE_COMMISSION

    bt.load_market_data(trades_df, ticks_df)
    if not bt.instrument_multipliers:
        return {}

    bt.run_backtest(strategies[strategy_name])
    metrics = bt.generate_report(plot=False)
    _save_result(instrument, f"{market}_{strategy_name}", date_str, metrics)
    return metrics


def run_market(market: str, days: int):
    instruments = BYMA_INSTRUMENTS if market == 'byma' else BINANCE_SYMBOLS
    strategies = list(BYMA_STRATEGIES.keys()) if market == 'byma' else list(BINANCE_STRATEGIES.keys())
    strategy_map = BYMA_STRATEGIES if market == 'byma' else BINANCE_STRATEGIES

    dates = _available_dates(market, days)
    results = []

    for strategy_name in strategies:
        for instrument in instruments:
            for d in dates:
                m = run_one(market, instrument, d, strategy_name)
                if m:
                    results.append({
                        'strategy': strategy_name,
                        'instrument': instrument,
                        'date': d,
                        'return_pct': (m.get('total_return') or 0) * 100,
                        'sharpe': m.get('sharpe_ratio'),
                        'win_rate': m.get('win_rate'),
                        'profit_factor': m.get('profit_factor'),
                        'num_trades': m.get('num_trades'),
                    })

    if not results:
        logger.warning("No results for {m}", m=market)
        return

    df = pd.DataFrame(results)
    summary = df.groupby(['strategy', 'instrument']).agg(
        days=('date', 'count'),
        avg_ret=('return_pct', 'mean'),
        avg_sharpe=('sharpe', 'mean'),
        avg_wr=('win_rate', 'mean'),
        avg_pf=('profit_factor', 'mean'),
    ).round(3)
    print(f"\n=== {market.upper()} BACKTEST SUMMARY ===")
    print(summary.to_string())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--market', choices=['byma', 'binance'], required=True)
    parser.add_argument('--days', type=int, default=10)
    parser.add_argument('--strategy', choices=['vwap', 'mean_reversion'], default=None)
    args = parser.parse_args()
    run_market(args.market, args.days)
