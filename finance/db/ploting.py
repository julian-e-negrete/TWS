import pandas as pd
from sqlalchemy import create_engine
from config import host, user, password, database
import mplfinance as mpf


# Create SQLAlchemy engine
engine = create_engine(f'mysql+pymysql://{user}:{password}@{host}/{database}')

# Your SQL query
query = "SELECT * FROM market_data WHERE ticker = 'GGAL' ORDER BY timestamp desc ;"

# Fetch data and convert to DataFrame
with engine.connect() as connection:
    df = pd.read_sql(query, connection)
    
# Inspect the DataFrame
df['timestamp'] = pd.to_datetime(df['timestamp'])

# Set the 'date' column as the index of the DataFrame
df.set_index('timestamp', inplace=True)


print(df.head())
print(df.dtypes)

mpf.plot(df, type='candle', style='charles', volume=True, title=f"{df['ticker'][0]}")

    
    