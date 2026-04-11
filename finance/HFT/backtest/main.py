from finance.utils.logger import logger
from finance.HFT.backtest.db.load_data import load_order_data, load_tick_data
from finance.HFT.backtest.db.insert_data import insert_data
from finance.HFT.backtest.engine.position_manager import PositionManager
from finance.HFT.backtest.engine.order_executor import OrderExecutor
from finance.HFT.backtest.metrics.calculator import MetricsCalculator
from finance.HFT.backtest.metrics.reporter import Reporter

import pandas as pd
import numpy as np
from dataclasses import dataclass
from finance.HFT.backtest.types import (
    OrderType, Direction, MarketTrade, OrderBookSnapshot, StrategyTrade
)
from typing import List, Optional
import matplotlib.pyplot as plt
import seaborn as sns  # Added Seaborn import
import math


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
        # Sub-components (wired after load_market_data sets instrument_multipliers)
        self._pm: Optional[PositionManager] = None
        self._executor: Optional[OrderExecutor] = None
        self._calculator = MetricsCalculator()
        self._reporter: Optional[Reporter] = None

    def _init_engine(self):
        """Initialise sub-components once instrument_multipliers is known."""
        self._pm = PositionManager(self.instrument_multipliers)
        self._executor = OrderExecutor(self._pm, self.initial_capital)
        self._reporter = Reporter(self.instrument_multipliers)
        # Keep facade attributes in sync
        self.position = self._pm.position
        self.entry_price = self._pm.entry_price
        self.entry_time = self._pm.entry_time
        self.last_close_time = self._pm.last_close_time
        self.strategy_trades = self._executor.strategy_trades
        self.skipped_trades = 0
        self.signal_stats = self._executor.signal_stats

    def load_market_data(self, trades_df: pd.DataFrame, orderbook_df: pd.DataFrame):
        required_trade_cols = ['time', 'price', 'volume', 'side', 'instrument']
        required_ob_cols = ['time', 'bid_price', 'ask_price', 'bid_volume', 'instrument']
        
        if trades_df.empty:
            logger.warning("trades_df is empty")
        else:
            if not all(col in trades_df.columns for col in required_trade_cols):
                raise ValueError(f"trades_df missing required columns: {required_trade_cols}")
            if trades_df[required_trade_cols].isnull().any().any():
                raise ValueError("trades_df contains null values")
        
        if orderbook_df.empty:
            logger.warning("orderbook_df is empty")
        else:
            if not all(col in orderbook_df.columns for col in required_ob_cols):
                raise ValueError(f"orderbook_df missing required columns: {required_ob_cols}")
            if orderbook_df[required_ob_cols].isnull().any().any():
                raise ValueError("orderbook_df contains null values")
        
        trades_df['instrument'] = trades_df['instrument'].str.replace('M:', '')
        
        orderbook_df['instrument'] = orderbook_df['instrument'].str.replace('M:', '')
        
        duplicates = orderbook_df[['time', 'instrument']].duplicated().sum() 
        if duplicates > 0:
            logger.warning("Aggregating {duplicates} duplicate timestamps in orderbook_df")
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
                return 100
            elif 'bm_MERV_' in instrument or instrument in ('BTCUSDT', 'USDTARS'):
                return 1
            else:
                return None
        
        self.instrument_multipliers = {
            instr: get_multiplier(instr) for instr in trades_df['instrument'].unique() 
            if get_multiplier(instr) is not None
        }
        self._init_engine()
        
        logger.debug(f"Available instruments in trades_df: {list(trades_df['instrument'].unique())}")
        logger.debug(f"Valid instruments with multipliers: {list(self.instrument_multipliers.keys())}")
        
        logger.debug(f"Available instruments in orderbook_df: {list(orderbook_df['instrument'].unique())}")
        logger.debug(f"orderbook_df head:\n{orderbook_df.head(10)}")
    
        def infer_direction(row, recent_trades):
            if row['side'] in ['B', 'S']:
                return Direction.BUY if row['side'] == 'B' else Direction.SELL
            if row['side'] == 'U' and len(recent_trades) >= 1:
                ma = sum(t.price for t in recent_trades[-25:]) / min(len(recent_trades), 25)
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
        
        logger.info("\n=== DATA VALIDATION ===")
        for instr in self.instrument_multipliers:
            trades = [t for t in self.market_trades if t.instrument == instr]
            snapshots = [s for s in self.order_book_snapshots if s.instrument == instr]
            logger.debug(f"\nInstrument: {instr}")
            logger.debug(f"Multiplier: {self.instrument_multipliers[instr]}")
            logger.debug(f"Trades: {len(trades)} records")
            logger.debug(f"Order book: {len(snapshots)} records")
            if trades:
                logger.debug(f"Time range: {min(t.timestamp for t in trades)} to {max(t.timestamp for t in trades)}")
                logger.debug(f"Trade frequency: {len(trades) / ((trades[-1].timestamp - trades[0].timestamp).total_seconds() / 3600):.2f} trades/hour")
                logger.debug(f"Trade prices: {min(t.price for t in trades):.2f}-{max(t.price for t in trades):.2f}")
            if snapshots:
                logger.debug(f"Bid prices: {min(s.bid_price for s in snapshots):.2f}-{max(s.bid_price for s in snapshots):.2f}")
                logger.debug(f"Ask prices: {min(s.ask_price for s in snapshots):.2f}-{max(s.ask_price for s in snapshots):.2f}")
            else:
                logger.warning("No order book snapshots available for {instr}")
            if trades:
                logger.debug(f"Trade volumes (contracts): {min(t.volume for t in trades)}-{max(t.volume for t in trades)}")
                logger.debug(f"Trade directions: {sum(1 for t in trades if t.direction == Direction.BUY)} buys, "
                      f"{sum(1 for t in trades if t.direction == Direction.SELL)} sells, "
                      f"{sum(1 for t in trades if t.direction is None)} unknown")
            else:
                logger.warning("No trade records available for {instr}")

    def run_backtest(self, strategy_func):
        if not self.order_book_snapshots:
            logger.warning("No order book snapshots; running trade-only backtest")
            return self.run_trade_only_backtest(strategy_func)
        
        combined_timeline = self._create_combined_timeline()
        logger.info(f"\nTimeline contains {len(combined_timeline)} events")
        
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
                logger.info(f"\nClosing open position for {instrument} at end of backtest")
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
        if net_profit > 20000 * 1330:
            taxable_profit = net_profit - 20000
            tax = taxable_profit * 0.15
            logger.info(f"\nApplying capital gains tax: ${tax:.2f} on taxable profit ${taxable_profit:.2f}")
            self.cash -= tax

    def run_trade_only_backtest(self, strategy_func):
        logger.info("\nRunning trade-only backtest due to missing order book data")
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
                logger.info(f"\nClosing open position for {instrument} at end of backtest")
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
        if net_profit > 20000 * 1330:
            taxable_profit = net_profit - 20000
            tax = taxable_profit * 0.15
            logger.info(f"\nApplying capital gains tax: ${tax:.2f} on taxable profit ${taxable_profit:.2f}")
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
        price = order_book.ask_price if signal['direction'] == Direction.BUY else order_book.bid_price
        self._executor.execute(signal, price, self.current_time)
        self.cash = self._executor.cash
        self.skipped_trades = self._executor.skipped_trades




    def _execute_trade_only_order(self, signal: dict, trade: MarketTrade):
        self._executor.execute(signal, trade.price, self.current_time)
        self.cash = self._executor.cash
        self.skipped_trades = self._executor.skipped_trades

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
            logger.debug(f"No signal: No instrument (recent_trades: {len(recent_trades)})")
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
        
        logger.info(f"\nTime: {self.current_time} ({instrument})")
        if current_market:
            logger.debug(f"Bid/Ask: {current_market.bid_price:.2f}/{current_market.ask_price:.2f}")
            logger.debug(f"Spread: {spread:.4f} ({spread/mid_price*10000:.1f} bps)")
        else:
            logger.debug(f"Trade price: {price:.2f} (no order book)")
        logger.debug(f"Position: {current_position.get(instrument, 0)}, Cash: ${current_cash:,.2f}")
        logger.debug(f"Recent trades: {len(recent_trades)}")
        if recent_trades:
            logger.debug(f"Recent trade prices: {[t.price for t in recent_trades[-5:]]}")
            logger.debug(f"Recent trade volumes: {[t.volume for t in recent_trades[-5:]]}")
        logger.debug(f"Calculated volume: {volume} contracts")
        
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
                logger.debug(f"Exit triggered: Stop-loss (-{exit_threshold}%), take-profit ({exit_threshold*2}%), or time-based (5min)")
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
            logger.debug(f"No signal: Cooldown period ({cooldown})")
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
                logger.debug(f"No signal: Spread too wide ({spread/mid_price*100:.2f}% vs {spread_threshold*100:.2f}%)")
                self.signal_stats['spread_too_wide'] += 1
                self.signal_stats['no_order_book'] += 1
                return signals
            
            if trend_up:
                logger.info(f"BUY signal triggered: Price {last_trade.price:.2f} > MA {ma:.2f}, Volume {last_trade.volume}, Dev {price_dev_pct:.2f}%")
                signals.append({
                    'direction': Direction.BUY,
                    'volume': volume,
                    'order_type': OrderType.MARKET if not current_market else OrderType.LIMIT,
                    'price': price if not current_market else current_market.bid_price + spread/2,
                    'instrument': instrument
                })
            elif trend_down:
                logger.info(f"SELL signal triggered: Price {last_trade.price:.2f} < MA {ma:.2f}, Volume {last_trade.volume}, Dev {price_dev_pct:.2f}%")
                signals.append({
                    'direction': Direction.SELL,
                    'volume': volume,
                    'order_type': OrderType.MARKET if not current_market else OrderType.LIMIT,
                    'price': price if not current_market else current_market.ask_price - spread/2,
                    'instrument': instrument
                })
            else:
                if last_trade.volume <= 50:
                    logger.debug(f"No signal: Low trade volume ({last_trade.volume} <= 50)")
                    self.signal_stats['low_volume'] += 1
                if not (trend_up or trend_down):
                    logger.debug(f"No signal: No trend (Price {last_trade.price:.2f}, MA {ma:.2f}, Dev {price_dev_pct:.2f}%)")
                    self.signal_stats['no_trend'] += 1
                self.signal_stats['no_momentum'] += 1
        else:
            logger.info("No signal: Insufficient recent trades")
            self.signal_stats['no_recent_trades'] += 1
        
        return signals




    def generate_report(self, plot: bool = True):
        if not self.strategy_trades:
            logger.warning("No strategy trades executed")
            return {
                'total_trades': 0, 'skipped_trades': self.skipped_trades,
                'open_position': self.position, 'final_cash': self.cash,
                'total_return_pct': (self.cash / self.initial_capital - 1) * 100,
                'signal_stats': self.signal_stats,
            }

        trades_df = pd.DataFrame([{
            'timestamp': t.timestamp, 'price': t.price, 'volume': t.volume,
            'direction': t.direction.name, 'type': t.order_type.name,
            'profit': t.profit, 'closed': t.closed, 'instrument': t.instrument,
        } for t in self.strategy_trades])

        pnl_df = pd.DataFrame(self.pnl_history)
        metrics = self._calculator.calculate(pnl_df, trades_df)
        if plot:
            self._reporter.plot(pnl_df, trades_df)

        metrics.update({
            'skipped_trades': self.skipped_trades,
            'open_position': self.position,
            'final_cash': self.cash,
            'signal_stats': self.signal_stats,
        })
        return metrics


def print_report(metrics: dict):
    from finance.HFT.backtest.metrics.reporter import Reporter
    Reporter({}).print_report(metrics)


if __name__ == "__main__":
    backtester = MarketDataBacktester(initial_capital=2000000)
    try:
        market_trades = load_order_data("2025-08-12")
        order_book = load_tick_data("2025-08-12")
        backtester.load_market_data(market_trades, order_book)
        backtester.run_backtest(backtester.debug_strategy)
        report = backtester.generate_report()
        print_report(report)
    except Exception as e:
        logger.error("Error during backtest: {e}", e=e)
        raise
