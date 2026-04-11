"""
Train PPO agent for GGAL options.

Baseline policy for BC: bs_long_call / bs_long_put mispricing signals
from options_backtest.py (BUY when market < BS × 0.90).

Usage:
    python -m finance.HFT.ml.agents.train_options --timesteps 100000
    python -m finance.HFT.ml.agents.train_options --timesteps 50000 --leverage_implicit
"""
import argparse
from datetime import date
from pathlib import Path

import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.callbacks import EvalCallback, BaseCallback

from finance.HFT.ml import get_config
from finance.HFT.ml.env_options import OptionsEnv
from finance.HFT.ml.features_options import OPTIONS_FEATURE_COLS, extract_options_features
from finance.HFT.ml.monitoring import MLMonitor
from finance.HFT.backtest.options_backtest import BUY_THRESH
from finance.utils.logger import logger

MODELS_DIR = Path(__file__).parent.parent / 'models'
INSTRUMENT  = 'GGAL_OPTIONS'


def _bc_rollouts(n_episodes: int = 10) -> tuple[np.ndarray, np.ndarray]:
    """Rule-based baseline: BUY_CALL(1) when call underpriced, BUY_PUT(2) when put underpriced."""
    from sqlalchemy import text
    from finance.utils.db_pool import get_pg_engine

    with get_pg_engine().connect() as conn:
        expiries = [r[0] for r in conn.execute(text(
            "SELECT DISTINCT expiry FROM ppi_options_chain WHERE underlying='GGAL' ORDER BY expiry"
        )).fetchall()]

    obs_list, act_list = [], []
    env = OptionsEnv()

    for expiry in expiries[:n_episodes]:
        feat = extract_options_features(expiry)
        if feat.empty:
            continue
        rows = feat.fillna(0.0).reset_index().to_dict('records')
        for row in rows:
            obs = np.array([row.get(f, 0.0) for f in OPTIONS_FEATURE_COLS], dtype=np.float32)
            misp = row.get('mispricing_pct', 0.0)
            opt_type = row.get('option_type', '')
            tte = row.get('time_to_expiry_days', 0)
            if tte < 3:
                action = 3  # CLOSE near expiry
            elif misp < -10 and opt_type == 'C':
                action = 1  # BUY_CALL when call underpriced >10%
            elif misp < -10 and opt_type == 'P':
                action = 2  # BUY_PUT when put underpriced >10%
            else:
                action = 0  # HOLD
            obs_list.append(obs)
            act_list.append(action)

    logger.info("Options BC: {n} transitions from {e} expiries", n=len(obs_list), e=n_episodes)
    return np.array(obs_list, dtype=np.float32), np.array(act_list, dtype=np.int64)


def _bc_pretrain(ppo: PPO, obs: np.ndarray, acts: np.ndarray, n_steps: int = 3_000):
    import torch as th
    from torch.utils.data import DataLoader, TensorDataset
    dataset  = TensorDataset(th.tensor(obs), th.tensor(acts, dtype=th.long))
    loader   = DataLoader(dataset, batch_size=128, shuffle=True)
    opt      = th.optim.Adam(ppo.policy.parameters(), lr=1e-3)
    loss_fn  = th.nn.CrossEntropyLoss()
    steps, loss = 0, th.tensor(0.0)
    while steps < n_steps:
        for bx, by in loader:
            logits = ppo.policy.get_distribution(bx).distribution.logits
            loss   = loss_fn(logits, by)
            opt.zero_grad(); loss.backward(); opt.step()
            steps += len(bx)
            if steps >= n_steps:
                break
    logger.info("Options BC done ({s} steps, loss={l:.4f})", s=steps, l=loss.item())


def train(timesteps: int | None = None, model_version: str | None = None) -> PPO:
    cfg = get_config()
    timesteps = timesteps or cfg['training']['ppo_timesteps']
    mon = MLMonitor(INSTRUMENT)

    env      = make_vec_env(OptionsEnv, n_envs=4)
    eval_env = OptionsEnv()
    ppo = PPO('MlpPolicy', env, verbose=0, learning_rate=3e-4,
              n_steps=256, batch_size=32, n_epochs=10, gamma=0.99)

    obs, acts = _bc_rollouts(n_episodes=cfg['training']['bc_episodes'])
    if len(obs):
        _bc_pretrain(ppo, obs, acts)

    class _MonCB(BaseCallback):
        def __init__(self):
            super().__init__(); self._ep = 0
        def _on_step(self):
            for info in self.locals.get('infos', []):
                if 'episode' in info:
                    self._ep += 1
                    mon.log_episode(self._ep, float(info['episode']['r']), int(info['episode']['l']))
            return True

    eval_cb = EvalCallback(eval_env, eval_freq=5_000, n_eval_episodes=3, verbose=1, warn=False)
    ppo.learn(total_timesteps=timesteps, callback=[eval_cb, _MonCB()], progress_bar=False)

    v = model_version or date.today().isoformat()
    out = MODELS_DIR / v
    out.mkdir(parents=True, exist_ok=True)
    path = out / f'ppo_{INSTRUMENT}.zip'
    ppo.save(str(path))
    symlink = MODELS_DIR / 'latest'
    if symlink.is_symlink(): symlink.unlink()
    symlink.symlink_to(v)
    logger.info("Saved → {p}", p=path)
    return ppo


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--timesteps',     type=int, default=None)
    parser.add_argument('--model_version', default=None)
    args = parser.parse_args()
    train(args.timesteps, args.model_version)
