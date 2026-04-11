import requests
import pandas as pd
from datetime import datetime, timedelta, time, timezone
from zoneinfo import ZoneInfo

def fetch_minute_trades_today(trades):
  
    url = "https://matriz.eco.xoms.com.ar/api/v2/trades/securities/rx_DDF_DLR_JUL25?_ds=&_ds=1753889449163-979204"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.5",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Sec-GPC": "1",
        "Referer": "https://matriz.eco.xoms.com.ar/security/rx_DDF_DLR_JUL25?interval=D",
        "Cookie": "_mtz_web_key=SFMyNTY.g3QAAAACbQAAAAtfY3NyZl90b2tlbm0AAAAYUDBtVWZhVjk5c2p5b19lbE5McDNndHFnbQAAAApzZXNzaW9uX2lkbQAAAEBWb0dXeHZmM1VUYWNzL3RjazlUUFg5bmIwVndTNExmdlYxNXVUamFBMmZJSVYxekpJOE16a2Nhaitaa3BIa29S.N1mYWTuFKIYfmWN6AAahiz0EkKz_-NP93rMsbS6moNM"

    }

    response = requests.get(url, headers=headers)
    data = response.json()
    
    df = pd.DataFrame(data)

    if df.empty:
        print("No trades data available for today.")
        return df
    # Flatten 'sides' list to a single value (assuming single-element list)
    df['side'] = df['sides'].str[0].map({'1': 'buy', '2': 'sell'})
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    # Drop original 'sides' column if not needed
    df.drop(columns='sides', inplace=True)
    df['timestamp'] = pd.to_datetime(df['timestamp']).dt.strftime('%Y-%m-%d %H:%M:%S')
    print(df[['timestamp', 'price', 'volume', 'side']])


trades =[]
df = fetch_minute_trades_today(trades)
print(df)