from binance import ThreadedWebsocketManager
import asyncio
import pandas as pd
from config import BINANCE_API_KEY, BINANCE_SECRET_KEY, SYMBOL, INTERVAL, LOOKBACK

from indicators import compute_rsi
from alerting import evaluate_alerts, warning_price, warning_price_BTC
from graphing import update_graph
import time
import threading
import os
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.db_pool import get_conn, put_conn  # SPEC §6.4 T-DB-2

from tabulate import tabulate

# fromating output
from rich.console import Console
from rich.table import Table
from rich.live import Live




class BinanceMonitor:
    def __init__(self, symbols):
        self.symbols = symbols  
        self.data_map = {symbol: pd.DataFrame() for symbol in symbols}
        self.conn_keys = {}
        self.last_len = {symbol: 0 for symbol in symbols}

    def insert_kline_db(self, symbol, row):
        if row["volume"] == 0:
            return
        query = """
            INSERT INTO binance_ticks (symbol, timestamp, open, high, low, close, volume)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING;
        """
        values = (symbol, row["timestamp"], row["open"], row["high"], row["low"], row["close"], row["volume"])
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(query, values)
            conn.commit()
            cur.close()
        except Exception as e:
            print(f"DB insert error: {e}")
        finally:
            put_conn(conn)

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
        print(f"WebSocket started with connection key: {self.conn_keys}")  # Confirming the conn_key is set
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Keyboard interrupt detected. Shutting down gracefully...")
            self.stop()
        except Exception as e:
            print(f"Unexpected error: {str(e)}")
            self.stop()
            
            
        def create_table(symbol, df):
            table = Table(title=f"Live Data - {symbol}")

            # Add columns
            for col in df.columns:
                table.add_column(col, justify="right")

            # Add rows
            for _, row in df.iterrows():
                table.add_row(*[str(row[col]) for col in df.columns])

            return table
        

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

        # Insert into DB for backtesting
        self.insert_kline_db(symbol, new_row)

        df = self.data_map[symbol]
        df = pd.concat([df, pd.DataFrame([new_row])]).drop_duplicates(subset="timestamp")
        df = df.tail(LOOKBACK)
        self.data_map[symbol] = df

        if len(df) > self.last_len[symbol]:
            self.last_len[symbol] = len(df)
            if (len(df) >= 14):
                print(symbol)
                rsi = compute_rsi(df)
                evaluate_alerts(rsi)
            
            
            #update_graph(df, symbol)
            

    def stop(self):
        if self.twm:
            if hasattr(self, 'conn_key'):
                for symbol, conn_key in self.conn_keys.items():
                    print(f"Stopping WebSocket for {symbol} with conn_key: {conn_key}")
                    self.twm.stop_socket(conn_key)
            else:
                print("No connection key found. WebSocket might not have started properly.")
            
            # Ensure the WebSocket manager is stopped
            self.twm.stop()  # Properly stop the WebSocket manager
            print("WebSocket manager stopped")
            
            for thread in threading.enumerate():
                print(f"Thread still running: {thread.name}")
            
        else:
            print("WebSocket manager not initialized")
        
        # DB connections managed by shared pool — no manual close needed
