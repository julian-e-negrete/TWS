from finance.utils.logger import logger
from finance.HFT.backtest.types import (
    Direction, OrderType, OrderBookSnapshot, MarketTrade, StrategyTrade
)
from finance.HFT.backtest.engine.position_manager import PositionManager
from typing import List, Optional
import pandas as pd
import math


COMMISSION_RATE = 0.0027  # 0.25% arancel + 0.02% derechos (Eco Valores, Futuros Dólar)
MAX_FUTURES_POSITION = 2


class OrderExecutor:
    """Executes strategy orders against the order book or last trade price."""

    def __init__(self, position_manager: PositionManager, initial_capital: float):
        self.pm = position_manager
        self.initial_capital = initial_capital
        self.cash: float = initial_capital
        self.trade_id_counter: int = 0
        self.strategy_trades: List[StrategyTrade] = []
        self.skipped_trades: int = 0
        self.signal_stats = {
            'no_recent_trades': 0, 'spread_too_wide': 0, 'no_momentum': 0,
            'no_trend': 0, 'cooldown': 0, 'insufficient_capital': 0,
            'low_volume': 0, 'no_order_book': 0,
        }

    def execute(self, signal: dict, price: float, timestamp: pd.Timestamp) -> Optional[StrategyTrade]:
        instrument = signal['instrument']
        multiplier = self.pm.multipliers[instrument]
        max_vol = 2000 if 'bm_MERV_GFGC' in instrument else MAX_FUTURES_POSITION
        volume = max(1, min(int(signal['volume']), max_vol))

        if signal['order_type'] == OrderType.LIMIT and 'price' in signal and signal['price']:
            price = signal['price']

        trade_value = price * volume * multiplier
        commission = trade_value * COMMISSION_RATE
        cash_flow = (-trade_value if signal['direction'] == Direction.BUY else trade_value) - commission

        if signal['direction'] == Direction.BUY and self.cash + cash_flow < 0:
            logger.info("Insufficient capital for BUY: Need ${need:,.2f}, Have ${have:,.2f}",
                        need=abs(cash_flow), have=self.cash)
            self.skipped_trades += 1
            self.signal_stats['insufficient_capital'] += 1
            return None

        current_pos = self.pm.get(instrument)
        new_pos = current_pos + (volume if signal['direction'] == Direction.BUY else -volume)
        if 'rx_DDF_DLR' in instrument and abs(new_pos) > MAX_FUTURES_POSITION:
            self.skipped_trades += 1
            self.signal_stats['insufficient_capital'] += 1
            return None

        self.trade_id_counter += 1
        delta = volume if signal['direction'] == Direction.BUY else -volume
        profit = 0.0
        closed = False

        if (current_pos > 0 and signal['direction'] == Direction.SELL) or \
           (current_pos < 0 and signal['direction'] == Direction.BUY):
            closed_vol = min(abs(current_pos), volume)
            profit = (price - self.pm.entry_price.get(instrument, price)) * closed_vol * multiplier * \
                     (1 if current_pos > 0 else -1)
            closed = True

        trade = StrategyTrade(
            timestamp=timestamp, price=price, volume=volume,
            direction=signal['direction'], order_type=signal['order_type'],
            trade_id=self.trade_id_counter, instrument=instrument,
            profit=profit, closed=closed,
        )
        self.pm.update(instrument, delta, price, timestamp)
        self.cash += cash_flow
        self.strategy_trades.append(trade)

        logger.debug("Execute {dir} {instr} @ {price:.2f} vol={vol} commission={comm:.2f} profit={profit:.2f}",
                    dir=signal['direction'].name, instr=instrument, price=price,
                    vol=volume, comm=commission, profit=profit)
        return trade
