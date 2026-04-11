import pandas as pd
import numpy as np
from finance.HFT.backtest.db.load_data import load_tick_historical, load_order_historical
import pandas as pd
from sortedcontainers import SortedDict
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend; safe for headless import
import matplotlib.pyplot as plt





class LimitOrderBook:
    def __init__(self, df):
        self.bids = SortedDict(lambda x: -x)  # Descending price
        self.asks = SortedDict()              # Ascending price
        self.trade_history = []
        self.last_total_volume = df.iloc[0]['total_volume']  # Initialize with first value
        self.current_time = None
        self.prev_trade_price = None
        self.prev_direction = None
        
        # Process each tick starting from first row
        for _, row in df.iterrows():
            self.process_tick(row)
        
        # Print final state
        print("\nFinal LOB State:")
        self.print_top_levels()
        
        # Visualize
        #self.plot_lob()

    def process_tick(self, tick):
        self.current_time = tick['time']
    
        # Handle trade first using previous book state (skip first row)
        if tick.name > 0:
            if tick['total_volume'] > self.last_total_volume:
                executed_volume = tick['total_volume'] - self.last_total_volume
                self.handle_trade(tick, executed_volume)
        
        # Then update bid/ask to new state
        self.update_side('bid', tick['bid_price'], tick['bid_volume'])
        self.update_side('ask', tick['ask_price'], tick['ask_volume'])
        
        # Update last total volume
        self.last_total_volume = tick['total_volume']

    def update_side(self, side, price, volume):
        book = self.bids if side == 'bid' else self.asks
        book.clear()  # Reset to only the current best level
        if volume > 0:
            book[price] = volume

    def handle_trade(self, tick, executed_volume):
        trade_side = self.infer_trade_side(tick)
        if trade_side != 'unknown':
            self.prev_trade_price = tick['last_price']
            self.prev_direction = trade_side
        
        trade = {
            'time': tick['time'],
            'price': tick['last_price'],
            'volume': executed_volume,
            'side': trade_side
        }
        self.trade_history.append(trade)
        
        print(f"Trade at {trade['time']}: {trade['side']} {trade['volume']} @ {trade['price']}")

    def infer_trade_side(self, tick):
        if not self.asks or not self.bids:
            return 'unknown'
        
        best_bid = self.bids.peekitem(0)[0]
        best_ask = self.asks.peekitem(0)[0]
        mid = (best_bid + best_ask) / 2.0
        price = tick['last_price']
        
        if price > mid:
            return 'buy'
        elif price < mid:
            return 'sell'
        else:
            # Fallback to tick rule
            if self.prev_trade_price is None:
                return 'unknown'
            elif price > self.prev_trade_price:
                return 'buy'
            elif price < self.prev_trade_price:
                return 'sell'
            else:
                # Zero tick: use previous direction
                return self.prev_direction or 'unknown'

    def print_top_levels(self, levels=3):
        print("Bids:")
        if self.bids:
            for price, vol in list(self.bids.items())[:levels]:
                print(f"  {price}: {vol}")
        else:
            print("  No bids")
        
        print("Asks:")
        if self.asks:
            for price, vol in list(self.asks.items())[:levels]:
                print(f"  {price}: {vol}")
        else:
            print("  No asks")

    def plot_lob(self):
        plt.figure(figsize=(12, 6))
        plt.title(f"Limit Order Book @ {self.current_time}")
        
        # Plot bids (left side)
        if self.bids:
            bid_prices, bid_volumes = zip(*self.bids.items())
            plt.barh([-p for p in bid_prices], bid_volumes, height=0.5, color='green', alpha=0.6, label='Bids')
        
        # Plot asks (right side)
        if self.asks:
            ask_prices, ask_volumes = zip(*self.asks.items())
            plt.barh([-p for p in ask_prices], ask_volumes, height=0.5, color='red', alpha=0.6, label='Asks')
        
        # Formatting
        plt.xlabel("Volume")
        plt.ylabel("Price (inverted)")
        plt.yticks([-p for p in sorted(set(self.bids.keys()).union(set(self.asks.keys())))],
                  [f"{p:.2f}" for p in sorted(set(self.bids.keys()).union(set(self.asks.keys())))])
        
        plt.legend()
        plt.grid(True)
        plt.tight_layout()
        plt.show(block=True)

if __name__ == "__main__":
    # Example data matching your structure

    data = load_tick_historical("2025-08-12", "2025-08-13")

    tick_data = pd.DataFrame(data)
    
    tick_data['time'] = pd.to_datetime(tick_data['time'])
    
    # for index, row in tick_data.head(50).iterrows():
    #     print(row)

    
    
    
    #print(tick_data.head(10))
    LimitOrderBook(tick_data)
    
    # Process the data
    # results = process_tick_data(tick_data.tail(10))
    
    # # Save results
    # results.to_csv('order_book_analysis.csv', index=False)
    # print("\nAnalysis saved to order_book_analysis.csv")