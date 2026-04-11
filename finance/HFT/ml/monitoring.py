"""
ML monitoring — pushes training and inference metrics to:
  - Redis (real-time, TTL=300s): for live dashboards / polling
  - Prometheus Pushgateway (localhost:9091): for Grafana gauges
  - PostgreSQL ml_training_episodes: full history for Grafana time-series curves
"""
import json
import time
from datetime import datetime, timezone

from finance.utils.logger import logger

_PUSHGATEWAY = "localhost:9091"
_REDIS_TTL   = 300


def _ensure_tables():
    """Create ml_training_episodes table if not exists."""
    try:
        from finance.utils.db_pool import get_pg_engine
        from sqlalchemy import text
        with get_pg_engine().begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS ml_training_episodes (
                    id          BIGSERIAL PRIMARY KEY,
                    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    instrument  TEXT NOT NULL,
                    run_date    DATE NOT NULL DEFAULT CURRENT_DATE,
                    stage       TEXT NOT NULL,  -- 'rl_episode' | 'supervised'
                    episode     INT,
                    reward      FLOAT,
                    steps       INT,
                    loss        FLOAT,
                    accuracy    FLOAT,
                    regimes_covered INT
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_ml_ep_instrument_ts "
                "ON ml_training_episodes (instrument, ts DESC)"
            ))
    except Exception as e:
        logger.debug("ml_training_episodes table init failed: {e}", e=e)

_tables_ready = False

def _db_insert(row: dict):
    global _tables_ready
    try:
        from finance.utils.db_pool import get_pg_engine
        from sqlalchemy import text
        if not _tables_ready:
            _ensure_tables()
            _tables_ready = True
        with get_pg_engine().begin() as conn:
            conn.execute(text("""
                INSERT INTO ml_training_episodes
                    (instrument, stage, episode, reward, steps, loss, accuracy, regimes_covered)
                VALUES
                    (:instrument, :stage, :episode, :reward, :steps, :loss, :accuracy, :regimes_covered)
            """), row)
    except Exception as e:
        logger.debug("ml_training_episodes insert failed: {e}", e=e)


def _redis():
    try:
        import redis as _r
        from finance.config import settings
        host = settings.redis.host if settings.redis.host != "redis" else "localhost"
        c = _r.Redis(host=host, port=settings.redis.port, db=settings.redis.db,
                     password=settings.redis.password or None, socket_connect_timeout=1)
        c.ping()
        return c
    except Exception:
        return None


def _push(job: str, grouping: dict, metrics: dict):
    """Push metrics dict to Prometheus Pushgateway. Silent on failure."""
    try:
        from prometheus_client import CollectorRegistry, Gauge, push_to_gateway
        reg = CollectorRegistry()
        for name, (help_text, labels, value) in metrics.items():
            g = Gauge(name, help_text, list(labels.keys()), registry=reg)
            g.labels(**labels).set(value)
        push_to_gateway(_PUSHGATEWAY, job=job, grouping_key=grouping, registry=reg)
    except Exception as e:
        logger.debug("Pushgateway unavailable: {e}", e=e)


class MLMonitor:
    def __init__(self, instrument: str):
        self.instrument = instrument
        self._r = _redis()

    def _rset(self, key: str, data: dict):
        if self._r:
            try:
                self._r.setex(f"ml:{key}", _REDIS_TTL, json.dumps({**data, "ts": datetime.now(timezone.utc).isoformat()}))
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Supervised training
    # ------------------------------------------------------------------

    def log_training_step(self, epoch: int, loss: float, accuracy: float):
        data = {"epoch": epoch, "loss": loss, "accuracy": accuracy, "instrument": self.instrument}
        self._rset(f"training:{self.instrument}", data)
        _push("ml_training", {"instrument": self.instrument}, {
            "algotrading_ml_training_loss":     ("LightGBM training loss",     {"instrument": self.instrument}, loss),
            "algotrading_ml_training_accuracy": ("LightGBM training accuracy", {"instrument": self.instrument}, accuracy),
            "algotrading_ml_training_epoch":    ("LightGBM training epoch",    {"instrument": self.instrument}, epoch),
        })
        _db_insert({"instrument": self.instrument, "stage": "supervised",
                    "episode": epoch, "reward": None, "steps": None,
                    "loss": loss, "accuracy": accuracy, "regimes_covered": None})
        logger.info("Training [{instrument}] epoch={epoch} loss={loss:.4f} acc={acc:.4f}",
                    instrument=self.instrument, epoch=epoch, loss=loss, acc=accuracy)

    # ------------------------------------------------------------------
    # RL episode
    # ------------------------------------------------------------------

    def log_episode(self, episode: int, reward: float, steps: int, regimes_covered: int = 0):
        data = {"episode": episode, "reward": reward, "steps": steps,
                "regimes_covered": regimes_covered, "instrument": self.instrument}
        self._rset(f"rl_episode:{self.instrument}", data)
        # Keep rolling history in Redis list (last 100 episodes)
        if self._r:
            try:
                key = f"ml:rl_history:{self.instrument}"
                self._r.lpush(key, json.dumps(data))
                self._r.ltrim(key, 0, 99)
                self._r.expire(key, 86400)
            except Exception:
                pass

        # Compute rolling mean reward from last 20 episodes stored in Redis
        mean_reward = reward
        if self._r:
            try:
                raw = self._r.lrange(f"ml:rl_history:{self.instrument}", 0, 19)
                rewards = [json.loads(r)['reward'] for r in raw if r]
                mean_reward = sum(rewards) / len(rewards) if rewards else reward
            except Exception:
                pass

        _push("ml_rl", {"instrument": self.instrument}, {
            "algotrading_ml_rl_episode_reward":      ("PPO episode reward",              {"instrument": self.instrument}, reward),
            "algotrading_ml_rl_episode_reward_mean": ("PPO rolling mean reward (20 ep)", {"instrument": self.instrument}, mean_reward),
            "algotrading_ml_rl_episode_steps":       ("PPO episode steps",               {"instrument": self.instrument}, steps),
            "algotrading_ml_rl_regimes_covered":     ("BC regime diversity count",       {"instrument": self.instrument}, regimes_covered),
            "algotrading_ml_rl_episode_number":      ("PPO episode number",              {"instrument": self.instrument}, episode),
        })
        _db_insert({"instrument": self.instrument, "stage": "rl_episode",
                    "episode": episode, "reward": reward, "steps": steps,
                    "loss": None, "accuracy": None, "regimes_covered": regimes_covered})
        logger.info("Episode [{instrument}] #{ep} reward={reward:.4f} mean20={mean:.4f} steps={steps}",
                    instrument=self.instrument, ep=episode, reward=reward, mean=mean_reward, steps=steps)

    # ------------------------------------------------------------------
    # Live inference
    # ------------------------------------------------------------------

    def log_signal(self, action: str, instrument: str, price: float):
        data = {"action": action, "instrument": instrument, "price": price}
        self._rset(f"last_signal:{instrument}", data)
        action_val = {"BUY": 1, "SELL": -1, "HOLD": 0}.get(action, 0)
        _push("ml_live", {"instrument": instrument}, {
            "algotrading_ml_live_signal":       ("Last ML signal (1=BUY,-1=SELL,0=HOLD)", {"instrument": instrument}, action_val),
            "algotrading_ml_live_signal_price": ("Price at last ML signal",                {"instrument": instrument}, price),
        })

    def log_position(self, position: int, pnl: float):
        data = {"position": position, "pnl": pnl, "instrument": self.instrument}
        self._rset(f"position:{self.instrument}", data)
        _push("ml_live", {"instrument": self.instrument}, {
            "algotrading_ml_live_position": ("Current ML live position", {"instrument": self.instrument}, position),
            "algotrading_ml_live_pnl":      ("Simulated P&L",            {"instrument": self.instrument}, pnl),
        })
