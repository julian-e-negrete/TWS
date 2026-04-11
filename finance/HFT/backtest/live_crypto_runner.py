"""
Live strategy runner — re-runs BT-12 crypto strategies on latest binance_ticks data
every INTERVAL minutes and pushes results to Pushgateway.
Runs as a systemd service; no WebSocket needed — reads from DB on 244.
"""
import time
from finance.HFT.backtest.bt12_extended import run_crypto
from finance.utils.logger import logger

INTERVAL = 60  # seconds between runs


def main():
    logger.info("Live crypto strategy runner started (interval={s}s)", s=INTERVAL)
    while True:
        try:
            logger.info("Running crypto strategies on latest data...")
            run_crypto()
        except Exception as e:
            logger.error("Live runner error: {e}", e=e)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
