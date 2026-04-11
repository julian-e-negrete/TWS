import pandas as pd
from dataclasses import dataclass
from enum import Enum

class OrderType(Enum):
    MARKET = 1
    LIMIT = 2
    STOP = 3

class OrderSide(Enum):
    BUY = 1
    SELL = -1

@dataclass
class Order:
    time: pd.Timestamp
    price: float
    volume: float
    side: OrderSide
    order_type: OrderType
    order_id: int
    status: str = "PENDING"  # PENDING, FILLED, CANCELLED

class Backtester:
    def __init__(self, ticks_data):
        self.ticks = ticks_data
        self.current_time = None
        self.current_tick = None
        self.open_orders = []
        self.filled_orders = []
        self.position = 0
        self.cash = 100000  # Starting capital
        self.pnl = []
        self.trade_history = []
        
    def process_tick(self, tick):
        """Process each market data tick"""
        self.current_time = tick['time']
        self.current_tick = tick
        
        # Update open orders
        self._check_order_fills()
        
        # Execute strategy logic
        self.run_strategy()
        
        # Record portfolio state
        self._record_pnl()
    
    def _check_order_fills(self):
        """Check if any open orders should be filled"""
        for order in self.open_orders[:]:
            if order.status != "PENDING":
                continue
                
            if order.order_type == OrderType.MARKET:
                self._fill_market_order(order)
            elif order.order_type == OrderType.LIMIT:
                self._fill_limit_order(order)
            elif order.order_type == OrderType.STOP:
                self._fill_stop_order(order)
    
    def _fill_market_order(self, order):
        """Fill market order at current best price"""
        if order.side == OrderSide.BUY:
            fill_price = self.current_tick['ask_price']
        else:
            fill_price = self.current_tick['bid_price']
            
        self._execute_fill(order, fill_price)
    
    def _fill_limit_order(self, order):
        """Check if limit order can be filled"""
        if (order.side == OrderSide.BUY and 
            order.price >= self.current_tick['ask_price']):
            self._execute_fill(order, min(order.price, self.current_tick['ask_price']))
            
        elif (order.side == OrderSide.SELL and 
              order.price <= self.current_tick['bid_price']):
            self._execute_fill(order, max(order.price, self.current_tick['bid_price']))
    
    def _execute_fill(self, order, fill_price):
        """Execute order fill and update portfolio"""
        # Calculate cost and update position
        cost = fill_price * order.volume * order.side.value
        self.position += order.volume * order.side.value
        self.cash -= cost
        
        # Update order status
        order.status = "FILLED"
        order.price = fill_price  # Update with actual fill price
        
        # Move to filled orders
        self.open_orders.remove(order)
        self.filled_orders.append(order)
        
        # Record trade
        self.trade_history.append({
            'time': self.current_time,
            'price': fill_price,
            'volume': order.volume,
            'side': order.side.name,
            'type': order.order_type.name,
            'position': self.position,
            'cash': self.cash
        })
    
    def _record_pnl(self):
        """Record current portfolio value"""
        if pd.isna(self.current_tick['last_price']):
            return
            
        market_value = self.position * self.current_tick['last_price']
        total_value = self.cash + market_value
        self.pnl.append({
            'time': self.current_time,
            'position': self.position,
            'market_value': market_value,
            'cash': self.cash,
            'total_value': total_value,
            'last_price': self.current_tick['last_price']
        })
    
    def run_strategy(self):
        """Example: Simple moving average crossover strategy"""
        # Get recent prices (last 20 ticks)
        if len(self.pnl) < 20:
            return
            
        # Calculate short (5) and long (20) moving averages
        recent_prices = [x['last_price'] for x in self.pnl[-20:]]
        short_ma = sum(recent_prices[-5:]) / 5
        long_ma = sum(recent_prices) / 20
        
        # Close positions if opposite signal
        if self.position > 0 and short_ma < long_ma:
            self.add_order(OrderSide.SELL, abs(self.position), OrderType.MARKET)
        elif self.position < 0 and short_ma > long_ma:
            self.add_order(OrderSide.BUY, abs(self.position), OrderType.MARKET)
        
        # Open new positions
        elif self.position == 0:
            if short_ma > long_ma:
                # Buy signal
                target_volume = self.cash * 0.1 / self.current_tick['ask_price']  # 10% of capital
                self.add_order(OrderSide.BUY, target_volume, OrderType.MARKET)
            elif short_ma < long_ma:
                # Sell signal
                target_volume = self.cash * 0.1 / self.current_tick['bid_price']  # 10% of capital
                self.add_order(OrderSide.SELL, target_volume, OrderType.MARKET)
                
    
    def add_order(self, side, volume, order_type, price=None):
        """Create and add new order"""
        order_id = len(self.open_orders) + len(self.filled_orders) + 1
        
        if order_type == OrderType.MARKET:
            price = None  # Market orders don't have price
            
        order = Order(
            time=self.current_time,
            price=price,
            volume=volume,
            side=side,
            order_type=order_type,
            order_id=order_id
        )
        
        self.open_orders.append(order)
        
        # Market orders get filled immediately
        if order_type == OrderType.MARKET:
            self._fill_market_order(order)
            
        return order_id