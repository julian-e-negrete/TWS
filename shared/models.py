# T-ERR-2 / SPEC §2.2 — pydantic models for all 5 DB tables
from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, field_validator


class Tick(BaseModel):
    time: datetime
    instrument: str
    bid_volume: int
    bid_price: Decimal
    ask_price: Decimal
    ask_volume: int
    last_price: Decimal
    total_volume: int
    low: Decimal
    high: Decimal
    prev_close: Decimal


class Order(BaseModel):
    instrument: str
    time: datetime
    price: Decimal
    volume: int
    side: str

    @field_validator("side")
    @classmethod
    def side_must_be_bs(cls, v):
        if v not in ("B", "S"):
            raise ValueError(f"side must be 'B' or 'S', got {v!r}")
        return v


class Cookie(BaseModel):
    time: datetime
    name: str
    value: str


class BinanceTick(BaseModel):
    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


class BinanceTrade(BaseModel):
    time: datetime
    symbol: str
    price: Decimal
    qty: Decimal
    is_buyer_maker: bool
    trade_id: int


class MarketData(BaseModel):
    ticker: str
    timestamp: datetime
    last_price: Decimal
    volume: int
