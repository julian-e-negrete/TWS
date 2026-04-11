"""
Master training runner — trains all ML/RL agents sequentially and logs results.

Runs:
  1. LightGBM supervised baseline (DLR, GGAL, BTCUSDT)
  2. PPO RL agent for DLR
  3. PPO RL agent for GGAL options
  4. PPO RL agent for Binance margin

All results pushed to Prometheus Pushgateway + Redis.
Model artifacts saved to models/{YYYY-MM-DD}/ with latest symlink updated.

Usage:
    PYTHONPATH=. python -m finance.HFT.ml.train_all
    PYTHONPATH=. python -m finance.HFT.ml.train_all --instruments DLR          # single
    PYTHONPATH=. python -m finance.HFT.ml.train_all --skip-supervised          # RL only
    PYTHONPATH=. python -m finance.HFT.ml.train_all --timesteps 50000          # quick run
"""
import argparse
import os
import time

# Enforce CPU-only (no GPU needed for small MLP policies)
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
from datetime import date

from finance.utils.logger import logger
from finance.HFT.ml.monitoring import MLMonitor


def _push_run_status(instrument: str, stage: str, status: str, elapsed_s: float):
    """Push training run status to Pushgateway."""
    try:
        from prometheus_client import CollectorRegistry, Gauge, push_to_gateway
        reg = CollectorRegistry()
        Gauge("algotrading_ml_train_elapsed_seconds", "Training elapsed seconds",
              ["instrument", "stage"], registry=reg).labels(instrument=instrument, stage=stage).set(elapsed_s)
        Gauge("algotrading_ml_train_status", "Training status (1=ok, 0=failed)",
              ["instrument", "stage"], registry=reg).labels(instrument=instrument, stage=stage).set(
              1 if status == "ok" else 0)
        push_to_gateway("localhost:9091", job="ml_training",
                        grouping_key={"instrument": instrument, "stage": stage}, registry=reg)
    except Exception as e:
        logger.debug("Pushgateway unavailable: {e}", e=e)


def train_supervised(instruments: list[str], model_version: str):
    # Only DLR has real tick-level features suitable for LightGBM
    # BTCUSDT: 1-min OHLCV → zero features; GGAL: daily OHLCV → zero features
    # GGAL_OPTIONS/CCL_SPREAD/BTC_MARGIN use dedicated PPO trainers with their own BC baselines
    SUPPORTED = {'DLR'}
    supported = [i for i in instruments if i in SUPPORTED]
    if not supported:
        logger.info("Skipping supervised — only DLR supports LightGBM (instruments={i})", i=instruments)
        return
    from finance.HFT.ml.supervised import train as train_lgbm
    for instr in supported:
        logger.info("=== Supervised: {i} ===", i=instr)
        t0 = time.time()
        try:
            train_lgbm(instr, model_version=model_version)
            _push_run_status(instr, "supervised", "ok", time.time() - t0)
        except Exception as e:
            logger.error("Supervised {i} failed: {e}", i=instr, e=e)
            _push_run_status(instr, "supervised", "failed", time.time() - t0)


def train_rl_dlr(timesteps: int, model_version: str):
    from finance.HFT.ml.rl_agent import train as train_ppo
    logger.info("=== PPO: DLR ===")
    t0 = time.time()
    try:
        train_ppo('DLR', total_timesteps=timesteps, bc_diversity=True, model_version=model_version)
        _push_run_status('DLR', "ppo", "ok", time.time() - t0)
    except Exception as e:
        logger.error("PPO DLR failed: {e}", e=e)
        _push_run_status('DLR', "ppo", "failed", time.time() - t0)


def train_rl_options(timesteps: int, model_version: str):
    from finance.HFT.ml.agents.train_options import train as train_opts
    logger.info("=== PPO: GGAL_OPTIONS ===")
    t0 = time.time()
    try:
        train_opts(timesteps=timesteps, model_version=model_version)
        _push_run_status('GGAL_OPTIONS', "ppo", "ok", time.time() - t0)
    except Exception as e:
        logger.error("PPO GGAL_OPTIONS failed: {e}", e=e)
        _push_run_status('GGAL_OPTIONS', "ppo", "failed", time.time() - t0)


def train_rl_crypto(timesteps: int, model_version: str, leverage: int = 3):
    from finance.HFT.ml.agents.train_crypto import train as train_crypto
    logger.info("=== PPO: BTC_MARGIN {l}x ===", l=leverage)
    t0 = time.time()
    try:
        train_crypto('BTCUSDT', leverage=leverage, timesteps=timesteps, model_version=model_version)
        _push_run_status(f'BTCUSDT_MARGIN_{leverage}X', "ppo", "ok", time.time() - t0)
    except Exception as e:
        logger.error("PPO BTC_MARGIN failed: {e}", e=e)
        _push_run_status(f'BTCUSDT_MARGIN_{leverage}X', "ppo", "failed", time.time() - t0)


def train_rl_ccl(timesteps: int, model_version: str):
    from finance.HFT.ml.agents.train_ccl import train as train_ccl
    logger.info("=== PPO: CCL_SPREAD (AL30D/AL30) ===")
    t0 = time.time()
    try:
        train_ccl(timesteps=timesteps, model_version=model_version)
        _push_run_status('CCL_SPREAD', "ppo", "ok", time.time() - t0)
    except Exception as e:
        logger.error("PPO CCL_SPREAD failed: {e}", e=e)
        _push_run_status('CCL_SPREAD', "ppo", "failed", time.time() - t0)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Train all ML/RL agents")
    parser.add_argument('--instruments',     nargs='+', default=['DLR', 'GGAL_OPTIONS', 'BTC_MARGIN'],
                        choices=['DLR', 'GGAL', 'GGAL_OPTIONS', 'BTC_MARGIN', 'BTCUSDT', 'CCL_SPREAD'])
    parser.add_argument('--timesteps',       type=int, default=None, help='PPO timesteps (default from config)')
    parser.add_argument('--leverage',        type=int, default=3)
    parser.add_argument('--skip-supervised', action='store_true')
    parser.add_argument('--skip-rl',         action='store_true')
    parser.add_argument('--model-version',   default=date.today().isoformat())
    args = parser.parse_args()

    from finance.HFT.ml import get_config
    cfg = get_config()
    timesteps = args.timesteps or cfg['training']['ppo_timesteps']
    v = args.model_version

    logger.info("Training run: version={v} timesteps={t}", v=v, t=timesteps)
    t_total = time.time()

    if not args.skip_supervised:
        supervised_instruments = [i for i in args.instruments if i in ('DLR', 'GGAL')]
        if supervised_instruments:
            train_supervised(supervised_instruments, v)

    if not args.skip_rl:
        if 'DLR' in args.instruments:
            train_rl_dlr(timesteps, v)
        if 'GGAL_OPTIONS' in args.instruments:
            train_rl_options(timesteps, v)
        if 'BTC_MARGIN' in args.instruments:
            train_rl_crypto(timesteps, v, args.leverage)
        if 'CCL_SPREAD' in args.instruments:
            train_rl_ccl(timesteps, v)

    elapsed = time.time() - t_total
    logger.info("All training complete in {s:.0f}s", s=elapsed)
    _push_run_status("ALL", "complete", "ok", elapsed)
