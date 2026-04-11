import requests
import pandas as pd
from datetime import datetime
import locale

import asyncio
from get_cookies import get_cookies

    
async def fetch_minute_trades_today(trades, cookie): 

    
    locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')  # or 'es_AR.UTF-8' for Argentina
    month_name = datetime.now().strftime('%B')[:3].lower()
    url = f"https://matriz.eco.xoms.com.ar/api/v2/trades/securities/rx_DDF_DLR_{month_name.upper()}25?_ds=&_ds=1753889449163-979204"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.5",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Sec-GPC": "1",
        "Referer": f"https://matriz.eco.xoms.com.ar/security/rx_DDF_DLR_{month_name.upper()}25?interval=D",
        "Cookie": f"_mtz_web_key={cookie}"

    }

    response = requests.get(url, headers=headers)
    data = response.json()
    # handle 401
    if response.status_code != 200: 
        
        print("error")
        #_mtz_web_key = get_cookies()       
        return
        # key = get_cookies()
        # trades = []
        # fetch_minute_trades_today(trades, key)
        
        
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
    # Example: mapping full strings to 'B' or 'S'
    df["side"] = df["side"].str.upper().str[0]

    #print(df[['timestamp', 'price', 'volume', 'side']])


    records = df[["timestamp", "price", "volume", "side"]].values.tolist()
    print(df[["timestamp", "price", "volume", "side"]])

        #return df[['timestamp', 'price', 'volume', 'side']]




if __name__ == "__main__":
    _mtz_web_key = get_cookies()
    trades =[]
    print(_mtz_web_key)
    asyncio.run(fetch_minute_trades_today(trades, _mtz_web_key))
    # df = fetch_minute_trades_today(trades, _mtz_web_key)
    # print(df)