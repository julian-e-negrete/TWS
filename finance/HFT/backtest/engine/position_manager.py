from finance.utils.logger import logger
from finance.HFT.backtest.types import (
    Direction, OrderType, OrderBookSnapshot, MarketTrade, StrategyTrade
)
from typing import List, Optional
import pandas as pd


class PositionManager:
    """Tracks positions, entry prices, entry times and cooldowns per instrument."""

    def __init__(self, instrument_multipliers: dict):
        self.multipliers = instrument_multipliers
        self.position: dict = {}
        self.entry_price: dict = {}
        self.entry_time: dict = {}
        self.last_close_time: dict = {}

    def get(self, instrument: str) -> int:
        return self.position.get(instrument, 0)

    def update(self, instrument: str, delta: int, price: float, timestamp: pd.Timestamp):
        prev = self.position.get(instrument, 0)
        self.position[instrument] = prev + delta
        if self.position[instrument] != 0 and prev == 0:
            self.entry_price[instrument] = price
            self.entry_time[instrument] = timestamp
        if self.position[instrument] == 0:
            self.entry_time[instrument] = None
            self.last_close_time[instrument] = timestamp

    def unrealized_pnl(self, instrument: str, market_price: float) -> float:
        pos = self.position.get(instrument, 0)
        if pos == 0:
            return 0.0
        mult = self.multipliers[instrument]
        entry = self.entry_price.get(instrument, market_price)
        return (market_price - entry) * pos * mult if pos > 0 else (entry - market_price) * abs(pos) * mult
