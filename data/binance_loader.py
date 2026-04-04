import pandas as pd
import psycopg2
from config.settings import settings
dbname, user, password, host, port = settings.postgres.db, settings.postgres.user, settings.postgres.password, settings.postgres.host, settings.postgres.port

BINANCE_SYMBOLS = ['BTCUSDT', 'USDTARS']

def load_binance_data(date: str, symbol: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns (trades_df, ticks_df) for a Binance symbol on a given date.
    Each 1-min bar → 2 synthetic trades (open + close) + orderbook snapshot.
    """
    conn = psycopg2.connect(dbname=dbname, user=user, password=password,
                            host=host, port=port, sslmode='disable')
    query = f"""
        SELECT timestamp AT TIME ZONE 'UTC' AS time,
               symbol AS instrument, open, high, low, close, volume
        FROM binance_ticks
        WHERE timestamp::date = '{date}'
          AND symbol = '{symbol}'
        ORDER BY timestamp
    """
    with conn:
        df = pd.read_sql(query, conn)

    if df.empty:
        return pd.DataFrame(), pd.DataFrame()

    df['time'] = pd.to_datetime(df['time'], utc=True)
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # Synthesize trades: open trade + close trade per bar
    rows = []
    for _, bar in df.iterrows():
        direction = 'B' if bar['close'] >= bar['open'] else 'S'
        half_vol = max(1, bar['volume'] / 2)
        rows.append({'time': bar['time'], 'price': bar['open'],
                     'volume': half_vol, 'side': direction, 'instrument': symbol})
        rows.append({'time': bar['time'], 'price': bar['close'],
                     'volume': half_vol, 'side': direction, 'instrument': symbol})
    trades_df = pd.DataFrame(rows)

    # ticks_df: bid=low, ask=high, last=close (standard OHLCV → orderbook mapping)
    ticks_df = df.rename(columns={'low': 'bid_price', 'high': 'ask_price',
                                   'close': 'last_price', 'volume': 'total_volume'}).copy()
    ticks_df['bid_volume'] = ticks_df['total_volume'] / 2
    ticks_df['ask_volume'] = ticks_df['total_volume'] / 2
    ticks_df['instrument'] = symbol

    return trades_df, ticks_df
