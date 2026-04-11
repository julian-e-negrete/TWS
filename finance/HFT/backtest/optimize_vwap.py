"""
BT-05: VWAP parameter grid search.
Train on OCT25, validate best params on NOV25.
"""
import json, math, itertools
import numpy as np
from sqlalchemy import text
from finance.utils.db_pool import get_pg_engine
from finance.utils.logger import logger
from finance.HFT.backtest.main import MarketDataBacktester
from finance.HFT.backtest.db.load_data import load_order_data, load_tick_data
from finance.HFT.backtest.run_strategies import AVAILABLE_DATES
from finance.HFT.backtest.strategies.dlr_strategies import (
    Direction, OrderType, _instrument, _multiplier, _max_volume
)

# ---------------------------------------------------------------------------
# Parameterized VWAP
# ---------------------------------------------------------------------------

def make_vwap(buffer: float, vol_surge_mult: float):
    def strategy(current_market, recent_trades, current_position, current_cash):
        signals = []
        instrument = _instrument(current_market, recent_trades)
        if not instrument or not current_market or len(recent_trades) < 15:
            return signals
        mult = _multiplier(instrument)
        spread = current_market.ask_price - current_market.bid_price
        mid = (current_market.bid_price + current_market.ask_price) / 2
        if spread / mid > 0.015:  # 1.5% max spread (DLR typical: 0.1-0.7%)
            return signals
        prices  = np.array([t.price for t in recent_trades])
        volumes = np.array([t.volume for t in recent_trades], dtype=float)
        total_vol = volumes.sum()
        if total_vol == 0:
            return signals
        vwap      = (prices * volumes).sum() / total_vol
        last_price = recent_trades[-1].price
        vol_surge  = recent_trades[-1].volume > volumes.mean() * vol_surge_mult
        pos = current_position.get(instrument, 0)
        vol = _max_volume(instrument, current_cash, current_market.ask_price, mult)
        if last_price > vwap * (1 + buffer) and vol_surge and pos <= 0:
            signals.append({'direction': Direction.BUY, 'volume': vol,
                            'order_type': OrderType.MARKET, 'instrument': instrument})
        elif last_price < vwap * (1 - buffer) and vol_surge and pos >= 0:
            signals.append({'direction': Direction.SELL, 'volume': vol,
                            'order_type': OrderType.MARKET, 'instrument': instrument})
        return signals
    return strategy


# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------

BUFFERS    = [round(x, 4) for x in np.arange(0.0002, 0.0022, 0.0002)]
VOL_SURGES = [round(x, 1) for x in np.arange(1.2, 2.2, 0.2)]
GRID       = list(itertools.product(BUFFERS, VOL_SURGES))

TRAIN_CONTRACT    = "OCT25"
VALIDATE_CONTRACT = "NOV25"
INSTRUMENT        = "rx_DDF_DLR_OCT25"
INSTRUMENT_VAL    = "rx_DDF_DLR_NOV25"


def _safe(v):
    if v is None: return None
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 6)
    except Exception:
        return None


def run_grid(dates: list[str], instrument: str, split: str):
    results = []
    instr_bare = instrument.replace("M:", "")
    contract   = instr_bare.split("_")[-1]  # e.g. OCT25

    # Load all days once — ticks have M: prefix, orders don't
    daily_data = {}
    for d in dates:
        try:
            trades_df = load_order_data(d)
            ticks_df  = load_tick_data(d)
            trades_df = trades_df[trades_df["instrument"] == instr_bare]
            ticks_df  = ticks_df[ticks_df["instrument"] == f"M:{instr_bare}"]
            if not trades_df.empty and not ticks_df.empty:
                daily_data[d] = (trades_df, ticks_df)
        except Exception as e:
            logger.warning("load skip {d}: {e}", d=d, e=e)

    logger.info("Loaded {n} days for {split}", n=len(daily_data), split=split)

    for buffer, vsm in GRID:
        params   = {"buffer": buffer, "vol_surge_mult": vsm}
        strategy = make_vwap(buffer, vsm)
        day_metrics = []
        for d, (trades_df, ticks_df) in daily_data.items():
            try:
                bt = MarketDataBacktester(initial_capital=2_000_000)
                bt.load_market_data(trades_df.copy(), ticks_df.copy())
                bt.run_backtest(strategy)
                m = bt.generate_report(plot=False)
                if m and m.get("num_trades", 0) > 0:
                    day_metrics.append(m)
            except Exception as e:
                logger.warning("skip {d} {params}: {e}", d=d, params=params, e=e)

        if not day_metrics:
            continue

        avg = {
            "total_return":  float(np.mean([m["total_return"]  for m in day_metrics])),
            "sharpe":        float(np.mean([m["sharpe_ratio"]   for m in day_metrics])),
            "win_rate":      float(np.mean([m["win_rate"]       for m in day_metrics])),
            "profit_factor": float(np.mean([m.get("profit_factor", 0) or 0 for m in day_metrics])),
            "num_trades":    int(np.mean([m["num_trades"]       for m in day_metrics])),
        }
        results.append((params, avg))
        _save(instrument, params, split, avg)
        logger.info("{split} buffer={b} vsm={v} sharpe={s:.2f} ret={r:.2%} pf={pf:.2f}",
                    split=split, b=buffer, v=vsm,
                    s=avg["sharpe"], r=avg["total_return"], pf=avg["profit_factor"])
    return results


def _save(instrument: str, params: dict, split: str, avg: dict):
    with get_pg_engine().begin() as conn:
        conn.execute(text("""
            INSERT INTO bt_param_search
                (strategy, instrument, params, split, total_return, sharpe, win_rate, profit_factor, num_trades)
            VALUES
                ('vwap', :instrument, CAST(:params AS jsonb), :split,
                 :total_return, :sharpe, :win_rate, :profit_factor, :num_trades)
        """), {
            "instrument": instrument,
            "params": json.dumps(params),
            "split": split,
            **{k: _safe(v) for k, v in avg.items()},
        })


if __name__ == "__main__":
    train_dates = AVAILABLE_DATES[TRAIN_CONTRACT]
    val_dates   = AVAILABLE_DATES[VALIDATE_CONTRACT]

    print(f"Grid: {len(GRID)} combos × {len(train_dates)} train days")
    train_results = run_grid(train_dates, INSTRUMENT, "train")

    # Best params by Sharpe on train
    best_params, best_avg = max(train_results, key=lambda x: x[1]["sharpe"])
    print(f"\nBest train params: {best_params} → sharpe={best_avg['sharpe']:.2f} ret={best_avg['total_return']:.2%}")

    print(f"\nValidating best params on {VALIDATE_CONTRACT}...")
    val_strategy   = make_vwap(best_params["buffer"], best_params["vol_surge_mult"])
    instr_val_bare = INSTRUMENT_VAL.replace("M:", "")
    contract_val   = instr_val_bare.split("_")[-1]
    val_results    = []
    for d in val_dates:
        try:
            trades_df = load_order_data(d)
            ticks_df  = load_tick_data(d)
            trades_df = trades_df[trades_df["instrument"] == instr_val_bare]
            ticks_df  = ticks_df[ticks_df["instrument"] == f"M:{instr_val_bare}"]
            if trades_df.empty or ticks_df.empty:
                continue
            bt = MarketDataBacktester(initial_capital=2_000_000)
            bt.load_market_data(trades_df, ticks_df)
            bt.run_backtest(val_strategy)
            m = bt.generate_report(plot=False)
            if m and m.get("num_trades", 0) > 0:
                val_results.append(m)
        except Exception as e:
            logger.warning("val skip {d}: {e}", d=d, e=e)

    if val_results:
        val_avg = {
            "total_return":  float(np.mean([m["total_return"]  for m in val_results])),
            "sharpe":        float(np.mean([m["sharpe_ratio"]   for m in val_results])),
            "win_rate":      float(np.mean([m["win_rate"]       for m in val_results])),
            "profit_factor": float(np.mean([m.get("profit_factor", 0) or 0 for m in val_results])),
            "num_trades":    int(np.mean([m["num_trades"]       for m in val_results])),
        }
        _save(INSTRUMENT_VAL, best_params, "validate", val_avg)
        print(f"Validation: sharpe={val_avg['sharpe']:.2f} ret={val_avg['total_return']:.2%} "
              f"win_rate={val_avg['win_rate']:.1%} pf={val_avg['profit_factor']:.2f}")
    else:
        print("No validation trades generated")

    print("\nDone. Results in bt_param_search.")
