"""
BT-03: Load BYMA tick data and synthesize trades from bid/ask changes.
No orders table for BYMA — use mid-price changes as proxy trades.
"""
import pandas as pd
import psycopg2
from finance.HFT.backtest.db.config import dbname, user, password, host, port
from finance.HFT.backtest.db.load_data import safe_float_conversion


BYMA_INSTRUMENTS = [
    'M:bm_MERV_GGALD_24hs',
    'M:bm_MERV_AL30_24hs',
    'M:bm_MERV_AL30D_24hs',
    'M:bm_MERV_PBRD_24hs',
    'M:bm_MERV_BBDD_24hs',
]


def load_byma_data(date: str, instrument: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns (trades_df, ticks_df) for a BYMA instrument on a given date.
    trades_df is synthesized from mid-price changes (no orders table).
    """
    conn = psycopg2.connect(dbname=dbname, user=user, password=password,
                            host=host, port=port, sslmode='disable')
    query = f"""
        SELECT time AT TIME ZONE 'UTC' AS time,
               instrument, bid_price, ask_price, bid_volume, ask_volume,
               last_price, total_volume
        FROM ticks
        WHERE (time AT TIME ZONE 'America/Argentina/Buenos_Aires')::date = '{date}'
          AND instrument = '{instrument}'
        ORDER BY time
    """
    with conn:
        ticks_df = pd.read_sql(query, conn)

    if ticks_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    for col in ['bid_price', 'ask_price', 'last_price', 'bid_volume', 'ask_volume', 'total_volume']:
        ticks_df[col] = ticks_df[col].apply(safe_float_conversion)
    ticks_df['time'] = pd.to_datetime(ticks_df['time'], utc=True)
    # Normalize instrument: strip M: prefix so both DFs match
    ticks_df['instrument'] = ticks_df['instrument'].str.replace('M:', '', regex=False)

    # Synthesize trades: each tick where mid-price changed = a trade
    ticks_df['mid'] = (ticks_df['bid_price'] + ticks_df['ask_price']) / 2
    ticks_df['mid_change'] = ticks_df['mid'].diff()
    # Volume per tick = MAX-MIN of cumulative total_volume in rolling window
    ticks_df['vol_delta'] = ticks_df['total_volume'].diff().clip(lower=0).fillna(1)

    trades = ticks_df[ticks_df['mid_change'] != 0].copy()
    trades['side'] = trades['mid_change'].apply(lambda x: 'B' if x > 0 else 'S')
    trades['price'] = trades['last_price'].fillna(trades['mid'])
    trades['volume'] = trades['vol_delta'].clip(lower=1)

    trades_df = trades[['time', 'price', 'volume', 'side', 'instrument']].copy()
    trades_df['instrument'] = trades_df['instrument'].str.replace('M:', '', regex=False)

    return trades_df, ticks_df
