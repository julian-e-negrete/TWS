"""
Async Binance WebSocket monitor using asyncio.
Replaces ThreadedWebsocketManager with native async streams.
Supports multiple concurrent symbols.

Streams per symbol:
  - kline (1m)   → data_map[symbol]: DataFrame of OHLCV bars
  - aggTrade     → trades_map[symbol]: deque of last 1000 trades
                   each trade: {price, qty, is_buyer_maker, timestamp}
"""

import asyncio
from collections import deque

import pandas as pd
from binance import AsyncClient, BinanceSocketManager

from finance.utils.logger import logger
from finance.BINANCE.monitor.indicators import compute_rsi
from finance.config import settings
from finance.monitoring.metrics import BINANCE_TICKS, BINANCE_PRICE, BINANCE_RSI, BINANCE_VOLUME
from finance.BINANCE.mq_publisher import publish_tick

INTERVAL = "1m"
LOOKBACK = 100
TRADE_WINDOW = 1000  # rolling trades kept in memory


class AsyncBinanceMonitor:
    def __init__(self, symbols: list[str]):
        self.symbols = symbols
        self.data_map: dict[str, pd.DataFrame] = {s: pd.DataFrame() for s in symbols}
        # Rolling deque of raw aggTrade dicts per symbol
        self.trades_map: dict[str, deque] = {s: deque(maxlen=TRADE_WINDOW) for s in symbols}
        self._tasks: list[asyncio.Task] = []

    async def _stream_kline(self, client: AsyncClient, symbol: str):
        bm = BinanceSocketManager(client)
        while True:
            try:
                async with bm.kline_socket(symbol=symbol.lower(), interval=INTERVAL) as stream:
                    logger.info("Kline stream started for {symbol}", symbol=symbol)
                    while True:
                        msg = await stream.recv()
                        await self._process_kline(msg, symbol)
            except Exception as e:
                logger.warning("Kline stream error for {s}, reconnecting: {e}", s=symbol, e=e)
                await asyncio.sleep(5)

    async def _stream_trades(self, client: AsyncClient, symbol: str):
        bm = BinanceSocketManager(client)
        while True:
            try:
                async with bm.aggtrade_socket(symbol=symbol.lower()) as stream:
                    logger.info("aggTrade stream started for {symbol}", symbol=symbol)
                    while True:
                        msg = await stream.recv()
                        self._process_trade(msg, symbol)
            except Exception as e:
                logger.warning("aggTrade stream error for {s}, reconnecting: {e}", s=symbol, e=e)
                await asyncio.sleep(5)

    def _process_trade(self, msg: dict, symbol: str):
        """Append aggTrade to rolling deque."""
        if msg.get('e') != 'aggTrade':
            return
        self.trades_map[symbol].append({
            'price':           float(msg['p']),
            'qty':             float(msg['q']),
            'is_buyer_maker':  bool(msg['m']),   # True = sell aggressor, False = buy aggressor
            'timestamp':       pd.to_datetime(msg['T'], unit='ms', utc=True),
        })

    async def _process_kline(self, msg: dict, symbol: str):
        if msg.get("e") != "kline":
            return
        k = msg["k"]
        new_row = {
            "timestamp": pd.to_datetime(k["t"], unit="ms", utc=True),
            "open":   float(k["o"]),
            "high":   float(k["h"]),
            "low":    float(k["l"]),
            "close":  float(k["c"]),
            "volume": float(k["v"]),
        }
        df = self.data_map[symbol]
        df = pd.concat([df, pd.DataFrame([new_row])]).drop_duplicates(subset="timestamp").tail(LOOKBACK)
        self.data_map[symbol] = df

        logger.info("{symbol} close={close} rows={n}", symbol=symbol, close=new_row["close"], n=len(df))

        BINANCE_TICKS.labels(symbol=symbol).inc()
        BINANCE_PRICE.labels(symbol=symbol).set(new_row["close"])
        BINANCE_VOLUME.labels(symbol=symbol).set(new_row["volume"])

        publish_tick(symbol, new_row)

        if len(df) >= 14:
            rsi = compute_rsi(df)
            BINANCE_RSI.labels(symbol=symbol).set(rsi)

    async def start(self):
        client = await AsyncClient.create(
            api_key=settings.binance.api_key,
            api_secret=settings.binance.secret_key,
        )
        try:
            self._tasks = []
            for symbol in self.symbols:
                self._tasks.append(asyncio.create_task(self._stream_kline(client, symbol)))
                self._tasks.append(asyncio.create_task(self._stream_trades(client, symbol)))
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            logger.info("Monitor cancelled — shutting down")
        finally:
            await client.close_connection()
            logger.info("Binance client closed")

    def stop(self):
        for task in self._tasks:
            task.cancel()
