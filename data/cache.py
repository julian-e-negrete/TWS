import os
import pickle
import redis
import logging

logger = logging.getLogger(__name__)

# TTL for cache in seconds
TTL_MARKET = 60      # 1 minute for live data
TTL_HISTORICAL = 3600 # 1 hour for historical data

_client = None

def _get_client():
    global _client
    if _client is None:
        try:
            _client = redis.Redis(
                host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", "6379")),
                db=int(os.getenv("REDIS_DB", "0")),
                password=os.getenv("REDIS_PASSWORD") or None,
                socket_connect_timeout=2,
            )
            _client.ping()
        except Exception as e:
            logger.warning(f"Redis unavailable, cache disabled: {e}")
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
