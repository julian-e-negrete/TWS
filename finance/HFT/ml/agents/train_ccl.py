"""
Train PPO agent for CCL spread (AL30D/AL30 synthetic DLR proxy).

BC baseline: mean-reversion on CCL z-score
  BUY when ccl_vs_mean_20 < -1.0 (CCL below mean → expect reversion up)
  SELL when ccl_vs_mean_20 > +1.0

Usage:
    python -m finance.HFT.ml.agents.train_ccl --timesteps 300000
"""
import argparse
from datetime import date
from pathlib import Path

import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.callbacks import EvalCallback, BaseCallback

from finance.HFT.ml import get_config
from finance.HFT.ml.env_ccl import CCLEnv
from finance.HFT.ml.features_ccl import CCL_FEATURE_COLS, extract_ccl_features
from finance.HFT.ml.monitoring import MLMonitor
from finance.utils.logger import logger

MODELS_DIR = Path(__file__).parent.parent / 'models'
INSTRUMENT  = 'CCL_SPREAD'

TRAIN_DATES = [
    ('2025-09-01', '2025-09-30'),
    ('2025-10-01', '2025-10-31'),
    ('2025-11-01', '2025-11-30'),
]


def _bc_rollouts() -> tuple[np.ndarray, np.ndarray]:
    """Mean-reversion baseline: BUY when CCL below 20-tick mean, SELL when above."""
    obs_list, act_list = [], []
    for d_from, d_to in TRAIN_DATES:
        try:
            feat = extract_ccl_features(d_from, d_to).fillna(0.0)
            if feat.empty:
                continue
            for _, row in feat.iterrows():
                obs = row[CCL_FEATURE_COLS].values.astype(np.float32)
                z = row.get('ccl_vs_mean_20', 0.0)
                action = 1 if z < -1.0 else (2 if z > 1.0 else 0)
                obs_list.append(obs)
                act_list.append(action)
        except Exception as e:
            logger.warning("BC rollout failed {d}: {e}", d=d_from, e=e)
    logger.info("CCL BC: {n} transitions", n=len(obs_list))
    return np.array(obs_list, dtype=np.float32), np.array(act_list, dtype=np.int64)


def _bc_pretrain(ppo: PPO, obs: np.ndarray, acts: np.ndarray, n_steps: int = 5_000):
    import torch as th
    from torch.utils.data import DataLoader, TensorDataset
    dataset = TensorDataset(th.tensor(obs), th.tensor(acts, dtype=th.long))
    loader  = DataLoader(dataset, batch_size=256, shuffle=True)
    opt     = th.optim.Adam(ppo.policy.parameters(), lr=1e-3)
    loss_fn = th.nn.CrossEntropyLoss()
    steps, loss = 0, th.tensor(0.0)
    while steps < n_steps:
        for bx, by in loader:
            logits = ppo.policy.get_distribution(bx).distribution.logits
            loss   = loss_fn(logits, by)
            opt.zero_grad(); loss.backward(); opt.step()
            steps += len(bx)
            if steps >= n_steps:
                break
    logger.info("CCL BC done ({s} steps, loss={l:.4f})", s=steps, l=loss.item())


def train(timesteps: int | None = None, model_version: str | None = None) -> PPO:
    cfg = get_config()
    timesteps = timesteps or cfg['training']['ppo_timesteps']
    mon = MLMonitor(INSTRUMENT)

    env      = make_vec_env(CCLEnv, n_envs=4)
    eval_env = CCLEnv()
    ppo = PPO('MlpPolicy', env, verbose=0, learning_rate=3e-4,
              n_steps=512, batch_size=64, n_epochs=10, gamma=0.99)

    obs, acts = _bc_rollouts()
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

    eval_cb = EvalCallback(eval_env, eval_freq=10_000, n_eval_episodes=3, verbose=1, warn=False)
    ppo.learn(total_timesteps=timesteps, callback=[eval_cb, _MonCB()], progress_bar=True)

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


def load_policy(model_version: str | None = None) -> PPO:
    base = (MODELS_DIR / model_version) if model_version else (MODELS_DIR / 'latest')
    return PPO.load(str(base / f'ppo_{INSTRUMENT}.zip'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--timesteps',     type=int, default=None)
    parser.add_argument('--model_version', default=None)
    args = parser.parse_args()
    train(args.timesteps, args.model_version)
