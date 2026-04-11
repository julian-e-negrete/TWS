from binance.client import Client
from binance.enums import *
import pandas as pd
import matplotlib.pyplot as plt
import time
import mplfinance as mpf
from db_config import host, user, password, database

from sqlalchemy import create_engine


def get_binance_data_and_insert():
    from finance.config import settings
    API_KEY = settings.binance.api_key
    API_SECRET = settings.binance.api_secret

    client = Client(API_KEY, API_SECRET)


    exchange_info = client.get_exchange_info()
    symbols = [s['symbol'] for s in exchange_info['symbols']]

    ticker = 'USDTARS'
    if( ticker in symbols):   # Check availability
        

        # Example: Get 1-hour candles for USDTARS for last 7 days
        klines = client.get_klines(symbol=ticker, interval=Client.KLINE_INTERVAL_1DAY, limit=90)

        # Convert to DataFrame
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume', 
            'close_time', 'quote_asset_volume', 'num_trades', 
            'taker_buy_base_volume', 'taker_buy_quote_volume', 'ignore'
        ])
        df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        df.set_index('date', inplace=True)  # Now index is DatetimeIndex
        df = df[['open', 'high', 'low', 'close', 'volume', 'num_trades']].astype(float)
        df_reset = df.reset_index()
        
        df_reset['ticker'] = ticker
        
        df_reset = df_reset[['ticker', 'open', 'high', 'low', 'volume', 'num_trades', 'date', 'close']]
        

        print(df_reset.dtypes)
        print(df_reset.columns)
        print(df_reset.head())

        print(df_reset.tail())
        # Create SQLAlchemy engine (using PyMySQL as driver)
        engine = create_engine(f'mysql+pymysql://{user}:{password}@{host}/{database}')

        # Insert DataFrame into MySQL table (create table if it doesn't exist)
        df_reset.to_sql(name='cryptocurrency_data', con=engine, if_exists='append', index=False)
        #print(df.head())
        
        mpf.plot(df, type='candle', style='charles', volume=True, title='USDT/ARS')


    else:
        print("no avalaible")
    
    
    
if __name__ == "__main__":
    try:
        get_binance_data_and_insert()
        print("insert done right")
        
    except Exception as e:
        print("An error occurred:", str(e))