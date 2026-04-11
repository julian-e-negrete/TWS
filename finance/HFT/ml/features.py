"""
Feature extraction for ML/RL trading models.
Shared by supervised.py, env.py, and live_runner.py.

extract_features(ticks_df, trades_df, greeks_df=None) -> pd.DataFrame
  One row per tick timestamp. NaN-safe. Handles DLR, GGAL options, Binance.
"""
import numpy as np
import pandas as pd
from finance.HFT.dashboard.calcultions import enhanced_order_flow_imbalance

FEATURE_COLS = [
    'spread_bps', 'bid_ask_imbalance',
    'ofi_imbalance',
    'vwap_deviation', 'vol_surge_ratio',
    'price_momentum_5', 'price_momentum_20',
    # options Greeks (NaN for non-option instruments)
    'delta', 'gamma', 'vega', 'theta', 'iv', 'underlying_mid',
]

# Core features that must be non-NaN for a row to be usable
CORE_FEATURE_COLS = [
    'spread_bps', 'bid_ask_imbalance', 'ofi_imbalance',
    'vwap_deviation', 'vol_surge_ratio',
    'price_momentum_5', 'price_momentum_20',
]


def extract_features(
    ticks_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    greeks_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Returns a DataFrame indexed by tick timestamp with columns = FEATURE_COLS.
    ticks_df  : columns [time, bid_price, ask_price, bid_volume, ask_volume, total_volume, instrument]
    trades_df : columns [time, price, volume, side, instrument]
    greeks_df : optional, columns [time, delta, gamma, vega, theta, iv, underlying_mid]
    """
    ticks = ticks_df.copy().sort_values('time').reset_index(drop=True)
    trades = trades_df.copy().sort_values('time').reset_index(drop=True)

    mid = (ticks['bid_price'] + ticks['ask_price']) / 2
    spread = ticks['ask_price'] - ticks['bid_price']

    ticks['spread_bps'] = np.where(mid > 0, spread / mid * 1e4, np.nan)

    bv = pd.to_numeric(ticks.get('bid_volume', 0), errors='coerce').fillna(0)
    av = pd.to_numeric(ticks.get('ask_volume', 0), errors='coerce').fillna(0)
    total_ba = bv + av
    ticks['bid_ask_imbalance'] = np.where(total_ba > 0, (bv - av) / total_ba, 0.0)

    # OFI — resample to 1-min buckets then forward-fill onto tick timestamps
    ofi_df = enhanced_order_flow_imbalance(trades[['time', 'side', 'volume']], window='1min')
    if not ofi_df.empty and 'imbalance' in ofi_df.columns:
        # OFI result may have time as index or column
        if 'time' in ofi_df.columns:
            ofi_series = ofi_df.set_index('time')['imbalance'].rename('ofi_imbalance')
        else:
            ofi_series = ofi_df['imbalance'].rename('ofi_imbalance')
        ticks = ticks.set_index('time')
        ticks = ticks.join(ofi_series, how='left')
        ticks['ofi_imbalance'] = ticks['ofi_imbalance'].ffill().fillna(0.0)
        ticks = ticks.reset_index()
    else:
        ticks['ofi_imbalance'] = 0.0

    # VWAP deviation
    vol = pd.to_numeric(trades['volume'], errors='coerce').fillna(0)
    price = pd.to_numeric(trades['price'], errors='coerce').fillna(0)
    total_vol = vol.sum()
    vwap = (price * vol).sum() / total_vol if total_vol > 0 else mid.mean()
    ticks['vwap_deviation'] = np.where(vwap > 0, (mid - vwap) / vwap, 0.0)

    # Volume surge ratio (rolling 10-tick window on cumulative volume diff)
    if 'total_volume' in ticks.columns:
        tv = pd.to_numeric(ticks['total_volume'], errors='coerce').ffill().fillna(0)
        vol_delta = tv.diff().clip(lower=0).fillna(0)
        roll_mean = vol_delta.rolling(10, min_periods=1).mean().replace(0, np.nan)
        ticks['vol_surge_ratio'] = (vol_delta / roll_mean).fillna(1.0)
    else:
        ticks['vol_surge_ratio'] = 1.0

    # Price momentum
    ticks['price_momentum_5']  = mid.pct_change(5).fillna(0.0)
    ticks['price_momentum_20'] = mid.pct_change(20).fillna(0.0)

    # Greeks — merge on nearest timestamp if provided
    for col in ['delta', 'gamma', 'vega', 'theta', 'iv', 'underlying_mid']:
        ticks[col] = np.nan

    if greeks_df is not None and not greeks_df.empty:
        g = greeks_df.copy().sort_values('time')
        ticks = pd.merge_asof(
            ticks.sort_values('time'), g[['time', 'delta', 'gamma', 'vega', 'theta', 'iv', 'underlying_mid']],
            on='time', direction='backward'
        )

    return ticks[['time'] + FEATURE_COLS].set_index('time')


if __name__ == '__main__':
    from finance.HFT.backtest.db.load_data import load_order_data, load_tick_data
    ticks  = load_tick_data('2025-10-02')
    trades = load_order_data('2025-10-02')
    feat   = extract_features(ticks, trades)
    print(feat.shape)
    print(feat.head())
    print(feat.describe())
