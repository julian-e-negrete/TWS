from dataclasses import dataclass, field
from enum import Enum, auto
import pandas as pd


class OrderType(Enum):
    MARKET = auto()
    LIMIT = auto()
    STOP = auto()


class Direction(Enum):
    BUY = auto()
    SELL = auto()


@dataclass
class MarketTrade:
    timestamp: pd.Timestamp
    price: float
    volume: int
    direction: Direction
    instrument: str


@dataclass
class OrderBookSnapshot:
    timestamp: pd.Timestamp
    bid_price: float
    ask_price: float
    bid_volume: int
    ask_volume: int
    instrument: str


@dataclass
class StrategyTrade:
    timestamp: pd.Timestamp
    price: float
    volume: int
    direction: Direction
    order_type: OrderType
    trade_id: int
    instrument: str
    profit: float = 0
    closed: bool = False
