import psycopg2
import pandas as pd
from psycopg2.extras import execute_values
from config import dbname, user, password, host, port
from datetime import datetime

def safe_float_conversion(value):
    """Safely converts European format numbers to float"""
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace('.', '').replace(',', '.'))
    except (ValueError, AttributeError):
        return None

def load_tick_data(date, instrument='M:bm_MERV_PESOS_1D'):
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
    SELECT 
    (time AT TIME ZONE 'UTC') AT TIME ZONE 'UTC-3' AS time,
    bid_price, ask_price, bid_volume, ask_volume, last_price, total_volume
    FROM ticks
    WHERE instrument = '{instrument}'
    AND time BETWEEN '{date} 13:00:00' AND '{date} 20:00:00'
    ORDER BY time
    """
    
    # Use context manager for connection
    with conn:
        df = pd.read_sql(query, conn)
        
    
    # Convert numeric columns safely
    for col in ['bid_price', 'ask_price', 'last_price', 'bid_volume', 'ask_volume', 'total_volume']:
        if col in df.columns:
            df[col] = df[col].apply(safe_float_conversion)
            
    df['time'] = pd.to_datetime(df['time'])
    return df
    
    
    
    

def load_order_data(date, instrument='M:bm_MERV_PESOS_1D'):
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
    price, volume, side
    FROM orders
    WHERE time BETWEEN '{date} 13:00:00' AND '{date} 20:00:00'
    ORDER BY time
    """
    
    # Use context manager for connection
    with conn:
        df = pd.read_sql(query, conn, parse_dates=['time'])
    
    
    # Convert numeric columns safely
    for col in ['price', 'volume']:
        if col in df.columns:
            df[col] = df[col].apply(safe_float_conversion)
            
    df['time'] = pd.to_datetime(df['time'])
    return df


