"""
Strategy runner — ejecuta múltiples estrategias contra datos históricos reales
y persiste resultados en backtest_runs.

Uso:
    PYTHONPATH=. python finance/HFT/backtest/run_strategies.py
    PYTHONPATH=. python finance/HFT/backtest/run_strategies.py --date 2025-10-15
    PYTHONPATH=. python finance/HFT/backtest/run_strategies.py --strategy ofi
"""
import argparse
import sys
from datetime import date, timedelta

from finance.utils.logger import logger
from finance.utils.db_pool import get_pg_engine
from finance.HFT.backtest.main import MarketDataBacktester, print_report
from finance.HFT.backtest.db.load_data import load_order_data, load_tick_data
from finance.HFT.backtest.strategies.dlr_strategies import (
    ofi_strategy, mean_reversion_strategy, vwap_momentum_strategy
)
from finance.HFT.backtest.mq.publisher import publish_result
from finance.monitoring.metrics import (
    BACKTEST_RUNS, BACKTEST_RETURN, BACKTEST_SHARPE, BACKTEST_WIN_RATE, BACKTEST_PROFIT_FACTOR
)
from prometheus_client import CollectorRegistry, Gauge, Counter, push_to_gateway
from sqlalchemy import text

def _make_lgbm_strategy(instrument_type: str):
    """Wrap LightGBM model as a standard strategy function."""
    from finance.HFT.ml.supervised import load_model, predict
    from finance.HFT.ml.features import extract_features, FEATURE_COLS
    from finance.HFT.backtest.types import Direction, OrderType
    import pandas as pd

    model = load_model(instrument_type)

    def _strategy(current_market, recent_trades, current_position, current_cash):
        if not current_market or len(recent_trades) < 10:
            return []
        instrument = current_market.instrument
        ticks_df = pd.DataFrame([{
            'time': current_market.timestamp, 'bid_price': current_market.bid_price,
            'ask_price': current_market.ask_price, 'bid_volume': current_market.bid_volume,
            'ask_volume': current_market.ask_volume, 'total_volume': 0, 'instrument': instrument,
        }])
        trades_df = pd.DataFrame([{
            'time': t.timestamp, 'price': t.price, 'volume': t.volume,
            'side': 'B' if t.direction and t.direction.name == 'BUY' else 'S',
            'instrument': instrument,
        } for t in recent_trades])
        try:
            feat = extract_features(ticks_df, trades_df).fillna(0.0)
            if feat.empty:
                return []
            obs = feat.iloc[-1][FEATURE_COLS].values
            action = predict(model, obs)  # -1/0/1
        except Exception:
            return []
        if action == 0:
            return []
        direction = Direction.BUY if action == 1 else Direction.SELL
        pos = current_position.get(instrument, 0)
        if (direction == Direction.BUY and pos > 0) or (direction == Direction.SELL and pos < 0):
            return []
        return [{'direction': direction, 'volume': 1, 'order_type': OrderType.MARKET, 'instrument': instrument}]

    return _strategy


def _make_ppo_strategy(instrument_type: str):
    """Wrap PPO policy as a standard strategy function."""
    from finance.HFT.ml.rl_agent import load_policy
    from finance.HFT.ml.features import extract_features, FEATURE_COLS
    from finance.HFT.backtest.types import Direction, OrderType
    import numpy as np
    import pandas as pd

    policy = load_policy(instrument_type)

    def _strategy(current_market, recent_trades, current_position, current_cash):
        if not current_market or len(recent_trades) < 10:
            return []
        instrument = current_market.instrument
        ticks_df = pd.DataFrame([{
            'time': current_market.timestamp, 'bid_price': current_market.bid_price,
            'ask_price': current_market.ask_price, 'bid_volume': current_market.bid_volume,
            'ask_volume': current_market.ask_volume, 'total_volume': 0, 'instrument': instrument,
        }])
        trades_df = pd.DataFrame([{
            'time': t.timestamp, 'price': t.price, 'volume': t.volume,
            'side': 'B' if t.direction and t.direction.name == 'BUY' else 'S',
            'instrument': instrument,
        } for t in recent_trades])
        try:
            feat = extract_features(ticks_df, trades_df).fillna(0.0)
            if feat.empty:
                return []
            obs = feat.iloc[-1][FEATURE_COLS].values.astype(np.float32)
            action, _ = policy.predict(obs, deterministic=True)
            action = int(action)  # 0=HOLD, 1=BUY, 2=SELL
        except Exception:
            return []
        if action == 0:
            return []
        direction = Direction.BUY if action == 1 else Direction.SELL
        pos = current_position.get(instrument, 0)
        if (direction == Direction.BUY and pos > 0) or (direction == Direction.SELL and pos < 0):
            return []
        return [{'direction': direction, 'volume': 1, 'order_type': OrderType.MARKET, 'instrument': instrument}]

    return _strategy


STRATEGIES = {
    "debug":          lambda bt: bt.debug_strategy,
    "ofi":            lambda bt: ofi_strategy,
    "mean_reversion": lambda bt: mean_reversion_strategy,
    "vwap":           lambda bt: vwap_momentum_strategy,
    "lgbm":           lambda bt: _make_lgbm_strategy('DLR'),
    "ppo":            lambda bt: _make_ppo_strategy('DLR'),
}

# Days with confirmed data (ticks + orders for DLR futures)
AVAILABLE_DATES = {
    "OCT25": [f"2025-10-{d:02d}" for d in [2,3,6,7,8,9,13,14,15,16,17,20,21,22,23,24,27,28,29,30,31]],
    "SEP25": [f"2025-09-{d:02d}" for d in [3,4,5,8,9,10,11,12,15,16,17,18,19,22,23,24,25,26,29,30]],
    "NOV25": [f"2025-11-{d:02d}" for d in [3,4,5,6,7,10,11,12,13,14,17,18,19,20,21,24,25,26,27,28]],
}


def _db_insert(payload: dict):
    """Direct DB insert for bt_strategy_runs (fallback when RabbitMQ unavailable)."""
    with get_pg_engine().begin() as conn:
        conn.execute(text("""
            INSERT INTO bt_strategy_runs
                (instrument, strategy, date, total_return, sharpe, max_drawdown,
                 win_rate, num_trades, profit_factor, expectancy, skipped_trades, metadata)
            VALUES
                (:instrument, :strategy, :date, :total_return, :sharpe, :max_drawdown,
                 :win_rate, :num_trades, :profit_factor, :expectancy, :skipped_trades,
                 CAST(:metadata AS jsonb))
        """), payload)


def _save_result(instrument: str, strategy: str, date_str: str, metrics: dict):
    """Persist backtest result — via RabbitMQ if available, else direct DB."""
    if not metrics or metrics.get('num_trades', 0) == 0:
        return
    try:
        import json, math
        def _safe(v):
            if v is None: return None
            try:
                f = float(v)
                return None if (math.isnan(f) or math.isinf(f)) else f
            except Exception:
                return None

        payload = {
            "instrument": instrument,
            "strategy": strategy,
            "date": date_str,
            "total_return": _safe(metrics.get("total_return")),
            "sharpe": _safe(metrics.get("sharpe_ratio")),
            "max_drawdown": _safe((metrics.get("max_drawdown_pct") or 0) / 100),
            "win_rate": _safe(metrics.get("win_rate")),
            "num_trades": int(metrics.get("num_trades", 0)),
            "profit_factor": _safe(metrics.get("profit_factor")),
            "expectancy": _safe(metrics.get("expectancy")),
            "skipped_trades": int(metrics.get("skipped_trades", 0)),
            "metadata": json.dumps({"signal_stats": metrics.get("signal_stats")}),
        }

        # Try RabbitMQ first; fall back to direct DB
        if not publish_result(payload):
            _db_insert(payload)

        logger.info("Saved → bt_strategy_runs: {strategy}@{date} return={ret:.2f}% sharpe={sharpe:.2f}",
                    strategy=strategy, date=date_str,
                    ret=(metrics.get("total_return") or 0) * 100,
                    sharpe=metrics.get("sharpe_ratio") or 0)
        # Push to Prometheus Pushgateway
        try:
            reg = CollectorRegistry()
            Counter("algotrading_backtest_runs_total",    "Total backtest runs",          ["strategy"],              registry=reg).labels(strategy=strategy).inc()
            Gauge("algotrading_backtest_total_return",   "Last backtest total return",   ["strategy","instrument"], registry=reg).labels(strategy=strategy, instrument=instrument).set(metrics.get("total_return") or 0)
            Gauge("algotrading_backtest_sharpe",         "Last backtest Sharpe ratio",   ["strategy","instrument"], registry=reg).labels(strategy=strategy, instrument=instrument).set(metrics.get("sharpe_ratio") or 0)
            Gauge("algotrading_backtest_win_rate",       "Last backtest win rate",        ["strategy","instrument"], registry=reg).labels(strategy=strategy, instrument=instrument).set(metrics.get("win_rate") or 0)
            Gauge("algotrading_backtest_profit_factor",  "Last backtest profit factor",  ["strategy","instrument"], registry=reg).labels(strategy=strategy, instrument=instrument).set(metrics.get("profit_factor") or 0)
            push_to_gateway("localhost:9091", job="backtest", grouping_key={"strategy": strategy, "instrument": instrument}, registry=reg)
        except Exception as pe:
            logger.debug("Pushgateway unavailable: {e}", e=pe)
    except Exception as e:
        logger.error("Failed to save result: {e}", e=e)


def run_one(strategy_name: str, date_str: str, initial_capital: float = 2_000_000) -> dict:
    """Run a single strategy on a single date. Returns metrics dict."""
    logger.info("=== {strategy} | {date} ===", strategy=strategy_name, date=date_str)
    try:
        trades_df = load_order_data(date_str)
        ticks_df  = load_tick_data(date_str)
    except Exception as e:
        logger.error("Failed to load data for {date}: {e}", date=date_str, e=e)
        return {}

    if trades_df.empty or ticks_df.empty:
        logger.warning("No data for {date}", date=date_str)
        return {}

    bt = MarketDataBacktester(initial_capital=initial_capital)
    bt.load_market_data(trades_df, ticks_df)

    if not bt.instrument_multipliers:
        logger.warning("No valid instruments for {date}", date=date_str)
        return {}

    strategy_fn = STRATEGIES[strategy_name](bt)
    bt.run_backtest(strategy_fn)
    metrics = bt.generate_report(plot=False)

    instrument = list(bt.instrument_multipliers.keys())[0]
    _save_result(instrument, strategy_name, date_str, metrics)
    return metrics


def run_all(strategy_name: str, contract: str = "OCT25"):
    """Run strategy across all available dates for a contract."""
    dates = AVAILABLE_DATES.get(contract, AVAILABLE_DATES["OCT25"])
    results = []
    for d in dates:
        m = run_one(strategy_name, d)
        if m:
            results.append({"date": d, **m})

    if not results:
        logger.warning("No results for {strategy} on {contract}", strategy=strategy_name, contract=contract)
        return

    import pandas as pd
    df = pd.DataFrame(results).set_index("date")
    print(f"\n{'='*60}")
    print(f"SUMMARY: {strategy_name} on {contract} ({len(df)} days)")
    print(f"{'='*60}")
    cols = ["total_return_pct", "sharpe_ratio", "max_drawdown_pct", "win_rate_pct", "num_trades"]
    available = [c for c in cols if c in df.columns]
    print(df[available].to_string())
    print(f"\nMean return:   {df['total_return_pct'].mean():.3f}%")
    print(f"Mean Sharpe:   {df['sharpe_ratio'].mean():.3f}")
    print(f"Mean drawdown: {df['max_drawdown_pct'].mean():.3f}%")
    print(f"Win days:      {(df['total_return_pct'] > 0).sum()}/{len(df)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HFT Strategy Runner")
    parser.add_argument("--strategy", default="ofi",
                        choices=list(STRATEGIES.keys()),
                        help="Strategy to run (lgbm/ppo require trained model in finance/HFT/ml/models/)")
    parser.add_argument("--date", default=None,
                        help="Single date YYYY-MM-DD (default: run all OCT25 dates)")
    parser.add_argument("--contract", default="OCT25",
                        choices=list(AVAILABLE_DATES.keys()) + ["ALL"],
                        help="Contract month to backtest, or ALL")
    parser.add_argument("--capital", type=float, default=2_000_000,
                        help="Initial capital in ARS")
    args = parser.parse_args()

    if args.date:
        metrics = run_one(args.strategy, args.date, args.capital)
        if metrics:
            print_report(metrics)
    elif args.contract == "ALL":
        strategies = list(STRATEGIES.keys()) if args.strategy == "ofi" else [args.strategy]
        for strat in strategies:
            for contract in AVAILABLE_DATES:
                run_all(strat, contract)
    else:
        run_all(args.strategy, args.contract)
