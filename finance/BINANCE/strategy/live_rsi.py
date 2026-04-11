"""
BT-14: Live RSI mean-reversion strategy on BTCUSDT.
Consumes from AsyncBinanceMonitor.data_map, pushes signals + running P&L to Pushgateway.
Buy when RSI < 30, sell when RSI > 70. Simulated (no real orders).
"""
import asyncio
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway
from finance.BINANCE.monitor.indicators import compute_rsi
from finance.utils.logger import logger

SYMBOL = "BTCUSDT"
PUSHGATEWAY = "localhost:9091"


class LiveRSIStrategy:
    def __init__(self, data_map: dict):
        self._data_map = data_map
        self._position = 0       # 1 = long, 0 = flat
        self._entry_price = 0.0
        self._pnl = 0.0

    def _push(self, signal: str, price: float):
        reg = CollectorRegistry()
        Gauge("algotrading_live_signal", "", ["symbol", "signal"], registry=reg)\
            .labels(symbol=SYMBOL, signal=signal).set(price)
        Gauge("algotrading_live_pnl", "", ["symbol"], registry=reg)\
            .labels(symbol=SYMBOL).set(self._pnl)
        push_to_gateway(PUSHGATEWAY, job="live_strategy",
                        grouping_key={"symbol": SYMBOL}, registry=reg)

    def on_tick(self):
        df = self._data_map.get(SYMBOL)
        if df is None or len(df) < 14:
            return
        rsi = compute_rsi(df)
        price = float(df["close"].iloc[-1])

        if rsi < 30 and self._position == 0:
            self._position = 1
            self._entry_price = price
            logger.info("LIVE BUY {s} @ {p:.2f} RSI={r:.1f}", s=SYMBOL, p=price, r=rsi)
            self._push("BUY", price)

        elif rsi > 70 and self._position == 1:
            self._pnl += price - self._entry_price
            self._position = 0
            logger.info("LIVE SELL {s} @ {p:.2f} RSI={r:.1f} PnL={pnl:.2f}",
                        s=SYMBOL, p=price, r=rsi, pnl=self._pnl)
            self._push("SELL", price)

    async def run(self, interval: float = 60.0):
        """Poll data_map every interval seconds."""
        while True:
            try:
                self.on_tick()
            except Exception as e:
                logger.error("LiveRSIStrategy error: {e}", e=e)
            await asyncio.sleep(interval)
