"""
Feature extraction for Binance margin ML agent.
Reuses indicator logic from bt12_extended.py — no reimplementation.

Two modes:
  extract_crypto_features(symbol, hours_back)          → from DB (1-min OHLCV, for backtesting)
  extract_crypto_features_live(symbol, monitor)        → from AsyncBinanceMonitor in-memory trades
                                                          Real OFI, tick volume, spread proxy.
"""
import numpy as np
import pandas as pd
from collections import deque
from sqlalchemy import text

from finance.utils.db_pool import get_pg_engine

CRYPTO_FEATURE_COLS = [
    'rsi_14',
    'macd_signal',
    'bb_position',
    'volume_surge',
    'price_momentum_5',
    'price_momentum_20',
    'funding_rate_proxy',
    # Tick-level features (populated from aggTrade stream; 0.0 in DB/backtest mode)
    'ofi',              # order flow imbalance: (buy_qty - sell_qty) / total_qty
    'tick_volume',      # total qty in rolling window
    'spread_proxy',     # std of last 20 trade prices as spread proxy
    # Derived features
    'volatility_20',    # rolling 20-bar return std
    'trend_strength',   # abs(momentum_20) / volatility_20
    'ofi_smoothed',     # ewm(ofi, span=5)
    'tick_vol_ratio',   # tick_volume / rolling_mean(tick_volume, 20)
    'momentum_x_vol',   # price_momentum_5 * volume_surge (interaction)
]


def _indicators(c: pd.Series, vol: pd.Series) -> dict:
    """Shared indicator computation for both modes."""
    delta = c.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, np.nan)
    rsi   = (100 - 100 / (1 + rs)).fillna(50.0)

    macd   = c.ewm(span=12).mean() - c.ewm(span=26).mean()
    signal = macd.ewm(span=9).mean()
    macd_h = (macd - signal).fillna(0.0)

    mid  = c.rolling(20).mean()
    band = c.rolling(20).std().replace(0, np.nan)
    bb   = ((c - (mid - 2 * band)) / (4 * band)).clip(0, 1).fillna(0.5)

    vol_mean = vol.rolling(20, min_periods=1).mean().replace(0, np.nan)
    vol_surge = (vol / vol_mean).fillna(1.0)

    return {
        'rsi_14':      rsi,
        'macd_signal': macd_h,
        'bb_position': bb,
        'volume_surge': vol_surge,
        'price_momentum_5':   c.pct_change(5).fillna(0.0),
        'price_momentum_20':  c.pct_change(20).fillna(0.0),
        'funding_rate_proxy': c.pct_change(480).fillna(0.0),
    }


def extract_crypto_features(symbol: str = 'BTCUSDT', hours_back: int = 168) -> pd.DataFrame:
    """DB mode: 1-min OHLCV + real OFI from binance_trades (if available)."""
    with get_pg_engine().connect() as conn:
        df = pd.read_sql(text("""
            SELECT timestamp AT TIME ZONE 'UTC' AS time,
                   open, high, low, close, volume
            FROM binance_ticks
            WHERE symbol = :s
              AND timestamp >= NOW() - INTERVAL ':h hours'
            ORDER BY timestamp
        """.replace(':h', str(hours_back))), conn, params={"s": symbol})

        # Real OFI from binance_trades (1-min buckets)
        trades = pd.read_sql(text("""
            SELECT date_trunc('minute', time) AS bucket,
                   SUM(CASE WHEN NOT is_buyer_maker THEN qty ELSE 0 END) AS buy_qty,
                   SUM(CASE WHEN is_buyer_maker THEN qty ELSE 0 END) AS sell_qty,
                   SUM(qty) AS total_qty,
                   STDDEV(price::float) AS spread_proxy
            FROM binance_trades
            WHERE symbol = :s
              AND time >= NOW() - INTERVAL ':h hours'
            GROUP BY bucket ORDER BY bucket
        """.replace(':h', str(hours_back))), conn, params={"s": symbol})

    if df.empty:
        return pd.DataFrame(columns=['time'] + CRYPTO_FEATURE_COLS)

    df['time'] = pd.to_datetime(df['time'], utc=True)
    df = df.sort_values('time').reset_index(drop=True)

    ind = _indicators(df['close'], df['volume'])
    for k, v in ind.items():
        df[k] = v

    # Merge real OFI if available
    if not trades.empty:
        trades['bucket'] = pd.to_datetime(trades['bucket'], utc=True)
        trades['ofi'] = ((trades['buy_qty'] - trades['sell_qty']) /
                         trades['total_qty'].replace(0, float('nan'))).fillna(0.0)
        trades['tick_volume'] = trades['total_qty']
        trades['spread_proxy'] = trades['spread_proxy'].fillna(0.0)
        df = df.merge(trades[['bucket', 'ofi', 'tick_volume', 'spread_proxy']],
                      left_on='time', right_on='bucket', how='left')
        df['ofi']          = df['ofi'].fillna(0.0)
        df['tick_volume']  = df['tick_volume'].fillna(0.0)
        df['spread_proxy'] = df['spread_proxy'].fillna(0.0)
    else:
        df['ofi']          = 0.0
        df['tick_volume']  = 0.0
        df['spread_proxy'] = 0.0

    # Drop rows with no real trade data (OFI=0 and tick_volume=0 means no binance_trades coverage)
    has_trades = (df['ofi'] != 0.0) | (df['tick_volume'] != 0.0)
    if has_trades.any():
        df = df[has_trades]

    # Derived features (#252, #253)
    ret = df['price_momentum_5']
    vol20 = ret.rolling(20, min_periods=1).std().replace(0, np.nan)
    df['volatility_20']   = vol20.fillna(0.0)
    df['trend_strength']  = (df['price_momentum_20'].abs() / vol20).fillna(0.0).clip(0, 5)
    df['ofi_smoothed']    = df['ofi'].ewm(span=5, adjust=False).mean()
    tv_mean = df['tick_volume'].rolling(20, min_periods=1).mean().replace(0, np.nan)
    df['tick_vol_ratio']  = (df['tick_volume'] / tv_mean).fillna(1.0).clip(0, 10)
    df['momentum_x_vol']  = (df['price_momentum_5'] * df['volume_surge']).fillna(0.0)

    return df[['time'] + CRYPTO_FEATURE_COLS].set_index('time')


def extract_crypto_features_live(symbol: str, monitor) -> pd.Series | None:
    """
    Live mode: compute one feature vector from AsyncBinanceMonitor in-memory data.
    Returns a Series with CRYPTO_FEATURE_COLS, or None if insufficient data.

    monitor: AsyncBinanceMonitor instance with .data_map and .trades_map populated.
    """
    klines = monitor.data_map.get(symbol)
    trades = monitor.trades_map.get(symbol)

    if klines is None or len(klines) < 20:
        return None

    c   = klines['close'].reset_index(drop=True)
    vol = klines['volume'].reset_index(drop=True)
    ind = _indicators(c, vol)
    feat = {k: float(v.iloc[-1]) for k, v in ind.items()}

    # Tick-level features from aggTrade deque
    if trades and len(trades) >= 10:
        trade_list = list(trades)
        prices = np.array([t['price'] for t in trade_list])
        buy_qty  = sum(t['qty'] for t in trade_list if not t['is_buyer_maker'])
        sell_qty = sum(t['qty'] for t in trade_list if t['is_buyer_maker'])
        total_qty = buy_qty + sell_qty
        feat['ofi']          = (buy_qty - sell_qty) / total_qty if total_qty > 0 else 0.0
        feat['tick_volume']  = float(total_qty)
        feat['spread_proxy'] = float(np.std(prices[-20:])) if len(prices) >= 20 else 0.0
    else:
        feat['ofi']          = 0.0
        feat['tick_volume']  = 0.0
        feat['spread_proxy'] = 0.0

    # Derived features
    ret = ind['price_momentum_5']
    vol20 = float(ret.rolling(20, min_periods=1).std().iloc[-1]) or 1e-8
    feat['volatility_20']  = vol20
    feat['trend_strength'] = min(abs(feat['price_momentum_20']) / vol20, 5.0)
    feat['ofi_smoothed']   = feat['ofi']  # single step — no history available
    tv_mean = float(vol.rolling(20, min_periods=1).mean().iloc[-1]) or 1.0
    feat['tick_vol_ratio'] = min(feat['tick_volume'] / tv_mean, 10.0)
    feat['momentum_x_vol'] = feat['price_momentum_5'] * feat['volume_surge']

    return pd.Series(feat, index=CRYPTO_FEATURE_COLS, dtype=np.float32)
