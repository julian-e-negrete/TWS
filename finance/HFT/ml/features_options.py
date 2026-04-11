"""
Feature extraction for GGAL options ML agent.
Reuses BS helpers from options_backtest.py — no reimplementation.

extract_options_features(expiry, date_from, date_to) -> pd.DataFrame
  One row per (ticker, date). Index = (ticker, date).
"""
import numpy as np
import pandas as pd
from datetime import date
from sqlalchemy import text

from finance.utils.db_pool import get_pg_engine
from finance.HFT.backtest.options_backtest import _bs, _iv, RISK_FREE, CONTRACT

OPTIONS_FEATURE_COLS = [
    'delta', 'gamma', 'vega', 'theta', 'iv',
    'moneyness',           # S / K
    'time_to_expiry_days',
    'iv_vs_hist_vol',      # IV − 30d realized vol of GGAL
    'bid_ask_imbalance',   # from ticks if available, else 0
    'spread_bps',
    'underlying_momentum_5',
    'underlying_momentum_20',
    'mispricing_pct',      # (market − BS) / BS × 100
]

STRIKE_DIVISOR = 10.0


def _greeks(S, K, T, r, sigma, opt_type):
    """Returns (delta, gamma, vega, theta) via finite differences."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return (np.nan,) * 4
    h = 0.01
    p0  = _bs(S, K, T, r, sigma, opt_type)
    p_u = _bs(S * (1 + h), K, T, r, sigma, opt_type)
    p_d = _bs(S * (1 - h), K, T, r, sigma, opt_type)
    p_t = _bs(S, K, max(T - 1/365, 1e-6), r, sigma, opt_type)
    delta = (p_u - p_d) / (2 * S * h)
    gamma = (p_u - 2 * p0 + p_d) / (S * h) ** 2
    vega  = (_bs(S, K, T, r, sigma + h, opt_type) - p0) / h
    theta = (p_t - p0) * 365
    return delta, gamma, vega, theta


def extract_options_features(
    expiry: date,
    date_from: date | None = None,
    date_to: date | None = None,
) -> pd.DataFrame:
    engine = get_pg_engine()
    with engine.connect() as conn:
        opts = pd.read_sql(text("""
            SELECT ticker, option_type, strike, expiry, date, close, volume
            FROM ppi_options_chain
            WHERE underlying='GGAL' AND expiry=:exp AND close IS NOT NULL AND volume > 0
              AND (:d_from IS NULL OR date >= :d_from)
              AND (:d_to   IS NULL OR date <= :d_to)
            ORDER BY ticker, date
        """), conn, params={"exp": expiry, "d_from": date_from, "d_to": date_to})

        spot_df = pd.read_sql(text(
            "SELECT date, close AS spot FROM ppi_ohlcv WHERE ticker='GGAL' ORDER BY date"
        ), conn)

    if opts.empty or spot_df.empty:
        return pd.DataFrame(columns=['ticker', 'date'] + OPTIONS_FEATURE_COLS)

    opts['date']     = pd.to_datetime(opts['date']).dt.date
    spot_df['date']  = pd.to_datetime(spot_df['date']).dt.date
    spot_map         = dict(zip(spot_df['date'], spot_df['spot']))

    # 30-day realized vol of GGAL
    spot_df = spot_df.sort_values('date')
    spot_df['ret']      = spot_df['spot'].pct_change()
    spot_df['hist_vol'] = spot_df['ret'].rolling(30).std() * np.sqrt(252)
    hist_vol_map        = dict(zip(spot_df['date'], spot_df['hist_vol']))

    # Spot momentum
    spot_df['mom5']  = spot_df['spot'].pct_change(5)
    spot_df['mom20'] = spot_df['spot'].pct_change(20)
    mom5_map  = dict(zip(spot_df['date'], spot_df['mom5']))
    mom20_map = dict(zip(spot_df['date'], spot_df['mom20']))

    # IV per ticker per day (no look-ahead: use prev-day median)
    iv_map: dict[str, dict] = {}
    for ticker, grp in opts.groupby('ticker'):
        for _, row in grp.sort_values('date').iterrows():
            S = spot_map.get(row['date'])
            if S is None:
                continue
            K = row['strike'] / STRIKE_DIVISOR
            T = (expiry - row['date']).days / 365.0
            iv = _iv(S, K, T, RISK_FREE, row['close'], row['option_type'])
            if not np.isnan(iv):
                iv_map.setdefault(ticker, {})[row['date']] = iv

    rows = []
    for ticker, grp in opts.groupby('ticker'):
        ticker_ivs  = iv_map.get(ticker, {})
        dates_sorted = sorted(ticker_ivs)
        for _, row in grp.sort_values('date').iterrows():
            S = spot_map.get(row['date'])
            if S is None:
                continue
            K = row['strike'] / STRIKE_DIVISOR
            if not (S * 0.5 <= K <= S * 2.0):
                continue
            T = (expiry - row['date']).days / 365.0
            if T <= 0:
                continue

            prev_ivs = [ticker_ivs[d] for d in dates_sorted if d < row['date']]
            sigma = float(np.median(prev_ivs)) if prev_ivs else 0.3
            bs_price = _bs(S, K, T, RISK_FREE, sigma, row['option_type'])
            if np.isnan(bs_price) or bs_price <= 0:
                continue

            delta, gamma, vega, theta = _greeks(S, K, T, RISK_FREE, sigma, row['option_type'])
            hist_vol = hist_vol_map.get(row['date'], sigma)
            mispricing = (row['close'] - bs_price) / bs_price * 100

            rows.append({
                'ticker': ticker,
                'date':   row['date'],
                'option_type': row['option_type'],
                'strike': K,
                'spot':   S,
                'market': row['close'],
                'bs':     bs_price,
                'delta':              delta,
                'gamma':              gamma,
                'vega':               vega,
                'theta':              theta,
                'iv':                 sigma,
                'moneyness':          S / K,
                'time_to_expiry_days': T * 365,
                'iv_vs_hist_vol':     sigma - (hist_vol or sigma),
                'bid_ask_imbalance':  0.0,   # daily OHLCV has no bid/ask
                'spread_bps':         0.0,
                'underlying_momentum_5':  mom5_map.get(row['date'], 0.0) or 0.0,
                'underlying_momentum_20': mom20_map.get(row['date'], 0.0) or 0.0,
                'mispricing_pct':     mispricing,
            })

    return pd.DataFrame(rows).set_index(['ticker', 'date'])
