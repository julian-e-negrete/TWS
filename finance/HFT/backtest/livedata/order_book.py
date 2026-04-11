import websocket
import json
import locale
from datetime import datetime

from ppi_client.api.constants import ACCOUNTDATA_TYPE_ACCOUNT_NOTIFICATION, ACCOUNTDATA_TYPE_PUSH_NOTIFICATION, \
    ACCOUNTDATA_TYPE_ORDER_NOTIFICATION
from ppi_client.ppi import PPI


from finance.HFT.backtest.PPI.opciones.get_maturity import get_maturity

from finance.PPI.classes import Account, Market_data


from finance.HFT.backtest.opciones.blackscholes import black_scholes_model



import re
import QuantLib as ql
import functools

class TopOfBookLOB:
    def __init__(self, symbol_filter=None):
        self.bid_price = None
        self.bid_size = None
        self.ask_price = None
        self.ask_size = None
        self.last_seq = None
        self.symbol = None
        self.last_price = None
        self.volume = None
        self.symbol_filter = symbol_filter
        # Store previous snapshot's bid/ask for comparison
        self.prev_bid_price = None
        self.prev_bid_size = None
        self.prev_ask_price = None
        self.prev_ask_size = None
        self.prev_volume = None

    def update_from_raw_message(self, raw_message):
        if not raw_message.startswith('M:'):
            return

        parts = raw_message.split('|')
        if len(parts) < 8:
            return

        message_symbol = parts[0].split(':')[1]
        if self.symbol_filter and message_symbol != self.symbol_filter:
            return

        self.symbol = message_symbol
        seq_num = parts[1]
        new_bid_size = int(parts[2])
        new_bid_price = float(parts[3])
        new_ask_price = float(parts[4])
        new_ask_size = int(parts[5])
        new_last_price = float(parts[6])
        timestamp = parts[7]
        new_volume = int(parts[8]) if len(parts) > 8 and parts[8] else 0

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
        self.last_seq = seq_num

        if lob_updated:
            print(f"\n--- {self.symbol} LOB Update (Seq: {seq_num}, Time: {timestamp}) ---")
            self.print_lob()

    def print_lob(self):
        print(f"Bid: {self.bid_price} @ {self.bid_size}")
        print(f"Ask: {self.ask_price} @ {self.ask_size}")
        print(f"Last Price: {self.last_price}")
        print(f"Volume: {self.volume}")
        if self.ask_price is not None and self.bid_price is not None:
            spread = self.ask_price - self.bid_price
            print(f"Spread: {spread:.1f}")
            if spread > 1.0:
                print("Note: Wide spread, low liquidity.")
            elif spread <= 0.5:
                print("Note: Tight spread, good liquidity.")
        
        # Infer trade type
        if self.last_price is not None and self.volume is not None and self.prev_volume is not None:
            if self.volume > self.prev_volume:  # Trade occurred (volume increased)
                if self.last_price == self.ask_price:
                    print("Trade Inference: Likely a BUY MARKET order (last price matches current ask).")
                    print(f"price: {self.last_price}  volume: {self.volume - self.prev_volume}")
                elif self.last_price == self.bid_price:
                    print("Trade Inference: Likely a SELL MARKET order (last price matches current bid).")
                    print(f"price: {self.last_price}  volume: {self.volume - self.prev_volume}")
                elif self.prev_bid_price is not None and self.last_price == self.prev_bid_price:
                    print("Trade Inference: Likely a SELL MARKET order (last price matches previous bid, limit order filled).")
                    print(f"price: {self.last_price}  volume: {self.volume - self.prev_volume}")
                elif self.prev_ask_price is not None and self.last_price == self.prev_ask_price:
                    print("Trade Inference: Likely a BUY MARKET order (last price matches previous ask, limit order filled).")
                    print(f"price: {self.last_price}  volume: {self.volume - self.prev_volume}")
                else:
                    print("Trade Inference: Ambiguous (last price does not match current or previous bid/ask).")
            else:
                print("Trade Inference: Likely a LIMIT order update (no volume change).")

# Global LOB tracker
lob_processor = TopOfBookLOB(symbol_filter="bm_MERV_GFGC85573O_24hs")

def on_message(ws, message, account, calculated_data):
    #print(message)
    try:
        data = json.loads(message)
        
        
        if 'topic' in data and 'msg' in data and data['topic'].startswith('md.'):
            print("aaa")
            raw_data_message = data['msg']
            lob_processor.update_from_raw_message(raw_data_message)
            
            symbol = "M:bm_MERV_GFGC85573O_24hs"

    
            match = re.search(r"_([A-Z]+\d+[A-Z])_", symbol)
            if match:
                ticker = match.group(1)  # GFGC85573O
            
            match = re.search(r"_([A-Z]+\d+[A-Z])_", symbol)
            if match:
                maturity = get_maturity(match.group(1), 2025)  
                
        
            match = re.search(r"[A-Z]+(\d+)[A-Z]", symbol)
            if match:
                strike_price = int(match.group(1))
                
            expiry = ql.Date(maturity.day,maturity.month, maturity.year)
            
            market = Market_data(account.ppi)
            actual_option_price = market.get_market_data("GGAL", "OPCIONES", "A-24HS")

            option, actual_price, delta, gamma, vega, theta, rho, iv = black_scholes_model(
            "GGAL", ticker, strike_price, expiry, actual_option_price["price"], account
            )
            
            # Append data to the list
            calculated_data.append({
                'timestamp': lob_processor.last_seq,  # Use the timestamp column
                'calculated_price': option,
                'delta': delta,
                'gamma': gamma,
                'vega': vega,
                'theta': theta,
                'rho': rho,
                'implied_volatility': iv,
                'underlying_price': actual_option_price["price"]
            })
            
            print(f"Calculated option price: {option}")
            print(f"Delta: {delta}, Gamma: {gamma}, Vega: {vega}, Theta: {theta}, Rho: {rho}")

    except json.JSONDecodeError:
        
        lob_processor.update_from_raw_message(message)
        symbol = "M:bm_MERV_GFGC85573O_24hs"

        

        match = re.search(r"_([A-Z]+\d+[A-Z])_", symbol)
        if match:
            ticker = match.group(1)  # GFGC85573O
        
        match = re.search(r"_([A-Z]+\d+[A-Z])_", symbol)
        if match:
            maturity = get_maturity(match.group(1), 2025)  
            
    
        match = re.search(r"[A-Z]+(\d+)[A-Z]", symbol)
        if match:
            strike_price = int(match.group(1))
            
        if len(str(strike_price)) > 4:
            strike_price /=10
    
        expiry = ql.Date(maturity.day,maturity.month, maturity.year)
        
        market = Market_data(account.ppi)
       
        actual_option_price = market.get_market_data("GGAL", "ACCIONES", "A-24HS")
        #print("Received non-JSON message")


        option, actual_price, delta, gamma, vega, theta, rho, iv = black_scholes_model(
        "GGAL", ticker, strike_price, expiry, actual_option_price["price"], account, False
        )
        
        # Append data to the list
        calculated_data.append({
            'timestamp': lob_processor.last_seq,  # Use the timestamp column
            'calculated_price': option,
            'delta': delta,
            'gamma': gamma,
            'vega': vega,
            'theta': theta,
            'rho': rho,
            'implied_volatility': iv,
            'underlying_price': actual_option_price["price"]
        })
        print(f"precio actual de la accion: {actual_option_price['price']}")
        print(f"Calculated option price: {option}")
        print(f"Delta: {delta}, Gamma: {gamma}, Vega: {vega}, Theta: {theta}, Rho: {rho}")
        print(f"Implied Volatility: {iv*100:.2f}%")

def on_error(ws, error):
    print("WebSocket Error:", error)

def on_close(ws, close_status_code, close_msg):
    print("WebSocket Connection Closed")

def on_open(ws):
    print("WebSocket Connection Established. Subscribing to market data...")
  
    ws.send(json.dumps({
        "_req": "S",
        "topicType": "md",
        "topics": [
            
            "md.bm_MERV_GFGC85573O_24hs"
        ],
        "replace": True
    }))
    print("Subscription request sent.")


url = "wss://matriz.eco.xoms.com.ar/ws?session_id=EhFRaDtXahpwimYEAdDIaW04nhn72u25WcOOGw9C78ZQaikRCFDzt61LupjIHMiA&conn_id=hAmfYHjuLpSTwdsPE2IS%2FA9Oh3fi68xe9Ol56F9UKtjYKZgMQ%2F92AVqGx0KNmcJE"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache"
}



if __name__ == "__main__":
    
    
    
            
    ppi = PPI(sandbox=False)

    account = Account(ppi)
    
    calculated_data = []  # List to store calculated option prices and Greeks
    
    ws = websocket.WebSocketApp(url,
                                header=[f"{k}: {v}" for k, v in headers.items()],
                                on_open=on_open,
                                on_message=functools.partial(on_message, account=account, calculated_data=calculated_data),
                                on_error=on_error,
                                on_close=on_close)
    ws.run_forever()
    
    print(calculated_data)