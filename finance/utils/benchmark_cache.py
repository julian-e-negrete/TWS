"""
Tarea 6.3 — Cache performance benchmark.

Compares direct DB query vs Redis-cached query for:
- load_tick_data (market data, TTL 5s)
- load_tick_historical (historical OHLCV, TTL 1h)

Target: ≥ 3x speedup on cache hit.
"""

import time
import sys
import pandas as pd

from finance.utils.cache import get, set, delete, TTL_MARKET, TTL_HISTORICAL
from finance.utils.logger import logger


def _time(fn, *args, **kwargs):
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    return result, time.perf_counter() - t0


def benchmark_function(label: str, fn, cache_key: str, ttl: int, *args, **kwargs):
    # Ensure cold cache
    delete(cache_key)

    # Cold run (DB hit)
    result, cold_ms = _time(fn, *args, **kwargs)
    cold_ms *= 1000

    # Populate cache
    set(cache_key, result, ttl=ttl)

    # Warm run (cache hit)
    _, warm_ms = _time(get, cache_key)
    warm_ms *= 1000

    speedup = cold_ms / warm_ms if warm_ms > 0 else float("inf")
    passed = speedup >= 3.0

    status = "✅ PASS" if passed else "❌ FAIL (target 3x)"
    logger.info(
        "[{label}] cold={cold:.1f}ms  cached={warm:.1f}ms  speedup={speedup:.1f}x  {status}",
        label=label, cold=cold_ms, warm=warm_ms, speedup=speedup, status=status,
    )
    return passed, speedup


def run():
    from finance.HFT.backtest.db.load_data import load_tick_data, load_tick_historical

    results = []

    # Benchmark 1: market data (single day ticks)
    passed, speedup = benchmark_function(
        "load_tick_data (market)",
        load_tick_data,
        "bench:ticks:2026-03-19",
        TTL_MARKET,
        "2026-03-19",
    )
    results.append(("load_tick_data", passed, speedup))

    # Benchmark 2: historical OHLCV (1 week)
    passed, speedup = benchmark_function(
        "load_tick_historical (1 week)",
        load_tick_historical,
        "bench:historical:2026-03-10:2026-03-17",
        TTL_HISTORICAL,
        "2026-03-10",
        "2026-03-17",
        "",
        500,
    )
    results.append(("load_tick_historical", passed, speedup))

    print("\n=== Benchmark Summary ===")
    all_passed = True
    for name, passed, speedup in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}  {name}: {speedup:.1f}x speedup")
        if not passed:
            all_passed = False

    if not all_passed:
        print("\n⚠️  Some benchmarks did not reach 3x target.")
        print("   This may be expected if DB is on localhost or network is fast.")
    else:
        print("\n✅ All benchmarks passed (≥3x speedup)")

    return all_passed


if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
