"""
Gymnasium TradingEnv for GGAL options (leveraged).

Observation : OPTIONS_FEATURE_COLS vector (float32, shape=(13,))
Action      : Discrete(4) — 0=HOLD, 1=BUY_CALL, 2=BUY_PUT, 3=CLOSE
Reward      : option P&L × CONTRACT (100 shares) − commission, per step
              Large negative reward on expiry with open position (theta risk)

Leverage is implicit: a 10% GGAL move → 50–200% option price move.
"""
import random
from datetime import date, timedelta

import numpy as np
import pandas as pd
import gymnasium as gym
from gymnasium import spaces
from sqlalchemy import text

from finance.utils.db_pool import get_pg_engine
from finance.HFT.ml.features_options import (
    extract_options_features, OPTIONS_FEATURE_COLS, CONTRACT
)
from finance.utils.logger import logger

COMMISSION = 0.0041
EXPIRY_PENALTY = -5.0
MIN_EXPIRY_DAYS = 3
N_FEATURES = len(OPTIONS_FEATURE_COLS)
DRAWDOWN_PENALTY_WEIGHT = 5.0


def _available_expiries() -> list[date]:
    with get_pg_engine().connect() as conn:
        rows = conn.execute(text(
            "SELECT DISTINCT expiry FROM ppi_options_chain WHERE underlying='GGAL' ORDER BY expiry"
        )).fetchall()
    return [r[0] for r in rows]


class OptionsEnv(gym.Env):
    metadata = {'render_modes': []}

    def __init__(self, initial_capital: float = 500_000):
        super().__init__()
        self.initial_capital = initial_capital
        self.observation_space = spaces.Box(-np.inf, np.inf, shape=(N_FEATURES,), dtype=np.float32)
        self.action_space = spaces.Discrete(4)  # HOLD, BUY_CALL, BUY_PUT, CLOSE

        self._expiries = _available_expiries()
        self._feat: pd.DataFrame | None = None
        self._rows: list[dict] = []
        self._idx: int = 0
        self._position: int = 0
        self._entry_price: float = 0.0
        self._entry_ticker: str = ''
        self._cash: float = initial_capital
        self._prev_value: float = initial_capital
        self._peak_value: float = initial_capital

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        if not self._expiries:
            return np.zeros(N_FEATURES, dtype=np.float32), {}

        expiry = random.choice(self._expiries)
        try:
            feat = extract_options_features(expiry)
            if feat.empty:
                raise ValueError("empty features")
        except Exception as e:
            logger.warning("OptionsEnv reset failed: {e}", e=e)
            return np.zeros(N_FEATURES, dtype=np.float32), {}

        self._feat = feat.fillna(0.0)
        self._rows = feat.reset_index().to_dict('records')
        self._idx = 0
        self._position = 0
        self._entry_price = 0.0
        self._cash = self.initial_capital
        self._prev_value = self.initial_capital
        self._peak_value = self.initial_capital
        return self._obs(), {}

    def step(self, action: int):
        if self._feat is None or self._idx >= len(self._rows):
            return np.zeros(N_FEATURES, dtype=np.float32), 0.0, True, False, {}

        row = self._rows[self._idx]
        tte = row.get('time_to_expiry_days', 0)
        market = row.get('market', 0.0)
        reward = 0.0

        # Force-close near expiry
        if tte < MIN_EXPIRY_DAYS and self._position != 0:
            pnl = (market - self._entry_price) * self._position * CONTRACT
            pnl -= (self._entry_price + market) * CONTRACT * COMMISSION
            self._cash += pnl
            reward = float(np.clip(pnl / self.initial_capital, -1, 1)) + EXPIRY_PENALTY
            self._position = 0
            self._idx += 1
            return self._obs(), reward, True, False, {'portfolio_value': self._cash}

        # Execute action
        if action == 1 and self._position == 0:   # BUY_CALL
            if row.get('option_type') == 'C':
                self._position = 1
                self._entry_price = market
                self._entry_ticker = row.get('ticker', '')
                self._cash -= market * CONTRACT * (1 + COMMISSION)

        elif action == 2 and self._position == 0:  # BUY_PUT
            if row.get('option_type') == 'P':
                self._position = -1
                self._entry_price = market
                self._entry_ticker = row.get('ticker', '')
                self._cash -= market * CONTRACT * (1 + COMMISSION)

        elif action == 3 and self._position != 0:  # CLOSE
            pnl = (market - self._entry_price) * self._position * CONTRACT
            pnl -= (self._entry_price + market) * CONTRACT * COMMISSION
            self._cash += pnl + self._entry_price * CONTRACT
            reward = float(np.clip(pnl / self.initial_capital, -1, 1))
            self._position = 0

        # Mark-to-market
        mtm = self._cash
        if self._position != 0:
            mtm += market * abs(self._position) * CONTRACT

        # High watermark + drawdown penalty
        if mtm > self._peak_value:
            self._peak_value = mtm
        drawdown_pct = (self._peak_value - mtm) / self._peak_value if self._peak_value > 0 else 0.0

        raw_reward = float(np.clip((mtm - self._prev_value) / self.initial_capital, -0.5, 0.5))
        drawdown_penalty = DRAWDOWN_PENALTY_WEIGHT * (drawdown_pct ** 1.5)
        reward += raw_reward - drawdown_penalty
        self._prev_value = mtm

        self._idx += 1
        done = self._idx >= len(self._rows)
        return self._obs(), reward, done, False, {'portfolio_value': mtm, 'drawdown': drawdown_pct}

    def _obs(self) -> np.ndarray:
        if self._feat is None or self._idx >= len(self._rows):
            return np.zeros(N_FEATURES, dtype=np.float32)
        row = self._rows[min(self._idx, len(self._rows) - 1)]
        obs = np.array([row.get(f, 0.0) for f in OPTIONS_FEATURE_COLS], dtype=np.float32)
        obs = np.nan_to_num(obs, nan=0.0, posinf=0.0, neginf=0.0)
        return obs
