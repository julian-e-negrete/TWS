"""
Gymnasium TradingEnv for CCL spread (AL30D/AL30 synthetic DLR proxy).

Action      : Discrete(3) — 0=HOLD, 1=BUY_CCL (buy AL30D, sell AL30), 2=SELL_CCL
Reward      : CCL P&L in ARS per unit, clipped to [-1, 1]
Leverage    : implicit — 1 AL30D unit ≈ USD 61 ≈ ARS 85k (much lower than 1.5M futures)

Episode     : one trading day of AL30/AL30D ticks.
"""
import random
import numpy as np
import pandas as pd
import gymnasium as gym
from gymnasium import spaces

from finance.HFT.ml.features_ccl import extract_ccl_features, CCL_FEATURE_COLS
from finance.utils.logger import logger

N_FEATURES  = len(CCL_FEATURE_COLS)
COMMISSION  = 0.0005
MIN_TICKS   = 20_000
DRAWDOWN_PENALTY_WEIGHT = 2.0  # softer than crypto/options — CCL moves are smaller

def _good_dates() -> list[tuple[str, str]]:
    """Return (date_from, date_to) windows of 30 days each with complete data."""
    try:
        from sqlalchemy import text
        from finance.utils.db_pool import get_pg_engine
        import datetime
        with get_pg_engine().connect() as conn:
            rows = conn.execute(text("""
                SELECT (time AT TIME ZONE 'America/Argentina/Buenos_Aires')::date as day
                FROM ticks
                WHERE instrument = 'M:bm_MERV_AL30_24hs'
                  AND time >= NOW() - INTERVAL '180 days'
                GROUP BY day HAVING COUNT(*) >= :min_ticks
                ORDER BY day
            """), {"min_ticks": MIN_TICKS}).fetchall()
        good_days = [r[0] for r in rows]
        if not good_days:
            raise ValueError("no good days")
        # Build 30-day sliding windows
        windows = []
        for i in range(0, len(good_days) - 20, 5):
            d_from = str(good_days[i])
            d_to   = str(good_days[min(i + 30, len(good_days) - 1)])
            windows.append((d_from, d_to))
        return windows
    except Exception:
        import datetime
        return [('2025-09-01', '2025-09-30'), ('2025-10-01', '2025-10-31'),
                ('2025-11-01', '2025-11-30'), ('2025-12-01', '2025-12-31'),
                ('2026-01-01', '2026-01-31'), ('2026-02-01', '2026-02-28'),
                ('2026-03-01', '2026-03-28')]


_FEAT_CACHE: list[pd.DataFrame] = []  # preloaded at first init, shared across all envs


def _preload_features() -> list[pd.DataFrame]:
    """Load all CCL feature windows once at startup. Cached globally."""
    global _FEAT_CACHE
    if _FEAT_CACHE:
        return _FEAT_CACHE
    dates = _good_dates()
    logger.info("Preloading CCL features for {n} windows...", n=len(dates))
    for d_from, d_to in dates:
        try:
            feat = extract_ccl_features(d_from, d_to).fillna(0.0)
            if len(feat) >= 5:
                _FEAT_CACHE.append(feat)
        except Exception:
            pass
    logger.info("CCL feature cache: {n} windows loaded", n=len(_FEAT_CACHE))
    return _FEAT_CACHE


class CCLEnv(gym.Env):
    metadata = {'render_modes': []}

    def __init__(self, initial_capital: float = 100_000):
        super().__init__()
        self.initial_capital = initial_capital
        self._cache = _preload_features()  # DB hit only once per process
        self.observation_space = spaces.Box(-np.inf, np.inf, shape=(N_FEATURES,), dtype=np.float32)
        self.action_space = spaces.Discrete(3)

        self._feat: pd.DataFrame | None = None
        self._idx: int = 0
        self._position: int = 0
        self._entry_ccl: float = 0.0
        self._cash: float = initial_capital
        self._prev_value: float = initial_capital
        self._peak_value: float = initial_capital

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        if not self._cache:
            return np.zeros(N_FEATURES, dtype=np.float32), {}
        self._feat = random.choice(self._cache)
        self._idx = 0
        self._position = 0
        self._entry_ccl = 0.0
        self._cash = self.initial_capital
        self._prev_value = self.initial_capital
        self._peak_value = self.initial_capital
        return self._obs(), {}

    def step(self, action: int):
        if self._feat is None or self._idx >= len(self._feat):
            return np.zeros(N_FEATURES, dtype=np.float32), 0.0, True, False, {}

        row   = self._feat.iloc[self._idx]
        ccl   = float(row['ccl'])
        reward = 0.0

        if action == 1 and self._position == 0:    # BUY CCL
            self._position  = 1
            self._entry_ccl = ccl * (1 + COMMISSION)
        elif action == 2 and self._position == 0:  # SELL CCL
            self._position  = -1
            self._entry_ccl = ccl * (1 - COMMISSION)
        elif action == 0 and self._position != 0:  # HOLD → keep (close on direction flip)
            pass

        # Close on direction change
        if (action == 1 and self._position == -1) or (action == 2 and self._position == 1):
            pnl = (ccl - self._entry_ccl) * self._position
            self._cash += pnl
            reward = float(np.clip(pnl / self.initial_capital * 100, -1, 1))
            self._position = 0

        # Mark-to-market
        mtm = self._cash
        if self._position != 0 and self._entry_ccl > 0:
            mtm += (ccl - self._entry_ccl) * self._position

        # High watermark + drawdown penalty
        if mtm > self._peak_value:
            self._peak_value = mtm
        drawdown_pct = (self._peak_value - mtm) / self._peak_value if self._peak_value > 0 else 0.0

        raw_reward = float(np.clip((mtm - self._prev_value) / self.initial_capital, -0.5, 0.5))
        drawdown_penalty = DRAWDOWN_PENALTY_WEIGHT * (drawdown_pct ** 1.5)
        reward += raw_reward - drawdown_penalty
        self._prev_value = mtm

        self._idx += 1
        done = self._idx >= len(self._feat)
        return self._obs(), reward, done, False, {'portfolio_value': mtm, 'ccl': ccl, 'drawdown': drawdown_pct}

    def _obs(self) -> np.ndarray:
        if self._feat is None or self._idx >= len(self._feat):
            return np.zeros(N_FEATURES, dtype=np.float32)
        return self._feat.iloc[min(self._idx, len(self._feat)-1)].values.astype(np.float32)
