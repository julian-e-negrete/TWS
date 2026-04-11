import locale
from datetime import datetime
import pandas as pd
from finance.HFT.backtest.db.load_data import load_tick_historical

class TopOfBookLOB:
    def __init__(self, symbol_filter=None):
        self.bid_price = None
        self.bid_size = None
        self.ask_price = None
        self.ask_size = None
        self.last_seq = None  # Not used with database, kept for compatibility
        self.symbol = None
        self.last_price = None
        self.volume = None
        self.symbol_filter = symbol_filter
        self.prev_bid_price = None
        self.prev_bid_size = None
        self.prev_ask_price = None
        self.prev_ask_size = None
        self.prev_volume = None
        self.side = None
        
        
        self.results = []
        self.lob = []

    def update_from_db_row(self, row):
        """
        Process a Pandas Series row with fields: instrument, time, bid_price, ask_price,
        bid_volume, ask_volume, last_price, total_volume
        """
        message_symbol = row['instrument']
        if self.symbol_filter and message_symbol != self.symbol_filter:
            return

        self.symbol = message_symbol
        timestamp = str(row['time'])  # Convert Timestamp to string for display
        new_bid_price = float(row['bid_price'])
        new_ask_price = float(row['ask_price'])
        new_last_price = float(row['last_price'])
        new_bid_size = int(row['bid_volume'])
        new_ask_size = int(row['ask_volume'])
        # Scale total_volume to match WebSocket volume (e.g., divide by 1000)
        new_volume = int(row['total_volume'])

        # Check if LOB, last price, or volume changed
        lob_updated = (
            new_bid_price != self.bid_price or
            new_bid_size != self.bid_size or
            new_ask_price != self.ask_price or
            new_ask_size != self.ask_size or
            new_last_price != self.last_price or
            new_volume != self.volume
        )

        # Store current state as previous before updating
        if lob_updated:
            self.prev_bid_price = self.bid_price
            self.prev_bid_size = self.bid_size
            self.prev_ask_price = self.ask_price
            self.prev_ask_size = self.ask_size
            self.prev_volume = self.volume

        # Update state
        self.bid_price = new_bid_price
        self.bid_size = new_bid_size
        self.ask_price = new_ask_price
        self.ask_size = new_ask_size
        self.last_price = new_last_price
        self.volume = new_volume
        self.last_seq = timestamp  # Use timestamp as proxy for seq_num
        
        
        

        if lob_updated:
            # print(f"\n--- {self.symbol} LOB Update (Time: {timestamp}) ---")
            self.print_lob()

    def print_lob(self):
        
        # print(f"Bid: {self.bid_price} @ {self.bid_size}")
        # print(f"Ask: {self.ask_price} @ {self.ask_size}")
        # print(f"Last Price: {self.last_price}")
        # print(f"Volume: {self.volume}")
        # if self.ask_price is not None and self.bid_price is not None:
        #     spread = self.ask_price - self.bid_price
        #     print(f"Spread: {spread:.1f}")
        #     if spread > 1.0:
        #         print("Note: Wide spread, low liquidity.")
        #     elif spread <= 0.5:
        #         print("Note: Tight spread, good liquidity.")
        
        # Infer trade type
        if self.last_price is not None and self.volume is not None and self.prev_volume is not None:
            if self.volume > self.prev_volume:  # Trade occurred (volume increased)
                trade_volume = self.volume - self.prev_volume
                if self.last_price == self.ask_price:
                    # print(f"Trade Inference: Likely a BUY MARKET order (last price matches current ask).")
                    # print(f"Price: {self.last_price} Volume: {trade_volume}")
                    self.side = "BUY"
                elif self.last_price == self.bid_price:
                    # print(f"Trade Inference: Likely a SELL MARKET order (last price matches current bid).")
                    # print(f"Price: {self.last_price} Volume: {trade_volume}")
                    self.side = "SELL"
                elif self.prev_bid_price is not None and self.last_price == self.prev_bid_price:
                    #print(f"Trade Inference: Likely a SELL MARKET order (last price matches previous bid, limit order filled).")
                    #print(f"Price: {self.last_price} Volume: {trade_volume}")
                    self.side = "SELL"
                elif self.prev_ask_price is not None and self.last_price == self.prev_ask_price:
                    #print(f"Trade Inference: Likely a BUY MARKET order (last price matches previous ask, limit order filled).")
                    #print(f"Price: {self.last_price} Volume: {trade_volume}")
                    self.side = "BUY"
                #else:
                    #print("Trade Inference: Ambiguous (last price does not match current or previous bid/ask).")
                    
                self.results.append({
                        "timestamp": self.last_seq,
                        "bid_price": self.bid_price,
                        "bid_size": self.bid_size,
                        "ask_price": self.ask_price,
                        "ask_size": self.ask_size,
                        "last_price": self.last_price,
                        "volume": self.volume,
                        "side" : self.side
                        
                    })
            else:
                self.lob.append({
                    "timestamp": self.last_seq,
                    "bid_price": self.bid_price,
                    "bid_size": self.bid_size,
                    "ask_price": self.ask_price,
                    "ask_size": self.ask_size,
                    "last_price": self.last_price,
                    "volume": self.volume,                        
                    })
                #print("Trade Inference: Likely a LIMIT order update (no volume change).")

def process_db_data(db,symbol_filter ):
    # Initialize LOB processor
    lob_processor = TopOfBookLOB(symbol_filter=symbol_filter)
    # print(f"Processing market data from database for symbol: {symbol_filter}")
    # print("Starting data processing...\n")

    # Ensure DataFrame is sorted by time
    db = db.sort_values(by='time')

    # Process each row
    for _, row in db.iterrows():
        lob_processor.update_from_db_row(row)
        
    return lob_processor.results, lob_processor.lob

if __name__ == "__main__":
    # Set locale for date parsing if needed
    locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')

    # Load historical market data
    market_data = load_tick_historical(
        start_date="2025-08-20",
        end_date="2025-08-20",
        instrument="M:rx_DDF_DLR_AGO25"
    )

    # Process data from DataFrame
    