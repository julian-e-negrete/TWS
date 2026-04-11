"""
Synthetic DLR futures data generator using Ornstein-Uhlenbeck process.

Parameters fitted from real DLR tick data (OCT25/SEP25/NOV25).
Generates unlimited synthetic trading days — no capital requirement,
no market hours constraint, no data sparsity.

Usage:
    from finance.HFT.ml.synthetic_dlr import generate_episode
    ticks_df, trades_df = generate_episode(n_ticks=8000)
"""
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta

# OU parameters fitted from real DLR data
_MU        = 1438.0   # long-run mean price (ARS)
_THETA     = 0.0002   # mean-reversion speed per tick
_SIGMA     = 0.00074  # volatility per tick (log-return std)
_SPREAD_MU = 2.3      # mean bid-ask spread (ARS)
_SPREAD_SD = 1.5      # spread std
_SPREAD_MIN = 0.5
_TICK_SIZE  = 0.5     # minimum price increment

# Realistic intraday drift: slight upward bias during session
_SESSION_TICKS = 8000  # ~typical ticks per trading day


def generate_episode(
    n_ticks: int = _SESSION_TICKS,
    mu: float = _MU,
    theta: float = _THETA,
    sigma: float = _SIGMA,
    seed: int | None = None,
    instrument: str = 'rx_DDF_DLR_SYNTH',
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns (ticks_df, trades_df) matching the schema expected by
    extract_features() and MarketDataBacktester.load_market_data().

    Price follows OU: dP = theta*(mu - P)*dt + sigma*P*dW
    Spread sampled from truncated normal.
    Volume per tick from log-normal fitted to real data.
    Trade direction inferred from price change sign.
    """
    rng = np.random.default_rng(seed)

    # Generate price path via OU
    prices = np.empty(n_ticks)
    prices[0] = mu * rng.uniform(0.95, 1.05)  # random start near mu
    for i in range(1, n_ticks):
        drift = theta * (mu - prices[i-1])
        shock = sigma * prices[i-1] * rng.standard_normal()
        prices[i] = max(prices[i-1] + drift + shock, 1.0)
        # Round to tick size
        prices[i] = round(prices[i] / _TICK_SIZE) * _TICK_SIZE

    # Spread: truncated normal, min 0.5
    raw_spread = rng.normal(_SPREAD_MU, _SPREAD_SD, n_ticks)
    spreads = np.clip(raw_spread, _SPREAD_MIN, _SPREAD_MU * 10)
    # Round spreads to tick size
    spreads = np.round(spreads / _TICK_SIZE) * _TICK_SIZE

    bid = prices - spreads / 2
    ask = prices + spreads / 2

    # Volume: log-normal (real mean ~20k, but in contracts: 1-5 per tick)
    volumes = rng.integers(1, 6, size=n_ticks)

    # Cumulative volume (matches total_volume schema)
    cum_volume = np.cumsum(volumes) * 1000  # scale to match real data units

    # Timestamps: synthetic session 13:00-17:00 ART = 16:00-20:00 UTC
    t0 = datetime(2026, 1, 2, 16, 0, 0, tzinfo=timezone.utc)
    session_seconds = 4 * 3600  # 4h session
    tick_interval = session_seconds / n_ticks
    timestamps = [t0 + timedelta(seconds=i * tick_interval) for i in range(n_ticks)]

    ticks_df = pd.DataFrame({
        'time':         timestamps,
        'instrument':   instrument,
        'bid_price':    bid,
        'ask_price':    ask,
        'last_price':   prices,
        'bid_volume':   volumes,
        'ask_volume':   volumes,
        'total_volume': cum_volume,
    })
    ticks_df['time'] = pd.to_datetime(ticks_df['time'], utc=True)

    # Trades: one per tick where price changed
    price_change = np.diff(prices, prepend=prices[0])
    side = np.where(price_change >= 0, 'B', 'S')

    trades_df = pd.DataFrame({
        'time':       timestamps,
        'price':      prices,
        'volume':     volumes.astype(float),
        'side':       side,
        'instrument': instrument,
    })
    trades_df['time'] = pd.to_datetime(trades_df['time'], utc=True)

    return ticks_df, trades_df


def generate_dataset(
    n_episodes: int = 100,
    n_ticks: int = _SESSION_TICKS,
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate multiple synthetic episodes concatenated — for supervised training."""
    all_ticks, all_trades = [], []
    for i in range(n_episodes):
        t, tr = generate_episode(n_ticks=n_ticks, seed=seed + i)
        all_ticks.append(t)
        all_trades.append(tr)
    return pd.concat(all_ticks, ignore_index=True), pd.concat(all_trades, ignore_index=True)


if __name__ == '__main__':
    ticks, trades = generate_episode(seed=0)
    print(f"ticks: {ticks.shape}, price range: {ticks['bid_price'].min():.1f}–{ticks['ask_price'].max():.1f}")
    print(f"trades: {trades.shape}, buy/sell: {(trades['side']=='B').sum()}/{(trades['side']=='S').sum()}")
    print(ticks.head(3))
