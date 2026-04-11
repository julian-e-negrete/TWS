"""
Gymnasium TradingEnv for Binance margin (leveraged spot simulation).

Observation : CRYPTO_FEATURE_COLS vector (float32, shape=(11,))
Action      : Discrete(3) — 0=HOLD, 1=LONG, 2=SHORT
Reward      : P&L × leverage − funding_cost, clipped to [-1, 1]
              Margin call if unrealized loss > 80% of margin → liquidation + large penalty

Leverage: configurable (default 3x). Applied to P&L only — no actual borrowing simulation.
Episode: 7 days of 1-min bars.
Note: ofi/tick_volume/spread_proxy are 0.0 in backtest mode (no tick data in DB).
      They are populated with real values when running via live_runner.py.
"""
import random
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import gymnasium as gym
from gymnasium import spaces

from finance.HFT.ml.features_crypto import extract_crypto_features, CRYPTO_FEATURE_COLS
from finance.HFT.ml import get_config
from finance.utils.logger import logger

N_FEATURES = len(CRYPTO_FEATURE_COLS)
COMMISSION  = 0.001
FUNDING_INTERVAL = 480
MARGIN_CALL_THRESHOLD = 0.80
LIQUIDATION_PENALTY   = -2.0
INACTIVITY_PENALTY    = -0.0002  # per step when holding — prevents degenerate hold policy
DRAWDOWN_PENALTY_WEIGHT = 0.5   # reduced from 5.0 — was dominating reward signal


class CryptoMarginEnv(gym.Env):
    metadata = {'render_modes': []}

    def __init__(self, symbol: str = 'BTCUSDT', leverage: int = 3,
                 initial_capital: float = 10_000):
        super().__init__()
        self.symbol = symbol
        self.leverage = leverage
        self.initial_capital = initial_capital
        self.observation_space = spaces.Box(-np.inf, np.inf, shape=(N_FEATURES,), dtype=np.float32)
        self.action_space = spaces.Discrete(3)

        self._feat: pd.DataFrame | None = None
        self._idx: int = 0
        self._position: int = 0
        self._entry_price: float = 0.0
        self._cash: float = initial_capital
        self._prev_value: float = initial_capital
        self._peak_value: float = initial_capital
        self._bars_since_funding: int = 0

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        try:
            feat = extract_crypto_features(self.symbol, hours_back=168)
            if feat.empty:
                raise ValueError("empty")
        except Exception as e:
            logger.warning("CryptoMarginEnv reset failed: {e}", e=e)
            return np.zeros(N_FEATURES, dtype=np.float32), {}

        # Random 1-day window (#255: shorter episodes for better credit assignment)
        n = len(feat)
        episode_len = 60 * 24  # 1 day of 1-min bars
        if n > episode_len:
            start = random.randint(0, n - episode_len)
            feat = feat.iloc[start:start + episode_len]

        self._feat = feat.fillna(0.0)
        self._idx = 0
        self._position = 0
        self._entry_price = 0.0
        self._cash = self.initial_capital
        self._prev_value = self.initial_capital
        self._peak_value = self.initial_capital
        self._bars_since_funding = 0
        self._prev_value = self.initial_capital
        self._bars_since_funding = 0
        return self._obs(), {}

    def step(self, action: int):
        if self._feat is None or self._idx >= len(self._feat):
            return np.zeros(N_FEATURES, dtype=np.float32), 0.0, True, False, {}

        row = self._feat.iloc[self._idx]
        # Use price_momentum_5 as the per-step return (features are normalized, no raw price needed)
        step_return = float(row.get('price_momentum_5', 0.0))
        reward = 0.0

        # Margin call: cumulative unrealized loss > threshold
        if self._position != 0:
            unreal = step_return * self._position * self.leverage
            if unreal < -MARGIN_CALL_THRESHOLD:
                self._cash *= (1 - MARGIN_CALL_THRESHOLD)
                self._position = 0
                self._idx += 1
                return self._obs(), LIQUIDATION_PENALTY, True, False, {'portfolio_value': self._cash}

        # Execute action
        if action == 1 and self._position == 0:    # LONG
            self._position = 1
            self._cash -= self._cash * COMMISSION
        elif action == 2 and self._position == 0:  # SHORT
            self._position = -1
            self._cash -= self._cash * COMMISSION
        elif (action == 1 and self._position == -1) or (action == 2 and self._position == 1):
            # Close + reverse
            pnl = step_return * self._position * self.leverage
            self._cash *= (1 + pnl - COMMISSION)
            reward = float(np.clip(pnl, -1, 1))
            self._position = 0

        # Funding cost every 8h
        self._bars_since_funding += 1
        if self._bars_since_funding >= FUNDING_INTERVAL and self._position != 0:
            funding = abs(float(row.get('funding_rate_proxy', 0.0))) * 0.01
            self._cash *= (1 - funding)
            self._bars_since_funding = 0

        # Mark-to-market reward
        if self._position != 0:
            mtm = self._cash * (1 + step_return * self._position * self.leverage)
        else:
            mtm = self._cash

        # High watermark + drawdown penalty
        if mtm > self._peak_value:
            self._peak_value = mtm
        drawdown_pct = (self._peak_value - mtm) / self._peak_value if self._peak_value > 0 else 0.0

        # Reward: realized P&L pct (no clipping) + transaction cost on position change (#251)
        pnl_pct = (mtm - self._prev_value) / self.initial_capital
        reward += float(pnl_pct)
        self._prev_value = mtm

        self._idx += 1
        done = self._idx >= len(self._feat)
        return self._obs(), reward, done, False, {
            'portfolio_value': mtm, 'leverage': self.leverage, 'drawdown': drawdown_pct
        }

    def _obs(self) -> np.ndarray:
        if self._feat is None or self._idx >= len(self._feat):
            return np.zeros(N_FEATURES, dtype=np.float32)
        obs = self._feat.iloc[min(self._idx, len(self._feat) - 1)].values.astype(np.float32)
        return np.nan_to_num(obs, nan=0.0, posinf=0.0, neginf=0.0)
