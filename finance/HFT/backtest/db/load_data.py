import psycopg2
import pandas as pd
from psycopg2.extras import execute_values
from finance.HFT.backtest.db.config import dbname, user, password, host, port
from finance.HFT.backtest.db.cache import cache_get, cache_set
from datetime import datetime, timedelta

def safe_float_conversion(value):
    """Safely converts European format numbers to float"""
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace('.', '').replace(',', '.'))
    except (ValueError, AttributeError):
        return None

def load_tick_data(date, instrument='M:rx_DDF_DLR_AGO25'):
    """Load tick data — returns timestamps in UTC to match orders table."""
    key = f"ticks:{date}"
    cached = cache_get(key)
    if cached is not None:
        return cached
    conn = psycopg2.connect(
        dbname=dbname, user=user, password=password,
        host=host, port=port, sslmode='disable'
    )
    query = f"""
    SELECT instrument,
    time AT TIME ZONE 'UTC' AS time,
    bid_price, ask_price, bid_volume, ask_volume, last_price, total_volume
    FROM ticks
    WHERE (time AT TIME ZONE 'America/Argentina/Buenos_Aires')::date = '{date}'
    AND instrument NOT LIKE '%AGO25%'
    ORDER BY time
    """
    with conn:
        df = pd.read_sql(query, conn)

    for col in ['bid_price', 'ask_price', 'last_price', 'bid_volume', 'ask_volume', 'total_volume']:
        if col in df.columns:
            df[col] = df[col].apply(safe_float_conversion)

    df['time'] = pd.to_datetime(df['time'], utc=True)
    cache_set(key, df)
    return df




def load_order_data(date, instrument='M:rx_DDF_DLR_AGO25'):
    """Load order data — returns timestamps in UTC."""
    key = f"orders:{date}"
    cached = cache_get(key)
    if cached is not None:
        return cached
    conn = psycopg2.connect(
        dbname=dbname, user=user, password=password,
        host=host, port=port, sslmode='disable'
    )
    query = f"""
    SELECT
    time AT TIME ZONE 'UTC' AS time,
    price, volume, side, instrument
    FROM orders
    WHERE (time AT TIME ZONE 'America/Argentina/Buenos_Aires')::date = '{date}'
    AND instrument NOT LIKE '%AGO25%'
    ORDER BY time
    """
    with conn:
        df = pd.read_sql(query, conn, parse_dates=['time'])

    for col in ['price', 'volume']:
        if col in df.columns:
            df[col] = df[col].apply(safe_float_conversion)

    df['time'] = pd.to_datetime(df['time'], utc=True)
    cache_set(key, df)
    return df



def load_tick_historical(start_date, end_date,  instrument='', limit=0):
    """Load tick data with proper numeric conversion"""
    conn = psycopg2.connect(
        dbname=dbname,
        user=user,
        password=password,
        host=host,
        port=port,
        sslmode='disable'
    )

    query = f"""
    SELECT instrument,
    bid_volume, bid_price, ask_price, ask_volume,
    last_price, total_volume, (time AT TIME ZONE 'UTC') AT TIME ZONE 'UTC-3' AS time
    FROM ticks

    WHERE  time >= '{start_date} 00:00:00' AND  time <'{end_date} 24:00:00' 
    and instrument != ''
    
    """
    if instrument!= '': query += f"\nAND instrument = '{instrument}'"
    
    query += "\nORDER BY time ASC"
    if limit > 0: query += f"\nlimit {limit}"
    

 
    
    #and instrument != '' and instrument != 'M:rx_DDF_DLR_AGO25A' and instrument != 'M:rx_DDF_DLR_AGO25'

    
    #print(query)
    # Use context manager for connection
    with conn:
        df = pd.read_sql(query, conn)
        
    
    # Convert numeric columns safely
    for col in ['bid_price', 'ask_price', 'last_price', 'bid_volume', 'ask_volume', 'total_volume']:
        if col in df.columns:
            df[col] = df[col].apply(safe_float_conversion)
            
    df['time'] = pd.to_datetime(df['time'])
    return df
    
    
    
    


def load_order_historical(start_date, end_date, instrument=''):
    """Load order data with proper numeric conversion"""
    conn = psycopg2.connect(
        dbname=dbname,
        user=user,
        password=password,
        host=host,
        port=port,
        sslmode='disable'
    )
    
    query = f"""
    SELECT 
    (time AT TIME ZONE 'UTC') AT TIME ZONE 'UTC-3' AS time,
    price, volume, side, instrument
    FROM orders
    WHERE time BETWEEN '{start_date} 00:00:00' AND '{end_date} 24:00:00'

    and instrument != ''
    """
    
    
    if instrument!= '': query += f"\nAND instrument = '{instrument}'"
    
    query += "\nORDER BY time"
    query += "\nlimit 100"
    # Use context manager for connection
    with conn:
        df = pd.read_sql(query, conn, parse_dates=['time'])
    
    
    # Convert numeric columns safely
    for col in ['price', 'volume']:
        if col in df.columns:
            df[col] = df[col].apply(safe_float_conversion)
            
    df['time'] = pd.to_datetime(df['time'])
    return df