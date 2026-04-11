"""
Redis cache wrapper for AlgoTrading.

TTLs per data type:
- Market data (ticks, order book): 5 seconds
- Historical OHLCV: 1 hour
- Backtest results: 24 hours
"""

import json
import pickle
from functools import wraps
from typing import Any, Optional

import redis
import pandas as pd

from finance.config import settings
from finance.utils.logger import logger

# TTL constants (seconds)
TTL_MARKET = 5
TTL_HISTORICAL = 3_600
TTL_BACKTEST = 86_400


def _get_client() -> redis.Redis:
    return redis.Redis(
        host=settings.redis.host,
        port=settings.redis.port,
        db=settings.redis.db,
        password=settings.redis.password or None,
        decode_responses=False,
        socket_connect_timeout=2,
    )


def get(key: str) -> Optional[Any]:
    try:
        client = _get_client()
        raw = client.get(key)
        if raw is None:
            return None
        return pickle.loads(raw)
    except Exception as e:
        logger.warning("Cache GET failed for {key}: {e}", key=key, e=e)
        return None


def set(key: str, value: Any, ttl: int = TTL_HISTORICAL) -> bool:
    try:
        client = _get_client()
        client.setex(key, ttl, pickle.dumps(value))
        return True
    except Exception as e:
        logger.warning("Cache SET failed for {key}: {e}", key=key, e=e)
        return False


def delete(key: str) -> bool:
    try:
        _get_client().delete(key)
        return True
    except Exception as e:
        logger.warning("Cache DELETE failed for {key}: {e}", key=key, e=e)
        return False


def cached(key_prefix: str, ttl: int = TTL_HISTORICAL):
    """
    Decorator that caches function return value in Redis.

    Usage:
        @cached("ohlcv", ttl=TTL_HISTORICAL)
        def get_ohlcv(instrument, bucket, hours_back): ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = f"{key_prefix}:{':'.join(str(a) for a in args)}:{':'.join(f'{k}={v}' for k,v in sorted(kwargs.items()))}"
            cached_val = get(key)
            if cached_val is not None:
                logger.debug("Cache HIT: {key}", key=key)
                return cached_val
            result = func(*args, **kwargs)
            if result is not None:
                set(key, result, ttl)
                logger.debug("Cache SET: {key} ttl={ttl}s", key=key, ttl=ttl)
            return result
        return wrapper
    return decorator
