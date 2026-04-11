"""
Gymnasium TradingEnv wrapping MarketDataBacktester.

Observation : FEATURE_COLS vector (float32, shape=(len(FEATURE_COLS),))
Action      : Discrete(3)  — 0=HOLD, 1=BUY, 2=SELL
Reward      : realized P&L delta per step (ARS), clipped to [-1, 1] for stability

Usage:
    python -m finance.HFT.ml.env
"""
import random
from typing import Any

import numpy as np
import pandas as pd
import gymnasium as gym
from gymnasium import spaces

from finance.HFT.ml.features import extract_features, FEATURE_COLS
from finance.HFT.backtest.main import MarketDataBacktester
from finance.HFT.backtest.types import Direction, OrderType
from finance.HFT.backtest.db.load_data import load_order_data, load_tick_data
from finance.HFT.backtest.db.load_binance import load_binance_data
from finance.HFT.backtest.db.load_byma import load_byma_data
from finance.utils.logger import logger

AVAILABLE_DATES = {
    # DLR kept for reference but synthetic is preferred (see use_synthetic flag)
    "DLR": [f"2025-10-{d:02d}" for d in [2,3,6,7,8,9,13,14,15,16,17,20,21,22,23,24,27,28,29,30,31]]
          + [f"2025-09-{d:02d}" for d in [3,4,5,8,9,10,11,12,15,16,17,18,19,22,23,24,25,26,29,30]]
          + [f"2025-11-{d:02d}" for d in [3,4,5,6,7,10,11,12,13,14,17,18,19,20,21,24,25,26,27,28]],
    "BTCUSDT": [f"2025-10-{d:02d}" for d in [2,3,6,7,8,9,13,14,15,16,17,20,21,22,23,24,27,28,29,30,31]],
    "GGAL":    [f"2025-10-{d:02d}" for d in [2,3,6,7,8,9,13,14,15,16,17,20,21,22,23,24,27,28,29,30,31]],
}

N_FEATURES = len(FEATURE_COLS)
REWARD_SCALE = 1e-5


def _load_day(date: str, instrument_type: str):
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
    return ticks, trades


class TradingEnv(gym.Env):
    metadata = {'render_modes': []}

    def __init__(self, instrument_type: str = 'DLR', initial_capital: float = 2_000_000,
                 dates: list[str] | None = None, use_synthetic: bool | None = None):
        super().__init__()
        self.instrument_type = instrument_type
        self.initial_capital = initial_capital
        self.dates = dates or AVAILABLE_DATES.get(instrument_type, [])
        # DLR defaults to synthetic — real data is sparse and requires 1.5M ARS capital
        self.use_synthetic = use_synthetic if use_synthetic is not None else (instrument_type == 'DLR')

        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(N_FEATURES,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(3)  # 0=HOLD, 1=BUY, 2=SELL

        self._bt: MarketDataBacktester | None = None
        self._features: pd.DataFrame | None = None
        self._tick_idx: int = 0
        self._prev_value: float = initial_capital
        self._instrument: str | None = None
        self._ccl_delegate = None

    # ------------------------------------------------------------------
    def reset(self, *, seed=None, options=None) -> tuple[np.ndarray, dict]:
        super().reset(seed=seed)

        # DLR uses CCL (AL30D/AL30) real data — CCL IS the synthetic DLR proxy
        if self.use_synthetic and self.instrument_type == 'DLR':
            from finance.HFT.ml.env_ccl import CCLEnv
            # Try up to 5 random dates; fall back to OU synthetic if all fail
            for _ in range(5):
                ccl_env = CCLEnv(initial_capital=self.initial_capital)
                obs, info = ccl_env.reset(seed=seed)
                if (obs != 0).any():  # successful reset
                    self._ccl_delegate = ccl_env
                    self._features = None
                    self._instrument = 'CCL_SPREAD'
                    return obs.astype(np.float32)[:N_FEATURES] if len(obs) >= N_FEATURES else np.pad(obs, (0, N_FEATURES - len(obs))).astype(np.float32), info
                seed = (seed or 0) + 1
            # All CCL attempts failed — fall back to OU synthetic
            logger.warning("CCLEnv failed 5 times, falling back to OU synthetic")
            self._ccl_delegate = None
            from finance.HFT.ml.synthetic_dlr import generate_episode
            ticks, trades = generate_episode(seed=random.randint(0, 2**31))
        else:
            if not self.dates:
                return np.zeros(N_FEATURES, dtype=np.float32), {}
            date = random.choice(self.dates)
            try:
                ticks, trades = _load_day(date, self.instrument_type)
                if ticks.empty or trades.empty:
                    raise ValueError("empty data")
            except Exception as e:
                logger.warning("TradingEnv reset failed for {date}: {e}", date=date, e=e)
                return np.zeros(N_FEATURES, dtype=np.float32), {}

        self._features = extract_features(ticks, trades).fillna(0.0)
        self._bt = MarketDataBacktester(initial_capital=self.initial_capital)
        self._bt.load_market_data(trades, ticks)
        self._tick_idx = 0
        self._prev_value = self.initial_capital
        self._instrument = list(self._bt.instrument_multipliers.keys())[0] if self._bt.instrument_multipliers else None
        return self._obs(), {}

    def step(self, action: int) -> tuple[np.ndarray, float, bool, bool, dict]:
        # Delegate to CCLEnv if DLR synthetic mode
        if hasattr(self, '_ccl_delegate') and self._ccl_delegate is not None:
            obs, reward, done, trunc, info = self._ccl_delegate.step(action)
            return obs.astype(np.float32)[:N_FEATURES] if len(obs) >= N_FEATURES else np.pad(obs, (0, N_FEATURES - len(obs))).astype(np.float32), reward, done, trunc, info

        if self._features is None or self._tick_idx >= len(self._features):
            return np.zeros(N_FEATURES, dtype=np.float32), 0.0, True, False, {}

        # Map action → signal
        if action != 0 and self._instrument:
            direction = Direction.BUY if action == 1 else Direction.SELL
            pos = self._bt.position.get(self._instrument, 0)
            # Only act if not already in same direction
            if not (direction == Direction.BUY and pos > 0) and \
               not (direction == Direction.SELL and pos < 0):
                ob = self._current_ob()
                if ob:
                    signal = {
                        'direction': direction, 'volume': 1,
                        'order_type': OrderType.MARKET,
                        'instrument': self._instrument,
                    }
                    self._bt._execute_strategy_order(signal, ob)
                    self._bt.cash = self._bt._executor.cash

        # Advance tick and compute reward
        self._tick_idx += 1
        ob = self._current_ob()
        if ob:
            self._bt._update_pnl(ob)

        current_value = self._bt.cash
        if ob and self._instrument:
            pos = self._bt.position.get(self._instrument, 0)
            mult = self._bt.instrument_multipliers.get(self._instrument, 1)
            mid = (ob.bid_price + ob.ask_price) / 2
            current_value += pos * mid * mult

        reward = float(np.clip((current_value - self._prev_value) * REWARD_SCALE, -1.0, 1.0))
        self._prev_value = current_value

        done = self._tick_idx >= len(self._features)
        return self._obs(), reward, done, False, {'portfolio_value': current_value}

    def _obs(self) -> np.ndarray:
        if self._features is None or self._tick_idx >= len(self._features):
            return np.zeros(N_FEATURES, dtype=np.float32)
        return self._features.iloc[self._tick_idx][FEATURE_COLS].values.astype(np.float32)

    def _current_ob(self):
        if not self._bt or not self._bt.order_book_snapshots or not self._instrument:
            return None
        ts = self._features.index[min(self._tick_idx, len(self._features) - 1)]
        return self._bt._get_latest_orderbook(ts, self._instrument)


if __name__ == '__main__':
    env = TradingEnv('DLR')
    obs, _ = env.reset()
    total_reward = 0.0
    done = False
    steps = 0
    while not done:
        action = env.action_space.sample()
        obs, reward, done, _, info = env.step(action)
        total_reward += reward
        steps += 1
    print(f"Steps: {steps}  Total reward: {total_reward:.4f}  Final value: {info.get('portfolio_value', 0):,.0f}")
