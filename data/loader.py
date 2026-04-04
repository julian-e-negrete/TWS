import psycopg2
import pandas as pd
from .config import dbname, user, password, host, port
from .cache import cache_get, cache_set
from datetime import datetime, timedelta

def safe_float_conversion(value):
    """Safely converts European format numbers to float"""
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace('.', '').replace(',', '.'))
    except (ValueError, AttributeError):
        return None

def load_tick_data(date, instrument_filter=None):
    """Load tick data from PostgreSQL ticks table."""
    key = f"ticks:{date}:{instrument_filter}"
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
    """
    if instrument_filter:
        query += f" AND instrument LIKE '{instrument_filter}'"
    
    query += " ORDER BY time"
    
    with conn:
        df = pd.read_sql(query, conn)

    for col in ['bid_price', 'ask_price', 'last_price', 'bid_volume', 'ask_volume', 'total_volume']:
        if col in df.columns:
            df[col] = df[col].apply(safe_float_conversion)

    df['time'] = pd.to_datetime(df['time'], utc=True)
    cache_set(key, df)
    return df

def load_order_data(date, instrument_filter=None):
    """Load order data from PostgreSQL orders table."""
    key = f"orders:{date}:{instrument_filter}"
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
    """
    if instrument_filter:
        query += f" AND instrument LIKE '{instrument_filter}'"
        
    query += " ORDER BY time"
    
    with conn:
        df = pd.read_sql(query, conn, parse_dates=['time'])

    for col in ['price', 'volume']:
        if col in df.columns:
            df[col] = df[col].apply(safe_float_conversion)

    df['time'] = pd.to_datetime(df['time'], utc=True)
    cache_set(key, df)
    return df

def load_historical_data(start_date, end_date, instrument=None, table='ticks'):
    """Generic historical loader for ticks or orders."""
    conn = psycopg2.connect(
        dbname=dbname, user=user, password=password,
        host=host, port=port, sslmode='disable'
    )
    
    if table == 'ticks':
        cols = "instrument, bid_volume, bid_price, ask_price, ask_volume, last_price, total_volume, (time AT TIME ZONE 'UTC') AT TIME ZONE 'UTC-3' AS time"
    else:
        cols = "(time AT TIME ZONE 'UTC') AT TIME ZONE 'UTC-3' AS time, price, volume, side, instrument"
        
    query = f"""
    SELECT {cols}
    FROM {table}
    WHERE time >= '{start_date} 00:00:00' AND time < '{end_date} 23:59:59'
    """
    if instrument:
        query += f" AND instrument = '{instrument}'"
    
    query += " ORDER BY time ASC"
    
    with conn:
        df = pd.read_sql(query, conn)
        
    # Conversion
    numeric_cols = ['bid_price', 'ask_price', 'last_price', 'bid_volume', 'ask_volume', 'total_volume', 'price', 'volume']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].apply(safe_float_conversion)
            
    df['time'] = pd.to_datetime(df['time'])
    return df
