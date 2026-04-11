"""
PPO RL agent with behavioral cloning initialization from LightGBM baseline.

Flow:
  1. Load LightGBM model (supervised.py)
  2. Collect expert rollouts with optional diversity filter (--bc_diversity)
  3. BC pre-training via cross-entropy on PPO policy network
  4. PPO fine-tuning via stable-baselines3
  5. Save to models/{date}/ppo_{instrument}.zip

Usage:
    python -m finance.HFT.ml.rl_agent --instrument DLR --timesteps 100000
    python -m finance.HFT.ml.rl_agent --instrument DLR --bc_diversity --model_version 2026-03-25
"""
import argparse
from datetime import date
from pathlib import Path

import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.callbacks import EvalCallback

from finance.HFT.ml import get_config
from finance.HFT.ml.env import TradingEnv
from finance.HFT.ml.features import FEATURE_COLS
from finance.utils.logger import logger

MODELS_DIR = Path(__file__).parent / 'models'


# ---------------------------------------------------------------------------
# Model versioning helpers (mirrors supervised.py)
# ---------------------------------------------------------------------------

def _model_dir(version: str | None = None) -> Path:
    v = version or date.today().isoformat()
    d = MODELS_DIR / v
    d.mkdir(parents=True, exist_ok=True)
    return d


def _latest_model_dir() -> Path | None:
    dirs = sorted([d for d in MODELS_DIR.iterdir() if d.is_dir() and d.name != '__pycache__'], reverse=True)
    return dirs[0] if dirs else None


# ---------------------------------------------------------------------------
# Regime bucketing for BC diversity filter
# ---------------------------------------------------------------------------

def _regime(obs: np.ndarray) -> tuple:
    """Bucket obs into (vol_bucket, spread_bucket, volume_bucket) using feature indices."""
    feat_names = FEATURE_COLS
    spread_idx = feat_names.index('spread_bps')
    vol_idx    = feat_names.index('vol_surge_ratio')
    mom_idx    = feat_names.index('price_momentum_5')

    spread_bucket = int(np.clip(obs[spread_idx] // 10, 0, 4))   # 0-4 (0=tight, 4=wide)
    vol_bucket    = int(np.clip(obs[vol_idx] // 0.5, 0, 4))     # 0-4
    mom_bucket    = int(np.sign(obs[mom_idx]) + 1)               # 0=down, 1=flat, 2=up
    return (spread_bucket, vol_bucket, mom_bucket)


def _collect_expert_data(instrument_type: str, n_episodes: int, diversity_required: bool
                         ) -> tuple[np.ndarray, np.ndarray]:
    from finance.HFT.ml.supervised import load_model, predict

    model = load_model(instrument_type)
    env   = TradingEnv(instrument_type)
    obs_list, act_list, regimes_seen = [], [], set()

    episodes = 0
    max_attempts = n_episodes * 5  # avoid infinite loop

    while episodes < n_episodes or (diversity_required and len(regimes_seen) < 3):
        if episodes >= max_attempts:
            logger.warning("BC diversity: only {n} regimes after {e} episodes", n=len(regimes_seen), e=episodes)
            break

        obs, _ = env.reset()
        done = False
        ep_obs, ep_act, ep_regimes = [], [], set()

        while not done:
            action = predict(model, obs) + 1  # -1/0/1 → 0/1/2
            ep_obs.append(obs.copy())
            ep_act.append(action)
            ep_regimes.add(_regime(obs))
            obs, _, done, _, _ = env.step(action)

        # If diversity filter: only keep episode if it adds a new regime
        if diversity_required and not (ep_regimes - regimes_seen):
            episodes += 1
            continue

        obs_list.extend(ep_obs)
        act_list.extend(ep_act)
        regimes_seen |= ep_regimes
        episodes += 1

    logger.info("BC data: {n} transitions, {r} regimes covered", n=len(obs_list), r=len(regimes_seen))
    from finance.HFT.ml.monitoring import MLMonitor
    MLMonitor(instrument_type).log_episode(episode=0, reward=0.0, steps=len(obs_list), regimes_covered=len(regimes_seen))
    return np.array(obs_list, dtype=np.float32), np.array(act_list, dtype=np.int64)


# ---------------------------------------------------------------------------
# Behavioral cloning pre-training
# ---------------------------------------------------------------------------

def _bc_pretrain(ppo_model: PPO, obs: np.ndarray, acts: np.ndarray, n_steps: int):
    import torch as th
    from torch.utils.data import DataLoader, TensorDataset

    dataset = TensorDataset(th.tensor(obs), th.tensor(acts, dtype=th.long))
    loader  = DataLoader(dataset, batch_size=256, shuffle=True)
    optimizer = th.optim.Adam(ppo_model.policy.parameters(), lr=1e-3)
    loss_fn   = th.nn.CrossEntropyLoss()
    loss = th.tensor(0.0)

    steps = 0
    while steps < n_steps:
        for batch_obs, batch_acts in loader:
            logits = ppo_model.policy.get_distribution(batch_obs).distribution.logits
            loss   = loss_fn(logits, batch_acts)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            steps += len(batch_obs)
            if steps >= n_steps:
                break

    logger.info("BC done ({steps} steps, loss={loss:.4f})", steps=steps, loss=loss.item())


# ---------------------------------------------------------------------------
# Train
# ---------------------------------------------------------------------------

def train(instrument_type: str = 'DLR', total_timesteps: int | None = None,
          bc_diversity: bool | None = None, model_version: str | None = None) -> PPO:
    cfg = get_config()
    total_timesteps = total_timesteps or cfg['training']['ppo_timesteps']
    n_episodes      = cfg['training']['bc_episodes']
    diversity       = bc_diversity if bc_diversity is not None else cfg['training']['bc_diversity_required']

    env      = make_vec_env(lambda: TradingEnv(instrument_type), n_envs=4)
    eval_env = TradingEnv(instrument_type)

    ppo = PPO('MlpPolicy', env, verbose=0, learning_rate=3e-4,
              n_steps=512, batch_size=64, n_epochs=10, gamma=0.99)

    lgbm_path = next(
        (d / f'lgbm_{instrument_type}.pkl'
         for d in [MODELS_DIR / 'latest', _latest_model_dir() or Path('/dev/null')]
         if (d / f'lgbm_{instrument_type}.pkl').exists()),
        None
    )
    if lgbm_path:
        logger.info("Collecting expert rollouts (diversity={d})...", d=diversity)
        obs, acts = _collect_expert_data(instrument_type, n_episodes, diversity)
        _bc_pretrain(ppo, obs, acts, n_steps=5_000)
    else:
        logger.warning("No LightGBM model found; skipping BC init")

    eval_cb = EvalCallback(eval_env, eval_freq=10_000, n_eval_episodes=3, verbose=1, warn=False)
    logger.info("PPO fine-tuning for {n} timesteps...", n=total_timesteps)

    from stable_baselines3.common.callbacks import BaseCallback
    from finance.HFT.ml.monitoring import MLMonitor

    class _MonitorCB(BaseCallback):
        def __init__(self, mon: MLMonitor):
            super().__init__()
            self._mon = mon
            self._ep = 0
        def _on_step(self) -> bool:
            for info in self.locals.get("infos", []):
                if "episode" in info:
                    self._ep += 1
                    self._mon.log_episode(
                        episode=self._ep,
                        reward=float(info["episode"]["r"]),
                        steps=int(info["episode"]["l"]),
                    )
            return True

    mon_cb = _MonitorCB(MLMonitor(instrument_type))
    ppo.learn(total_timesteps=total_timesteps, callback=[eval_cb, mon_cb], progress_bar=False)

    out_dir = _model_dir(model_version)
    path = out_dir / f'ppo_{instrument_type}.zip'
    ppo.save(str(path))

    symlink = MODELS_DIR / 'latest'
    if symlink.is_symlink():
        symlink.unlink()
    symlink.symlink_to(out_dir.name)

    logger.info("Saved PPO → {path}", path=path)
    return ppo


def load_policy(instrument_type: str = 'DLR', model_version: str | None = None) -> PPO:
    if model_version:
        path = MODELS_DIR / model_version / f'ppo_{instrument_type}.zip'
    else:
        latest = MODELS_DIR / 'latest'
        base = latest if latest.exists() else _latest_model_dir()
        if base is None:
            raise FileNotFoundError(f"No trained PPO model found in {MODELS_DIR}")
        path = base / f'ppo_{instrument_type}.zip'
    return PPO.load(str(path))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--instrument',    default='DLR', choices=['DLR', 'BTCUSDT', 'GGAL'])
    parser.add_argument('--timesteps',     type=int, default=None)
    parser.add_argument('--bc_diversity',  action='store_true', help='Enforce regime diversity in BC rollouts')
    parser.add_argument('--model_version', default=None, help='YYYY-MM-DD version tag')
    args = parser.parse_args()
    train(args.instrument, args.timesteps, args.bc_diversity or None, args.model_version)
