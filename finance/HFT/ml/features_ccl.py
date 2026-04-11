"""
CCL (Contado con Liquidación) feature extraction.

CCL = AL30_ARS / AL30D_USD — implicit USD/ARS FX rate.
Trading the CCL spread is equivalent to DLR futures exposure
with ~$5k ARS entry (vs 1.5M for futures).

extract_ccl_features(date_from, date_to) -> pd.DataFrame
  One row per second (joined AL30 + AL30D ticks).
  Index = UTC timestamp.
"""
import numpy as np
import pandas as pd
from sqlalchemy import text
from finance.utils.db_pool import get_pg_engine
from finance.HFT.dashboard.calcultions import enhanced_order_flow_imbalance

CCL_FEATURE_COLS = [
    'ccl',                  # AL30_ARS / AL30D_USD — the implicit FX rate
    'ccl_momentum_5',       # % change over last 5 ticks
    'ccl_momentum_20',
    'ccl_vs_mean_20',       # deviation from 20-tick rolling mean (mean reversion signal)
    'ccl_spread_bps',       # (ccl_ask - ccl_bid) / ccl * 1e4
    'al30_ofi',             # OFI of AL30 (ARS leg)
    'al30d_ofi',            # OFI of AL30D (USD leg)
    'al30_bid_ask_imb',     # bid/ask volume imbalance of AL30
    'al30d_bid_ask_imb',
    'vol_surge',            # AL30 volume surge ratio
]


def _load_pair(date_from: str, date_to: str) -> pd.DataFrame:
    """Load AL30 and AL30D ticks, join on second, compute CCL."""
    with get_pg_engine().connect() as conn:
        al30 = pd.read_sql(text("""
            SELECT time AT TIME ZONE 'UTC' AS time,
                   bid_price, ask_price, bid_volume, ask_volume, total_volume
            FROM ticks
            WHERE instrument = 'M:bm_MERV_AL30_24hs'
              AND time >= :d_from AND time <= :d_to
              AND bid_price > 0 AND ask_price > 0
            ORDER BY time
        """), conn, params={"d_from": date_from, "d_to": date_to})

        al30d = pd.read_sql(text("""
            SELECT time AT TIME ZONE 'UTC' AS time,
                   bid_price, ask_price, bid_volume, ask_volume
            FROM ticks
            WHERE instrument = 'M:bm_MERV_AL30D_24hs'
              AND time >= :d_from AND time <= :d_to
              AND bid_price > 0 AND ask_price > 0
            ORDER BY time
        """), conn, params={"d_from": date_from, "d_to": date_to})

    for df in [al30, al30d]:
        df['time'] = pd.to_datetime(df['time'], utc=True)
        df['second'] = df['time'].dt.floor('s')

    # Aggregate to 30-minute buckets — 5-min CCL moves (~0.01-0.05%) are below 0.5% commission
    # 30-min bars give ~12 steps/day with moves of 0.1-0.3%, learnable above commission
    # Daily bars: one open + close per session day
    # Daily CCL moves 0.5-1.5% — well above 0.05% commission
    al30['second']  = al30['time'].dt.floor('1D')
    al30d['second'] = al30d['time'].dt.floor('1D')
    al30_s  = al30.drop(columns=['time']).groupby('second').agg(
        bid_price=('bid_price','last'), ask_price=('ask_price','last'),
        bid_volume=('bid_volume','sum'), ask_volume=('ask_volume','sum'),
        total_volume=('total_volume','max')
    ).reset_index()
    al30d_s = al30d.drop(columns=['time']).groupby('second').agg(
        bid_price=('bid_price','last'), ask_price=('ask_price','last'),
        bid_volume=('bid_volume','sum'), ask_volume=('ask_volume','sum')
    ).reset_index()

    merged = pd.merge(al30_s, al30d_s, on='second', suffixes=('_al30', '_al30d'))
    merged = merged.rename(columns={'second': 'time'})
    return merged


def extract_ccl_features(date_from: str, date_to: str) -> pd.DataFrame:
    df = _load_pair(date_from, date_to)
    if df.empty:
        return pd.DataFrame(columns=['time'] + CCL_FEATURE_COLS)

    # CCL = AL30_ARS_mid / AL30D_USD_mid
    al30_mid  = (df['bid_price_al30']  + df['ask_price_al30'])  / 2
    al30d_mid = (df['bid_price_al30d'] + df['ask_price_al30d']) / 2
    ccl       = al30_mid / al30d_mid

    # CCL bid/ask (worst case: buy AL30 at ask, sell AL30D at bid)
    ccl_bid = df['bid_price_al30'] / df['ask_price_al30d']
    ccl_ask = df['ask_price_al30'] / df['bid_price_al30d']

    df['ccl']             = ccl
    df['ccl_momentum_5']  = ccl.pct_change(5).fillna(0.0)
    df['ccl_momentum_20'] = ccl.pct_change(20).fillna(0.0)
    df['ccl_vs_mean_20']  = (ccl - ccl.rolling(20).mean()) / ccl.rolling(20).std().replace(0, np.nan)
    df['ccl_vs_mean_20']  = df['ccl_vs_mean_20'].fillna(0.0)
    df['ccl_spread_bps']  = ((ccl_ask - ccl_bid) / ccl * 1e4).fillna(0.0)

    # OFI for each leg (reuse existing function)
    def _ofi(bid, ask, bvol, avol):
        """Simple tick-level OFI: bid pressure - ask pressure."""
        bid_chg = bid.diff().fillna(0)
        ask_chg = ask.diff().fillna(0)
        buy_flow  = np.where(bid_chg >= 0, bvol, 0)
        sell_flow = np.where(ask_chg <= 0, avol, 0)
        total = buy_flow + sell_flow
        with np.errstate(divide='ignore', invalid='ignore'):
            ofi = np.where(total > 0, (buy_flow - sell_flow) / total, 0.0)
        return pd.Series(ofi, index=bid.index).rolling(10).mean().fillna(0.0)

    df['al30_ofi']  = _ofi(df['bid_price_al30'],  df['ask_price_al30'],
                           df['bid_volume_al30'],  df['ask_volume_al30'])
    df['al30d_ofi'] = _ofi(df['bid_price_al30d'], df['ask_price_al30d'],
                           df['bid_volume_al30d'], df['ask_volume_al30d'])

    bv30  = df['bid_volume_al30'].fillna(0)
    av30  = df['ask_volume_al30'].fillna(0)
    bv30d = df['bid_volume_al30d'].fillna(0)
    av30d = df['ask_volume_al30d'].fillna(0)

    df['al30_bid_ask_imb']  = ((bv30  - av30)  / (bv30  + av30).replace(0, np.nan)).fillna(0.0)
    df['al30d_bid_ask_imb'] = ((bv30d - av30d) / (bv30d + av30d).replace(0, np.nan)).fillna(0.0)

    tv = pd.to_numeric(df['total_volume_al30'] if 'total_volume_al30' in df.columns else pd.Series(0, index=df.index), errors='coerce').ffill().fillna(0)
    vol_delta = tv.diff().clip(lower=0).fillna(0)
    roll_mean = vol_delta.rolling(10, min_periods=1).mean().replace(0, np.nan)
    df['vol_surge'] = (vol_delta / roll_mean).fillna(1.0)

    return df[['time'] + CCL_FEATURE_COLS].set_index('time')


if __name__ == '__main__':
    feat = extract_ccl_features('2025-10-02', '2025-10-03')
    print(feat.shape)
    print(feat.describe())
    print(f"\nCCL range: {feat['ccl'].min():.2f} – {feat['ccl'].max():.2f}")
