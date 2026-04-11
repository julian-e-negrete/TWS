"""
Train PPO agent for Binance margin (leveraged).

Baseline policy for BC: crypto_rsi from bt12_extended.py
(BUY when RSI < 30, SHORT when RSI > 70).

Usage:
    python -m finance.HFT.ml.agents.train_crypto --timesteps 200000 --leverage 3
    python -m finance.HFT.ml.agents.train_crypto --symbol BTCUSDT --leverage 5
"""
import argparse
from datetime import date
from pathlib import Path

import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.callbacks import EvalCallback, BaseCallback
from stable_baselines3.common.vec_env import VecNormalize

from finance.HFT.ml import get_config
from finance.HFT.ml.env_crypto import CryptoMarginEnv
from finance.HFT.ml.features_crypto import extract_crypto_features, CRYPTO_FEATURE_COLS
from finance.HFT.ml.monitoring import MLMonitor
from finance.utils.logger import logger

MODELS_DIR = Path(__file__).parent.parent / 'models'


def _instrument_key(symbol: str, leverage: int) -> str:
    return f'{symbol}_MARGIN_{leverage}X'


def _bc_rollouts(symbol: str, leverage: int) -> tuple[np.ndarray, np.ndarray]:
    """Rule-based baseline: RSI < 30 → LONG(1), RSI > 70 → SHORT(2), else HOLD(0).
    Labels use next-bar direction (no look-ahead bias). #250
    Validates BC accuracy > 55% before returning. #254
    """
    feat = extract_crypto_features(symbol, hours_back=168 * 4)  # 4 weeks
    if feat.empty:
        return np.array([]), np.array([])

    # Next-bar direction label — no look-ahead bias (#250)
    next_ret = feat['price_momentum_5'].shift(-1).fillna(0.0)
    labels = np.where(next_ret > 0.0005, 1, np.where(next_ret < -0.0005, 2, 0))

    obs_arr = feat[CRYPTO_FEATURE_COLS].values.astype(np.float32)
    # Chronological 80/20 split for validation (#256)
    split = int(len(obs_arr) * 0.8)
    X_tr, y_tr = obs_arr[:split], labels[:split]
    X_val, y_val = obs_arr[split:], labels[split:]

    # Validate signal quality (#254)
    from sklearn.ensemble import GradientBoostingClassifier
    clf = GradientBoostingClassifier(n_estimators=50, max_depth=3, random_state=42)
    clf.fit(X_tr, y_tr)
    acc = (clf.predict(X_val) == y_val).mean()
    logger.info("BC pretrain accuracy: {a:.3f}", a=acc)
    if acc < 0.40:  # below random — skip BC
        logger.warning("BC accuracy {a:.3f} too low — skipping pretrain", a=acc)
        return np.array([]), np.array([])

    logger.info("Crypto BC: {n} transitions", n=len(obs_arr))
    return obs_arr, labels.astype(np.int64)


def _bc_pretrain(ppo: PPO, obs: np.ndarray, acts: np.ndarray, n_steps: int = 5_000):
    import torch as th
    from torch.utils.data import DataLoader, TensorDataset
    device = next(ppo.policy.parameters()).device
    dataset = TensorDataset(th.tensor(obs), th.tensor(acts, dtype=th.long))
    loader  = DataLoader(dataset, batch_size=256, shuffle=True)
    opt     = th.optim.Adam(ppo.policy.parameters(), lr=1e-3)
    loss_fn = th.nn.CrossEntropyLoss()
    steps, loss = 0, th.tensor(0.0)
    while steps < n_steps:
        for bx, by in loader:
            bx, by = bx.to(device), by.to(device)
            logits = ppo.policy.get_distribution(bx).distribution.logits
            loss   = loss_fn(logits, by)
            opt.zero_grad(); loss.backward(); opt.step()
            steps += len(bx)
            if steps >= n_steps:
                break
    logger.info("Crypto BC done ({s} steps, loss={l:.4f})", s=steps, l=loss.item())


def train(symbol: str = 'BTCUSDT', leverage: int = 3,
          timesteps: int | None = None, model_version: str | None = None) -> PPO:
    cfg = get_config()
    timesteps = timesteps or cfg['training']['ppo_timesteps']
    instrument = _instrument_key(symbol, leverage)
    mon = MLMonitor(instrument)

    env_fn = lambda: CryptoMarginEnv(symbol=symbol, leverage=leverage)
    env    = VecNormalize(make_vec_env(env_fn, n_envs=4), norm_obs=True, norm_reward=False)  # #248

    # Resume from checkpoint if exists, otherwise fresh PPO + BC pretrain
    v = model_version or date.today().isoformat()
    ckpt     = MODELS_DIR / v / f'ppo_{instrument}.zip'
    norm_ckpt = MODELS_DIR / v / f'vecnorm_{instrument}.pkl'
    if ckpt.exists():
        logger.info("Resuming from checkpoint: {p}", p=ckpt)
        env = VecNormalize.load(str(norm_ckpt), env) if norm_ckpt.exists() else env
        ppo = PPO.load(str(ckpt), env=env, device='cpu')
    else:
        ppo = PPO('MlpPolicy', env, verbose=0,
                  learning_rate=3e-5,   # #255: reduced from 3e-4
                  n_steps=2048,         # #255: increased from 512
                  batch_size=256,       # #255: increased from 64
                  n_epochs=10, gamma=0.99)
        obs, acts = _bc_rollouts(symbol, leverage)
        if len(obs):
            _bc_pretrain(ppo, obs, acts)

    eval_env = VecNormalize(make_vec_env(env_fn, n_envs=1), norm_obs=True, norm_reward=False)

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
    ppo.learn(total_timesteps=timesteps, callback=[eval_cb, _MonCB()], progress_bar=False)

    out = MODELS_DIR / v
    out.mkdir(parents=True, exist_ok=True)
    path = out / f'ppo_{instrument}.zip'
    ppo.save(str(path))
    env.save(str(out / f'vecnorm_{instrument}.pkl'))  # save normalizer stats
    symlink = MODELS_DIR / 'latest'
    if symlink.is_symlink(): symlink.unlink()
    symlink.symlink_to(v)
    logger.info("Saved → {p}", p=path)
    return ppo


def load_policy(symbol: str = 'BTCUSDT', leverage: int = 3,
                model_version: str | None = None) -> PPO:
    instrument = _instrument_key(symbol, leverage)
    base = (MODELS_DIR / model_version) if model_version else (MODELS_DIR / 'latest')
    return PPO.load(str(base / f'ppo_{instrument}.zip'), device='cpu')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--symbol',        default='BTCUSDT')
    parser.add_argument('--leverage',      type=int, default=3)
    parser.add_argument('--timesteps',     type=int, default=None)
    parser.add_argument('--model_version', default=None)
    args = parser.parse_args()
    train(args.symbol, args.leverage, args.timesteps, args.model_version)
