from finance.HFT.backtest.db.load_data import load_order_data, load_tick_data
from finance.HFT.backtest.db.insert_data import insert_data

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import List, Optional
import matplotlib.pyplot as plt
from enum import Enum, auto
import math


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


class MarketDataBacktester:
    def __init__(self, initial_capital: float = 2000000):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.position = {}
        self.entry_price = {}
        self.entry_time = {}
        self.last_close_time = {}
        self.strategy_trades: List[StrategyTrade] = []
        self.market_trades: List[MarketTrade] = []
        self.order_book_snapshots: List[OrderBookSnapshot] = []
        self.current_time = None
        self.trade_id_counter = 0
        self.pnl_history = []
        self.skipped_trades = 0
        self.signal_stats = {
            'no_recent_trades': 0,
            'spread_too_wide': 0,
            'no_momentum': 0,
            'no_trend': 0,
            'cooldown': 0,
            'insufficient_capital': 0,
            'low_volume': 0,
            'no_order_book': 0
        }
        self.instrument_multipliers = {}

    def load_market_data(self, trades_df: pd.DataFrame, orderbook_df: pd.DataFrame):
        required_trade_cols = ['time', 'price', 'volume', 'side', 'instrument']
        required_ob_cols = ['time', 'bid_price', 'ask_price', 'bid_volume', 'instrument']
        
        if trades_df.empty:
            print("Warning: trades_df is empty")
        else:
            if not all(col in trades_df.columns for col in required_trade_cols):
                raise ValueError(f"trades_df missing required columns: {required_trade_cols}")
            if trades_df[required_trade_cols].isnull().any().any():
                raise ValueError("trades_df contains null values")
        
        if orderbook_df.empty:
            print("Warning: orderbook_df is empty")
        else:
            if not all(col in orderbook_df.columns for col in required_ob_cols):
                raise ValueError(f"orderbook_df missing required columns: {required_ob_cols}")
            if orderbook_df[required_ob_cols].isnull().any().any():
                raise ValueError("orderbook_df contains null values")
        
        trades_df['instrument'] = trades_df['instrument'].str.replace('M:', '')
        
        orderbook_df['instrument'] = orderbook_df['instrument'].str.replace('M:', '')
        
        duplicates = orderbook_df[['time', 'instrument']].duplicated().sum() 
        if duplicates > 0:
            print(f"Warning: Aggregating {duplicates} duplicate timestamps in orderbook_df")
            orderbook_df = orderbook_df.groupby(['time', 'instrument']).agg({
                'bid_price': 'mean',
                'ask_price': 'mean',
                'bid_volume': 'sum',
                'ask_volume': 'sum'
            }).reset_index()
        
        def get_multiplier(instrument):
            if 'rx_DDF_DLR' in instrument:
                return 1000
            elif 'bm_MERV_GFGC' in instrument:
                # Updated: Assume 100 for all GFGC instruments, including options
                return 100
            else:
                return None
        
        self.instrument_multipliers = {
            instr: get_multiplier(instr) for instr in trades_df['instrument'].unique() 
            if get_multiplier(instr) is not None
        }
        
        print(f"Available instruments in trades_df: {list(trades_df['instrument'].unique())}")
        print(f"Valid instruments with multipliers: {list(self.instrument_multipliers.keys())}")
        
        
        print(f"Available instruments in orderbook_df: {list(orderbook_df['instrument'].unique())}")
        print(f"orderbook_df head:\n{orderbook_df.head(10)}")
    
        def infer_direction(row, recent_trades):
            if row['side'] in ['B', 'S']:
                return Direction.BUY if row['side'] == 'B' else Direction.SELL
            if row['side'] == 'U' and len(recent_trades) >= 1:
                ma = sum(t.price for t in recent_trades[-25:]) / min(len(recent_trades), 25)  # 25-period MA
                return Direction.BUY if row['price'] > ma else Direction.SELL
            return None
        
        self.market_trades = [
            MarketTrade(
                timestamp=row['time'],
                price=row['price'],
                volume=int(row['volume']),
                direction=infer_direction(row, self._get_recent_trades(row['instrument'], lookback='5min')),
                instrument=row['instrument']
            ) for _, row in trades_df.iterrows() if row['instrument'] in self.instrument_multipliers
        ]
        
        self.order_book_snapshots = [
            OrderBookSnapshot(
                timestamp=row['time'],
                bid_price=row['bid_price'],
                ask_price=row['ask_price'],
                bid_volume=int(row['bid_volume']),
                ask_volume=int(row.get('ask_volume', row['bid_volume'])),
                instrument=row['instrument']
            ) for _, row in orderbook_df.iterrows() if row['instrument'] in self.instrument_multipliers
        ]
        
        self.market_trades.sort(key=lambda x: x.timestamp)
        self.order_book_snapshots.sort(key=lambda x: x.timestamp)
        
        print("\n=== DATA VALIDATION ===")
        for instr in self.instrument_multipliers:
            trades = [t for t in self.market_trades if t.instrument == instr]
            snapshots = [s for s in self.order_book_snapshots if s.instrument == instr]
            print(f"\nInstrument: {instr}")
            print(f"Multiplier: {self.instrument_multipliers[instr]}")
            print(f"Trades: {len(trades)} records")
            print(f"Order book: {len(snapshots)} records")
            if trades:
                print(f"Time range: {min(t.timestamp for t in trades)} to {max(t.timestamp for t in trades)}")
                print(f"Trade frequency: {len(trades) / ((trades[-1].timestamp - trades[0].timestamp).total_seconds() / 3600):.2f} trades/hour")
                print(f"Trade prices: {min(t.price for t in trades):.2f}-{max(t.price for t in trades):.2f}")
            if snapshots:
                print(f"Bid prices: {min(s.bid_price for s in snapshots):.2f}-{max(s.bid_price for s in snapshots):.2f}")
                print(f"Ask prices: {min(s.ask_price for s in snapshots):.2f}-{max(s.ask_price for s in snapshots):.2f}")
            else:
                print(f"Warning: No order book snapshots available for {instr}")
            if trades:
                print(f"Trade volumes (contracts): {min(t.volume for t in trades)}-{max(t.volume for t in trades)}")
                print(f"Trade directions: {sum(1 for t in trades if t.direction == Direction.BUY)} buys, "
                      f"{sum(1 for t in trades if t.direction == Direction.SELL)} sells, "
                      f"{sum(1 for t in trades if t.direction is None)} unknown")
            else:
                print(f"Warning: No trade records available for {instr}")

    def run_backtest(self, strategy_func):
        if not self.order_book_snapshots:
            print("Warning: No order book snapshots; running trade-only backtest")
            return self.run_trade_only_backtest(strategy_func)
        
        combined_timeline = self._create_combined_timeline()
        print(f"\nTimeline contains {len(combined_timeline)} events")
        
        for event in combined_timeline:
            self.current_time = event['timestamp']
            if event['type'] == 'trade':
                self._process_market_trade(event['data'])
                current_ob = self._get_latest_orderbook(self.current_time, event['data'].instrument)
                if current_ob:
                    self._update_pnl(current_ob)
            elif event['type'] == 'orderbook':
                current_ob = event['data']
                signals = strategy_func(
                    current_market=current_ob,
                    recent_trades=self._get_recent_trades(current_ob.instrument),
                    current_position=self.position,
                    current_cash=self.cash
                )
                for signal in signals:
                    self._execute_strategy_order(signal, current_ob)
                self._update_pnl(current_ob)
        
        for instrument in self.position:
            if self.position[instrument] != 0:
                print(f"\nClosing open position for {instrument} at end of backtest")
                final_ob = next((ob for ob in reversed(self.order_book_snapshots) if ob.instrument == instrument), None)
                if final_ob:
                    close_direction = Direction.SELL if self.position[instrument] > 0 else Direction.BUY
                    close_volume = abs(self.position[instrument])
                    close_signal = {
                        'direction': close_direction,
                        'volume': close_volume,
                        'order_type': OrderType.MARKET,
                        'instrument': instrument
                    }
                    self._execute_strategy_order(close_signal, final_ob)
                    self._update_pnl(final_ob)
        
        net_profit = self.cash - self.initial_capital
        if net_profit > 20000 * 1330:  # Apply tax only above $20,000 USD
            taxable_profit = net_profit - 20000
            tax = taxable_profit * 0.15  # 15% capital gains tax
            print(f"\nApplying capital gains tax: ${tax:.2f} on taxable profit ${taxable_profit:.2f}")
            self.cash -= tax

    def run_trade_only_backtest(self, strategy_func):
        print("\nRunning trade-only backtest due to missing order book data")
        for trade in self.market_trades:
            self.current_time = trade.timestamp
            self._process_market_trade(trade)
            signals = strategy_func(
                current_market=None,
                recent_trades=self._get_recent_trades(trade.instrument),
                current_position=self.position,
                current_cash=self.cash
            )
            for signal in signals:
                self._execute_trade_only_order(signal, trade)
            self._update_pnl_trade_only(trade)
        
        for instrument in self.position:
            if self.position[instrument] != 0:
                print(f"\nClosing open position for {instrument} at end of backtest")
                final_trade = next((t for t in reversed(self.market_trades) if t.instrument == instrument), None)
                if final_trade:
                    close_direction = Direction.SELL if self.position[instrument] > 0 else Direction.BUY
                    close_volume = abs(self.position[instrument])
                    close_signal = {
                        'direction': close_direction,
                        'volume': close_volume,
                        'order_type': OrderType.MARKET,
                        'instrument': instrument
                    }
                    self._execute_trade_only_order(close_signal, final_trade)
                    self._update_pnl_trade_only(final_trade)
        
        net_profit = self.cash - self.initial_capital
        if net_profit > 20000 * 1330:  # Apply tax only above $20,000 USD
            taxable_profit = net_profit - 20000
            tax = taxable_profit * 0.15  # 15% capital gains tax
            print(f"\nApplying capital gains tax: ${tax:.2f} on taxable profit ${taxable_profit:.2f}")
            self.cash -= tax

    def _create_combined_timeline(self):
        timeline = []
        for trade in self.market_trades:
            timeline.append({
                'timestamp': trade.timestamp,
                'type': 'trade',
                'data': trade
            })
        for ob in self.order_book_snapshots:
            timeline.append({
                'timestamp': ob.timestamp,
                'type': 'orderbook',
                'data': ob
            })
        timeline.sort(key=lambda x: x['timestamp'])
        return timeline

    def _get_latest_orderbook(self, timestamp, instrument):
        for ob in reversed(self.order_book_snapshots):
            if ob.timestamp <= timestamp and ob.instrument == instrument:
                return ob
        return None

    def _get_recent_trades(self, instrument, lookback='10min'):
        if not self.current_time:
            return []
        cutoff = self.current_time - pd.Timedelta(lookback)
        trades = [t for t in self.market_trades if t.timestamp >= cutoff and 
                  t.timestamp <= self.current_time and t.instrument == instrument]
        return trades

    def _execute_strategy_order(self, signal: dict, order_book: OrderBookSnapshot):
        instrument = signal['instrument']
        multiplier = self.instrument_multipliers[instrument]
        volume = max(1, min(int(signal['volume']), 2000 if 'bm_MERV_GFGC' in instrument else 2))  # Cap at 2 for futures/options

        # Honor limit price if provided
        if signal['order_type'] == OrderType.LIMIT and 'price' in signal:
            price = signal['price']
        else:
            price = order_book.ask_price if signal['direction'] == Direction.BUY else order_book.bid_price

        trade_value = price * volume * multiplier
        # Fixed commission 0.5% of trade
        commission = trade_value * 0.005
        fees = 0
        total_fees = commission + fees
        cash_flow = -trade_value if signal['direction'] == Direction.BUY else trade_value
        cash_flow -= total_fees
        
        if signal['direction'] == Direction.BUY and self.cash + cash_flow < 0:
            print(f"Insufficient capital for BUY: Need ${abs(cash_flow):,.2f}, Available ${self.cash:,.2f}")
            self.skipped_trades += 1
            self.signal_stats['insufficient_capital'] += 1
            return
        
        current_position = self.position.get(instrument, 0)
        new_position = current_position + (volume if signal['direction'] == Direction.BUY else -volume)
        if 'rx_DDF_DLR' in instrument and abs(new_position) > 2:
            print(f"Position limit exceeded for {instrument}: Current {current_position}, Requested {new_position}")
            self.skipped_trades += 1
            self.signal_stats['insufficient_capital'] += 1
            return
        
        self.trade_id_counter += 1
        trade = StrategyTrade(
            timestamp=self.current_time,
            price=price,
            volume=volume,
            direction=signal['direction'],
            order_type=signal['order_type'],
            trade_id=self.trade_id_counter,
            instrument=instrument
        )
        
        if (current_position > 0 and signal['direction'] == Direction.SELL) or \
           (current_position < 0 and signal['direction'] == Direction.BUY):
            closed_volume = min(abs(current_position), volume)
            profit = (price - self.entry_price.get(instrument, price)) * closed_volume * multiplier * \
                     (1 if current_position > 0 else -1)
            trade.profit = profit
            trade.closed = True
        
        self.position[instrument] = new_position
        self.cash += cash_flow
        
        if (self.position[instrument] > 0 and signal['direction'] == Direction.BUY) or \
           (self.position[instrument] < 0 and signal['direction'] == Direction.SELL):
            self.entry_price[instrument] = price
            self.entry_time[instrument] = self.current_time
        
        if self.position[instrument] == 0:
            self.entry_time[instrument] = None
            self.last_close_time[instrument] = self.current_time
        
        self.strategy_trades.append(trade)
        print(f"\nExecuting {signal['direction'].name} at {order_book.timestamp} ({instrument}): "
              f"Price ${price:.2f}, Volume {volume}, Commission ${commission:.2f}, Fees ${fees:.2f}")
        print(f"New position ({instrument}): {self.position[instrument]}, Cash: ${self.cash:,.2f}, "
              f"Profit: ${trade.profit:,.2f}")

    def _execute_trade_only_order(self, signal: dict, trade: MarketTrade):
        instrument = signal['instrument']
        multiplier = self.instrument_multipliers[instrument]
        volume = max(1, min(int(signal['volume']), 2000 if 'bm_MERV_GFGC' in instrument else 2))

        if signal['order_type'] == OrderType.LIMIT and 'price' in signal:
            price = signal['price']
        else:
            price = trade.price

        trade_value = price * volume * multiplier
        commission = volume * 5.0
        fees = volume * 0.20
        total_fees = commission + fees
        cash_flow = -trade_value if signal['direction'] == Direction.BUY else trade_value
        cash_flow -= total_fees
        
        if signal['direction'] == Direction.BUY and self.cash + cash_flow < 0:
            print(f"Insufficient capital for BUY: Need ${abs(cash_flow):,.2f}, Available ${self.cash:,.2f}")
            self.skipped_trades += 1
            self.signal_stats['insufficient_capital'] += 1
            return
        
        current_position = self.position.get(instrument, 0)
        new_position = current_position + (volume if signal['direction'] == Direction.BUY else -volume)
        if 'rx_DDF_DLR' in instrument and abs(new_position) > 2:
            print(f"Position limit exceeded for {instrument}: Current {current_position}, Requested {new_position}")
            self.skipped_trades += 1
            self.signal_stats['insufficient_capital'] += 1
            return
        
        self.trade_id_counter += 1
        strategy_trade = StrategyTrade(
            timestamp=self.current_time,
            price=price,
            volume=volume,
            direction=signal['direction'],
            order_type=signal['order_type'],
            trade_id=self.trade_id_counter,
            instrument=instrument
        )
        
        if (current_position > 0 and signal['direction'] == Direction.SELL) or \
           (current_position < 0 and signal['direction'] == Direction.BUY):
            closed_volume = min(abs(current_position), volume)
            profit = (price - self.entry_price.get(instrument, price)) * closed_volume * multiplier * \
                     (1 if current_position > 0 else -1)
            strategy_trade.profit = profit
            strategy_trade.closed = True
        
        self.position[instrument] = new_position
        self.cash += cash_flow
        
        if (self.position[instrument] > 0 and signal['direction'] == Direction.BUY) or \
           (self.position[instrument] < 0 and signal['direction'] == Direction.SELL):
            self.entry_price[instrument] = price
            self.entry_time[instrument] = self.current_time
        
        if self.position[instrument] == 0:
            self.entry_time[instrument] = None
            self.last_close_time[instrument] = self.current_time
        
        self.strategy_trades.append(strategy_trade)
        print(f"\nExecuting {signal['direction'].name} at {trade.timestamp} ({instrument}): "
              f"Price ${price:.2f}, Volume {volume}, Commission ${commission:.2f}, Fees ${fees:.2f}")
        print(f"New position ({instrument}): {self.position[instrument]}, Cash: ${self.cash:,.2f}, "
              f"Profit: ${strategy_trade.profit:,.2f}")

    def _process_market_trade(self, trade: MarketTrade):
        pass

    def _update_pnl(self, order_book: OrderBookSnapshot):
        instrument = order_book.instrument
        multiplier = self.instrument_multipliers[instrument]
        position = self.position.get(instrument, 0)
        if position == 0:
            market_value = 0
        elif position > 0:
            market_value = order_book.bid_price * position * multiplier
        else:
            market_value = order_book.ask_price * position * multiplier
        
        self.pnl_history.append({
            'timestamp': self.current_time,
            'instrument': instrument,
            'total_value': self.cash + market_value,
            'position': position,
            'cash': self.cash,
            'market_value': market_value
        })

    def _update_pnl_trade_only(self, trade: MarketTrade):
        instrument = trade.instrument
        multiplier = self.instrument_multipliers[instrument]
        position = self.position.get(instrument, 0)
        market_value = trade.price * position * multiplier
        
        self.pnl_history.append({
            'timestamp': self.current_time,
            'instrument': instrument,
            'total_value': self.cash + market_value,
            'position': position,
            'cash': self.cash,
            'market_value': market_value
        })

    def _calculate_unrealized_pnl(self, current_market: Optional[OrderBookSnapshot], trade: Optional[MarketTrade]) -> float:
        if current_market:
            instrument = current_market.instrument
            multiplier = self.instrument_multipliers[instrument]
            position = self.position.get(instrument, 0)
            if position == 0:
                return 0.0
            return ((current_market.bid_price - self.entry_price.get(instrument, current_market.bid_price)) * 
                    position * multiplier if position > 0 else 
                    (self.entry_price.get(instrument, current_market.ask_price) - current_market.ask_price) * 
                    abs(position) * multiplier)
        elif trade:
            instrument = trade.instrument
            multiplier = self.instrument_multipliers[instrument]
            position = self.position.get(instrument, 0)
            if position == 0:
                return 0.0
            return ((trade.price - self.entry_price.get(instrument, trade.price)) * 
                    position * multiplier if position > 0 else 
                    (self.entry_price.get(instrument, trade.price) - trade.price) * 
                    abs(position) * multiplier)
        return 0.0

    def debug_strategy(self, current_market: Optional[OrderBookSnapshot], recent_trades: List[MarketTrade], 
                      current_position: dict, current_cash: float):
        signals = []
        instrument = current_market.instrument if current_market else recent_trades[-1].instrument if recent_trades else None
        if not instrument:
            self.signal_stats['no_recent_trades'] += 1
            print(f"No signal: No instrument (recent_trades: {len(recent_trades)})")
            return signals
        
        multiplier = self.instrument_multipliers[instrument]
        max_risk = 0.1 * self.initial_capital if 'bm_MERV_GFGC' in instrument else 0.68 * self.initial_capital
        cooldown = pd.Timedelta(seconds=30) if 'rx_DDF_DLR' in instrument else pd.Timedelta(minutes=3)
        
        if current_market:
            spread = current_market.ask_price - current_market.bid_price
            mid_price = (current_market.bid_price + current_market.ask_price) / 2
            price = mid_price
            volume = max(1, min(math.floor(max_risk / (current_market.ask_price * multiplier)), 
                                2000 if 'bm_MERV_GFGC' in instrument else 2))
        else:
            spread = None
            last_trade = recent_trades[-1]
            price = last_trade.price
            volume = max(1, min(math.floor(max_risk / (last_trade.price * multiplier)), 
                                2000 if 'bm_MERV_GFGC' in instrument else 2))
        
        print(f"\nTime: {self.current_time} ({instrument})")
        if current_market:
            print(f"Bid/Ask: {current_market.bid_price:.2f}/{current_market.ask_price:.2f}")
            print(f"Spread: {spread:.4f} ({spread/mid_price*10000:.1f} bps)")
        else:
            print(f"Trade price: {price:.2f} (no order book)")
        print(f"Position: {current_position.get(instrument, 0)}, Cash: ${current_cash:,.2f}")
        print(f"Recent trades: {len(recent_trades)}")
        if recent_trades:
            print(f"Recent trade prices: {[t.price for t in recent_trades[-5:]]}")
            print(f"Recent trade volumes: {[t.volume for t in recent_trades[-5:]]}")
        print(f"Calculated volume: {volume} contracts")
        
        # Estimate volatility (std dev proxy for ATR) from recent prices
        if len(recent_trades) >= 10:
            recent_prices = [t.price for t in recent_trades[-50:]]  # Up to 50 for better estimate
            atr_proxy = np.std(recent_prices) * 1.5  # Rough ATR scaling
        else:
            atr_proxy = 1.0  # Default low vol

        # Exit signals
        if current_position.get(instrument, 0) != 0 and self.entry_time.get(instrument) is not None:
            unrealized_pnl = self._calculate_unrealized_pnl(current_market, recent_trades[-1] if recent_trades else None)
            pnl_pct = unrealized_pnl / self.initial_capital * 100
            # Dynamic thresholds based on vol; widen SL to -1%, TP to 2%
            exit_threshold = 1.0 + (atr_proxy / price) * 100  # Vol-adjusted
            if (pnl_pct < -exit_threshold or pnl_pct > exit_threshold * 2 or 
                (self.current_time - self.entry_time[instrument]) > pd.Timedelta(minutes=5)):
                print(f"Exit triggered: Stop-loss (-{exit_threshold}%), take-profit ({exit_threshold*2}%), or time-based (5min)")
                # Use LIMIT at mid for time-based exits (if not SL/TP)
                is_time_exit = (self.current_time - self.entry_time[instrument]) > pd.Timedelta(minutes=5)
                order_type = OrderType.LIMIT if is_time_exit else OrderType.MARKET
                exit_price = mid_price if is_time_exit and current_market else None
                signals.append({
                    'direction': Direction.SELL if current_position[instrument] > 0 else Direction.BUY,
                    'volume': abs(current_position[instrument]),
                    'order_type': order_type,
                    'instrument': instrument,
                    'price': exit_price if exit_price else None
                })
                return signals
        
        # Cooldown check
        if self.last_close_time.get(instrument) is not None and \
           (self.current_time - self.last_close_time[instrument]) < cooldown:
            print(f"No signal: Cooldown period ({cooldown})")
            self.signal_stats['cooldown'] += 1
            return signals
        
        # Entry signals
        if len(recent_trades) >= 10:
            last_trade = recent_trades[-1]
            ma = sum(t.price for t in recent_trades[-50:]) / min(len(recent_trades), 50)
            price_dev_pct = abs(last_trade.price - ma) / ma * 100
            trend_up = last_trade.price > ma and last_trade.volume > 50 and price_dev_pct > 0.1
            trend_down = last_trade.price < ma and last_trade.volume > 50 and price_dev_pct > 0.1
            spread_threshold = 0.20 if 'bm_MERV_GFGC' in instrument else 0.003
            
            if current_market and (spread is None or spread > mid_price * spread_threshold):
                print(f"No signal: Spread too wide ({spread/mid_price*100:.2f}% vs {spread_threshold*100:.2f}%)")
                self.signal_stats['spread_too_wide'] += 1
                self.signal_stats['no_order_book'] += 1
                return signals
            
            if trend_up:
                print(f"BUY signal triggered: Price {last_trade.price:.2f} > MA {ma:.2f}, Volume {last_trade.volume}, Dev {price_dev_pct:.2f}%")
                signals.append({
                    'direction': Direction.BUY,
                    'volume': volume,
                    'order_type': OrderType.MARKET if not current_market else OrderType.LIMIT,
                    'price': price if not current_market else current_market.bid_price + spread/2,
                    'instrument': instrument
                })
            elif trend_down:
                print(f"SELL signal triggered: Price {last_trade.price:.2f} < MA {ma:.2f}, Volume {last_trade.volume}, Dev {price_dev_pct:.2f}%")
                signals.append({
                    'direction': Direction.SELL,
                    'volume': volume,
                    'order_type': OrderType.MARKET if not current_market else OrderType.LIMIT,
                    'price': price if not current_market else current_market.ask_price - spread/2,
                    'instrument': instrument
                })
            else:
                if last_trade.volume <= 50:
                    print(f"No signal: Low trade volume ({last_trade.volume} <= 50)")
                    self.signal_stats['low_volume'] += 1
                if not (trend_up or trend_down):
                    print(f"No signal: No trend (Price {last_trade.price:.2f}, MA {ma:.2f}, Dev {price_dev_pct:.2f}%)")
                    self.signal_stats['no_trend'] += 1
                self.signal_stats['no_momentum'] += 1
        else:
            print("No signal: Insufficient recent trades")
            self.signal_stats['no_recent_trades'] += 1
        
        return signals

    def generate_report(self):
        if not self.pnl_history:
            print("Warning: No PnL history; generating limited report")
            trades_df = pd.DataFrame([{
                'timestamp': t.timestamp,
                'price': t.price,
                'volume': t.volume,
                'direction': t.direction.name,
                'type': t.order_type.name,
                'profit': t.profit,
                'closed': t.closed,
                'instrument': t.instrument
            } for t in self.strategy_trades])
            metrics = {
                'total_trades': len(trades_df[trades_df['closed']]),
                'skipped_trades': self.skipped_trades,
                'open_position': self.position,
                'final_cash': self.cash,
                'total_return_pct': (self.cash / self.initial_capital - 1) * 100,
                'signal_stats': self.signal_stats
            }
            if not trades_df.empty:
                winning = trades_df[trades_df['profit'] > 0]
                losing = trades_df[trades_df['profit'] < 0]
                metrics['win_rate_pct'] = len(winning) / len(trades_df[trades_df['closed']]) * 100 if len(trades_df[trades_df['closed']]) > 0 else 0
                metrics['avg_win'] = winning['profit'].mean() if len(winning) > 0 else 0
                metrics['avg_loss'] = losing['profit'].mean() if len(losing) > 0 else 0
            if not trades_df.empty:
                self._plot_results(pd.DataFrame(), trades_df)
            return metrics
        
        pnl_df = pd.DataFrame(self.pnl_history)
        trades_df = pd.DataFrame([{
            'timestamp': t.timestamp,
            'price': t.price,
            'volume': t.volume,
            'direction': t.direction.name,
            'type': t.order_type.name,
            'profit': t.profit,
            'closed': t.closed,
            'instrument': t.instrument
        } for t in self.strategy_trades])
        
        metrics = self._calculate_metrics(pnl_df, trades_df)
        self._plot_results(pnl_df, trades_df)
        
        metrics['analysis'] = self._diagnose_performance(pnl_df, trades_df, metrics)
        metrics['trade_count'] = len(trades_df[trades_df['closed']])
        metrics['skipped_trades'] = self.skipped_trades
        metrics['open_position'] = self.position
        metrics['unrealized_pnl'] = {instr: self._calculate_unrealized_pnl(
            next((ob for ob in reversed(self.order_book_snapshots) if ob.instrument == instr), None),
            next((t for t in reversed(self.market_trades) if t.instrument == instr), None)
        ) for instr in self.position if self.position.get(instr, 0) != 0}
        metrics['signal_stats'] = self.signal_stats
        metrics['avg_trade_frequency'] = (trades_df['timestamp'].diff().mean().total_seconds() / 60) if len(trades_df) > 1 else 0
        
        return metrics
    
    


    # Example usage:
    # metrics = generate_report()  # Your original function
    # print_report(metrics)        # This new pretty-print function

    def _diagnose_performance(self, pnl_df, trades_df, metrics):
        issues = []
        if len(trades_df) > 50:
            issues.append("High trade count - potential overtrading")
        if 'win_rate_pct' in metrics and metrics['win_rate_pct'] < 50:
            issues.append(f"Low win rate ({metrics['win_rate_pct']:.1f}%) - reconsider entry signals")
        if not pnl_df.empty:
            drawdown_duration = (pnl_df[pnl_df['drawdown'] == pnl_df['drawdown'].max()]['timestamp'].iloc[0] - 
                                pnl_df[pnl_df['total_value'] == pnl_df['total_value'].cummax().max()]['timestamp'].iloc[0])
            if drawdown_duration > pd.Timedelta(minutes=30):
                issues.append(f"Prolonged drawdown ({drawdown_duration}) - improve exit timing")
        return " | ".join(issues) if issues else "No major issues detected"

    def _calculate_metrics(self, pnl_df: pd.DataFrame, trades_df: pd.DataFrame):
        metrics = {}
        initial_value = pnl_df['total_value'].iloc[0]
        final_value = pnl_df['total_value'].iloc[-1]
        metrics['total_return_pct'] = (final_value / initial_value - 1) * 100
        days = max((pnl_df['timestamp'].iloc[-1] - pnl_df['timestamp'].iloc[0]).days, 1)
        metrics['annualized_return_pct'] = ((final_value / initial_value) ** (365.25/days) - 1) * 100
        pnl_df['peak'] = pnl_df['total_value'].cummax()
        pnl_df['drawdown'] = (pnl_df['peak'] - pnl_df['total_value']) / pnl_df['peak']
        metrics['max_drawdown_pct'] = pnl_df['drawdown'].max() * 100
        closed_trades = trades_df[trades_df['closed']]
        if not closed_trades.empty:
            winning = closed_trades[closed_trades['profit'] > 0]
            losing = closed_trades[closed_trades['profit'] < 0]
            metrics['total_trades'] = len(closed_trades)
            metrics['win_rate_pct'] = len(winning) / len(closed_trades) * 100 if len(closed_trades) > 0 else 0
            metrics['avg_win'] = winning['profit'].mean() if len(winning) > 0 else 0
            metrics['avg_loss'] = losing['profit'].mean() if len(losing) > 0 else 0
            metrics['profit_factor'] = winning['profit'].sum() / abs(losing['profit'].sum()) if len(losing) > 0 else float('inf')
            metrics['expectancy'] = (metrics['avg_win'] * (metrics['win_rate_pct']/100) + 
                                   metrics['avg_loss'] * (1 - metrics['win_rate_pct']/100))
        return metrics

    def _plot_results(self, pnl_df: pd.DataFrame, trades_df: pd.DataFrame):
        plt.ioff()
        fig = plt.figure(figsize=(15, 10))
        ax1 = plt.subplot(2, 2, 1)
        for instr in self.instrument_multipliers:
            instr_pnl = pnl_df[pnl_df['instrument'] == instr].copy()
            if not instr_pnl.empty:
                instr_pnl.loc[:, 'total_value'].plot(ax=ax1, label=instr)
        ax1.set_title('Equity Curve')
        ax1.set_ylabel('Portfolio Value ($)')
        ax1.legend()
        
        ax2 = plt.subplot(2, 2, 2)
        for instr in self.instrument_multipliers:
            instr_pnl = pnl_df[pnl_df['instrument'] == instr].copy()
            if not instr_pnl.empty:
                instr_pnl.loc[:, 'peak'] = instr_pnl['total_value'].cummax()
                instr_pnl.loc[:, 'drawdown'] = (instr_pnl['peak'] - instr_pnl['total_value']) / instr_pnl['peak']
                instr_pnl.set_index('timestamp')['drawdown'].plot(ax=ax2, label=instr)
        ax2.set_title('Drawdown')
        ax2.set_ylabel('Drawdown (%)')
        ax2.legend()
        
        ax3 = plt.subplot(2, 2, 3)
        for instr in self.instrument_multipliers:
            instr_trades = trades_df[trades_df['instrument'] == instr]
            if not instr_trades.empty:
                instr_trades['profit'].hist(bins=30, ax=ax3, label=instr, alpha=0.5)
        ax3.set_title('Profit Distribution')
        ax3.set_xlabel('Profit ($)')
        ax3.legend()
        
        ax4 = plt.subplot(2, 2, 4)
        for instr in self.instrument_multipliers:
            instr_pnl = pnl_df[pnl_df['instrument'] == instr].copy()
            if not instr_pnl.empty:
                instr_pnl.set_index('timestamp')['position'].plot(ax=ax4, label=instr)
        ax4.set_title('Position Over Time')
        ax4.set_ylabel('Contracts')
        ax4.legend()
        
        plt.tight_layout()
        fig.savefig('backtest_results.png')
        plt.close(fig)
        print("Saved backtest results visualization to backtest_results.png")

def print_report(metrics):
    """Prints a formatted trading performance report from metrics dictionary."""
    
    # Header
    print("\n" + "="*60)
    print(" TRADING PERFORMANCE REPORT ".center(60, "="))
    print("="*60 + "\n")
    
    # Helper function to safely format values
    def fmt(value, is_currency=False, is_percent=False):
        if value is None:
            return "N/A"
        if isinstance(value, (int, float)):
            if is_currency:
                return f"${value:,.2f}"
            if is_percent:
                return f"{value:.2f}%"
            return f"{value:.2f}"
        return str(value)
    
    # Summary Section
    print("➤ SUMMARY")
    print(f"- Total Return: {fmt(metrics.get('total_return_pct'), is_percent=True)}")
    print(f"- Final Cash: {fmt(metrics.get('final_cash'), is_currency=True)}")
    
    # Format open positions
    positions = metrics.get('open_position', {})
    if positions:
        print("- Open Positions:")
        for instr, qty in positions.items():
            if qty != 0:  # Only show non-zero positions
                print(f"  • {instr}: {qty}")
    else:
        print("- Open Positions: None")
    
    print(f"- Skipped Trades: {metrics.get('skipped_trades', 0)}")
    print(f"- Trade Count: {metrics.get('trade_count', 0)}")
    print(f"- Avg Trade Frequency: {fmt(metrics.get('avg_trade_frequency'))} minutes\n")
    
    # Performance Metrics (if available)
    perf_metrics = ['sharpe_ratio', 'max_drawdown_pct', 'win_rate_pct', 
                   'avg_win', 'avg_loss', 'profit_factor', 'expectancy']
    if any(m in metrics for m in perf_metrics):
        print("➤ PERFORMANCE METRICS")
        if 'sharpe_ratio' in metrics:
            print(f"- Sharpe Ratio: {fmt(metrics['sharpe_ratio'])}")
        if 'max_drawdown_pct' in metrics:
            print(f"- Max Drawdown: {fmt(metrics['max_drawdown_pct'], is_percent=True)}")
        if 'win_rate_pct' in metrics:
            print(f"- Win Rate: {fmt(metrics['win_rate_pct'], is_percent=True)}")
        if 'avg_win' in metrics:
            print(f"- Avg Win: {fmt(metrics['avg_win'], is_currency=True)}")
        if 'avg_loss' in metrics:
            print(f"- Avg Loss: {fmt(metrics['avg_loss'], is_currency=True)}")
        if 'profit_factor' in metrics:
            print(f"- Profit Factor: {fmt(metrics['profit_factor'])}")
        if 'expectancy' in metrics:
            print(f"- Expectancy: {fmt(metrics['expectancy'], is_currency=True)}")
        print()
    
    # Unrealized PnL
    unrealized = metrics.get('unrealized_pnl', {})
    if unrealized and any(pnl != 0 for pnl in unrealized.values()):
        print("➤ UNREALIZED P&L")
        for instr, pnl in unrealized.items():
            if pnl != 0:  # Only show positions with actual PnL
                print(f"- {instr}: {fmt(pnl, is_currency=True)}")
        print()
    
    # Signal Statistics (with error handling)
    signal_stats = metrics.get('signal_stats', {})
    if signal_stats:
        print("➤ SIGNAL STATISTICS")
        for signal, stats in signal_stats.items():
            if isinstance(stats, dict):
                print(f"- {signal}:")
                for stat, value in stats.items():
                    print(f"  • {stat.replace('_', ' ').title()}: {fmt(value)}")
            else:
                print(f"- {signal}: {fmt(stats)}")  # Handle non-dictionary stats
        print()
    
    # Performance Analysis
    analysis = metrics.get('analysis', [])
    if analysis:
        print("➤ PERFORMANCE ANALYSIS")
        print(f"- {analysis}-")
        print()
    
    # Footer
    print("="*60)
    print(" END OF REPORT ".center(60, "="))
    print("="*60 + "\n")

if __name__ == "__main__":
    backtester = MarketDataBacktester(initial_capital=2000000)
    try:
        market_trades = load_order_data("2025-08-12")
        order_book = load_tick_data("2025-08-12")
        backtester.load_market_data(market_trades, order_book)
        backtester.run_backtest(backtester.debug_strategy)
        report = backtester.generate_report()
        print("\nDEBUG Report:")
        print(f"Final position: {backtester.position}")
        print(f"Final cash: ${backtester.cash:.2f}")
        print(f"Total trades attempted: {len(backtester.strategy_trades)}")
        print(f"Skipped trades: {backtester.skipped_trades}")
        print_report(report)
        # print(backtester.strategy_trades)
        # print(report, backtester.position, backtester.strategy_trades)
        #insert_data(report,backtester.position, backtester.strategy_trades)
    except Exception as e:
        print(f"Error during debug: {str(e)}")
        raise