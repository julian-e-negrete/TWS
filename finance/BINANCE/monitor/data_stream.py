from finance.utils.logger import logger
from binance import ThreadedWebsocketManager
import asyncio
import pandas as pd
from config import BINANCE_API_KEY, BINANCE_SECRET_KEY, SYMBOL, INTERVAL, LOOKBACK

from indicators import compute_rsi
from alerting import evaluate_alerts, warning_price
from graphing import update_graph
import time
import threading
import os



class BinanceMonitor:
    def __init__(self, symbols):
        self.symbols = symbols  
        self.data_map = {symbol: pd.DataFrame() for symbol in symbols}
        self.conn_keys = {}  # To store conn_keys per symbol
        self.last_len = 0

    def start(self):
        self.twm = ThreadedWebsocketManager(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)
        self.twm.start()
        
        for symbol in self.symbols:
            conn_key = self.twm.start_kline_socket(
                callback=lambda msg, s=symbol: self.process_message(msg, s),
                symbol=symbol.lower(),
                interval=INTERVAL
            )
            self.conn_keys[symbol] = conn_key
        logger.info(f"WebSocket started with connection key: {self.conn_keys}")  # Confirming the conn_key is set
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt detected. Shutting down gracefully...")
            self.stop()
        except Exception as e:
            logger.info(f"Unexpected error: {str(e)}")
            self.stop()
        

    def process_message(self, msg, symbol):
        if msg['e'] != 'kline':
            return
        kline = msg['k']
        new_row = {
            "timestamp": pd.to_datetime(kline['t'], unit='ms'),
            "open": float(kline['o']),
            "high": float(kline['h']),
            "low": float(kline['l']),
            "close": float(kline['c']),
            "volume": float(kline['v']),
        }

        df = self.data_map[symbol]
        df = pd.concat([df, pd.DataFrame([new_row])]).drop_duplicates(subset="timestamp")
        df = df.tail(LOOKBACK)
        self.data_map[symbol] = df
        
        logger.info(f"{symbol} \n{df}\n")    
        
        #logger.info(f"[{symbol}] Data length after update: {len(df)}")

        if len(df) >= 14:
            rsi = compute_rsi(df)
            evaluate_alerts(rsi)
            warning_price(df['close'])
            #update_graph(df, symbol)
            

    def stop(self):
        if self.twm:
            if hasattr(self, 'conn_key'):
                for symbol, conn_key in self.conn_keys.items():
                    logger.info(f"Stopping WebSocket for {symbol} with conn_key: {conn_key}")
                    self.twm.stop_socket(conn_key)
            else:
                logger.info("No connection key found. WebSocket might not have started properly.")
            
            # Ensure the WebSocket manager is stopped
            self.twm.stop()  # Properly stop the WebSocket manager
            logger.info("WebSocket manager stopped")
            
            for thread in threading.enumerate():
                logger.info(f"Thread still running: {thread.name}")
            
        else:
            logger.info("WebSocket manager not initialized")
