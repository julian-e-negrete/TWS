import asyncio
import signal
import sys
import os

from finance.BINANCE.monitor.data_stream_async import AsyncBinanceMonitor
from finance.utils.logger import logger
from finance.monitoring.metrics import start_metrics_server

SYMBOLS = ["USDTARS", "BTCUSDT"]
METRICS_PORT = 8003


async def main():
    start_metrics_server(port=METRICS_PORT)
    monitor = AsyncBinanceMonitor(symbols=SYMBOLS)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, monitor.stop)

    await monitor.start()


if __name__ == "__main__":
    os.system("clear")
    asyncio.run(main())
