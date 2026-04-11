"""
Redis cache for market data loaders.
Caches load_order_data and load_tick_data results for 1h (TTL=3600).
"""
import pickle
import redis
from finance.config import settings
from finance.utils.logger import logger

_client: redis.Redis | None = None


def _get_client() -> redis.Redis | None:
    global _client
    if _client is None:
        try:
            _client = redis.Redis(
                host=settings.redis.host if settings.redis.host != "redis" else "localhost",
                port=settings.redis.port,
                db=settings.redis.db,
                password=settings.redis.password or None,
                socket_connect_timeout=2,
            )
            _client.ping()
        except Exception as e:
            logger.warning("Redis unavailable, cache disabled: {e}", e=e)
            _client = None
    return _client


def cache_get(key: str):
    r = _get_client()
    if r is None:
        return None
    try:
        data = r.get(key)
        return pickle.loads(data) if data else None
    except Exception:
        return None


def cache_set(key: str, value, ttl: int = 3600):
    r = _get_client()
    if r is None:
        return
    try:
        r.setex(key, ttl, pickle.dumps(value))
    except Exception:
        pass
