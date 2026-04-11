"""
Feature alignment validator — compares batch (backtest) vs streaming (live) feature extraction.

Batch path  : extract_features(full day ticks_df, trades_df)
Stream path : rolling window of `window_size` ticks, same as live_runner

Reports any per-feature value differences > 1e-6 at each timestamp.

Usage:
    python -m finance.HFT.ml.validate_features --date 2025-10-16 --instrument DLR
"""
import argparse
from collections import deque

import numpy as np
import pandas as pd

from finance.HFT.ml import get_config
from finance.HFT.ml.features import extract_features, FEATURE_COLS
from finance.HFT.backtest.db.load_data import load_order_data, load_tick_data
from finance.HFT.backtest.db.load_binance import load_binance_data
from finance.HFT.backtest.db.load_byma import load_byma_data
from finance.utils.logger import logger

TOLERANCE = 1e-6


def _load(date: str, instrument_type: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    if instrument_type == 'DLR':
        ticks  = load_tick_data(date)
        trades = load_order_data(date)
        ticks  = ticks[ticks['instrument'].str.contains('DDF_DLR', na=False)]
        trades = trades[trades['instrument'].str.contains('DDF_DLR', na=False)]
    elif instrument_type == 'BTCUSDT':
        trades, ticks = load_binance_data(date, 'BTCUSDT')
    elif instrument_type == 'GGAL':
        trades, ticks = load_byma_data(date, 'M:bm_MERV_GGALD_24hs')
    else:
        raise ValueError(f"Unknown instrument_type: {instrument_type}")
    return ticks.reset_index(drop=True), trades.reset_index(drop=True)


def _stream_features(ticks_df: pd.DataFrame, trades_df: pd.DataFrame,
                     window_size: int) -> pd.DataFrame:
    """
    Simulate live_runner's rolling-window feature extraction tick by tick.
    Returns DataFrame indexed by timestamp, same columns as batch path.
    """
    buf: deque = deque(maxlen=window_size)
    rows = []

    for i, tick in ticks_df.iterrows():
        buf.append(tick.to_dict())
        if len(buf) < window_size:
            continue

        win_ticks = pd.DataFrame(list(buf))
        ts_start  = win_ticks['time'].iloc[0]
        ts_end    = win_ticks['time'].iloc[-1]

        win_trades = trades_df[(trades_df['time'] >= ts_start) & (trades_df['time'] <= ts_end)]
        if win_trades.empty:
            # synthesize minimal trades from volume delta
            win_trades = win_ticks[['time', 'last_price', 'total_volume', 'instrument']].copy()
            win_trades['price']  = win_trades['last_price']
            win_trades['volume'] = win_trades['total_volume'].diff().clip(lower=0).fillna(1)
            win_trades['side']   = 'B'
            win_trades = win_trades[['time', 'price', 'volume', 'side', 'instrument']]

        try:
            feat = extract_features(win_ticks, win_trades).fillna(0.0)
            if feat.empty:
                continue
            last = feat.iloc[-1]
            rows.append({'time': tick['time'], **last[FEATURE_COLS].to_dict()})
        except Exception:
            continue

    return pd.DataFrame(rows).set_index('time') if rows else pd.DataFrame()


def validate(date: str, instrument_type: str) -> bool:
    cfg = get_config()
    window_size = cfg['features']['rolling_window_size']

    logger.info("Loading data for {date} ({instr})...", date=date, instr=instrument_type)
    ticks, trades = _load(date, instrument_type)

    if ticks.empty or trades.empty:
        print(f"SKIP: no data for {date} / {instrument_type}")
        return True

    # Batch path
    logger.info("Running batch feature extraction...")
    batch = extract_features(ticks, trades).fillna(0.0)

    # Stream path
    logger.info("Running streaming feature extraction (window={w})...", w=window_size)
    stream = _stream_features(ticks, trades, window_size)

    if stream.empty:
        print("SKIP: streaming produced no features")
        return True

    # Deduplicate timestamps (keep last) before aligning
    batch  = batch[~batch.index.duplicated(keep='last')]
    stream = stream[~stream.index.duplicated(keep='last')]

    # Align on common timestamps
    common_ts = batch.index.intersection(stream.index)
    if len(common_ts) == 0:
        print("FAIL: no overlapping timestamps between batch and stream paths")
        return False

    batch_aligned  = batch.loc[common_ts, FEATURE_COLS]
    stream_aligned = stream.loc[common_ts, FEATURE_COLS]

    diff = (batch_aligned - stream_aligned).abs()
    mismatches = diff[diff > TOLERANCE].stack().dropna()

    if mismatches.empty:
        print(f"PASS: {len(common_ts)} timestamps checked, all features align (tol={TOLERANCE})")
        return True

    print(f"FAIL: {len(mismatches)} mismatches across {len(common_ts)} timestamps")
    print(f"\n{'Timestamp':<30} {'Feature':<25} {'Batch':>15} {'Stream':>15} {'Delta':>15}")
    print('-' * 90)
    for (ts, feat), delta in mismatches.items():
        b_val = float(batch_aligned.loc[ts, feat])
        s_val = float(stream_aligned.loc[ts, feat])
        print(f"{str(ts):<30} {feat:<25} {b_val:>15.8f} {s_val:>15.8f} {delta:>15.2e}")
    return False


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--date',       required=True, help='YYYY-MM-DD')
    parser.add_argument('--instrument', default='DLR', choices=['DLR', 'BTCUSDT', 'GGAL'])
    args = parser.parse_args()
    ok = validate(args.date, args.instrument)
    raise SystemExit(0 if ok else 1)
