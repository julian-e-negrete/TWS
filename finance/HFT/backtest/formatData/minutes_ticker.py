import requests
import pandas as pd
from datetime import datetime, time
from zoneinfo import ZoneInfo
import locale
from finance.HFT.backtest.db.get_cookies import get_cookies
from babel.dates import format_datetime

def fetch_minute_trades(date, enddate,symbol, interval="1" ):
    tz = ZoneInfo("America/Argentina/Buenos_Aires")
    

    start = datetime.combine(date.date(), time(10, 0, 0, tzinfo=tz))
    end   = datetime.combine(enddate.date(), time(21, 0, 0, tzinfo=tz))



    # locale for Spanish month abbreviation
    tz = ZoneInfo("America/Argentina/Buenos_Aires")
    date = datetime.now(tz)

    month_name = format_datetime(date, "MMM", locale="es_ES").upper()

    # symbol = f"rx_DDF_DLR_{month_name}25"

    url = (
        f"https://matriz.eco.xoms.com.ar/api/v2/series/securities/"
        f"{symbol}?resolution=1&from={start.isoformat()}&to={end.isoformat()}&_ds=1755704043509-197420"
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0) Gecko/20100101 Firefox/141.0",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.5",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Sec-GPC": "1",
        "Referer": f"https://matriz.eco.xoms.com.ar/security/{symbol}?interval={interval}",
        "Cookie": f"_mtz_web_key={get_cookies()}"
    }


    response = requests.get(url, headers=headers)
    response.raise_for_status()
    data = response.json()
    series = data.get("series", [])
    df = pd.DataFrame(series)
    
    if df.empty:
        return df

    df["timestamp"] = pd.to_datetime(df["d"]).dt.tz_convert(tz)

    df = df.rename(columns={
        "c": "close",
        "o": "open",
        "h": "high",
        "l": "low",
        "v": "volume"
    })[["timestamp", "open", "high", "low", "close", "volume"]]

    return df


if __name__ == "__main__":
    df_trades = fetch_minute_trades()
    print(df_trades)
