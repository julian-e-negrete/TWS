import requests
import pandas as pd
from datetime import datetime, timedelta, time, timezone
from zoneinfo import ZoneInfo

def fetch_minute_trades_today():
    tz = ZoneInfo("America/Argentina/Buenos_Aires")
    now = datetime.now(tz)

    start = now.replace(hour=11, minute=0, second=0, microsecond=0)
    end = now
    print(end)

    url = (
        f"https://matriz.eco.xoms.com.ar/api/v2/series/securities/rx_DDF_DLR_JUL25"
        f"?resolution=1&from={start.isoformat()}&to={end.isoformat()}&_ds=1753886875509-429083"
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.5",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Sec-GPC": "1",
        "Referer": "https://matriz.eco.xoms.com.ar/security/rx_DDF_DLR_JUL25?interval=1",
        "Cookie": "_mtz_web_key=SFMyNTY.g3QAAAACbQAAAAtfY3NyZl90b2tlbm0AAAAYb3hGbC1wbFRaTEZ4VFl2ZmVaTnRoQm02bQAAAApzZXNzaW9uX2lkbQAAAEAwb2FBTCs0RzdiUHpjZ05QbUlHTno0V09uVG5SajRkZzBnQzRwaEwwSHVPSXpiWm1LMjk0QUUxVUZNOEZKR2dp.D2A28OF1WlLgOd0o-ir3I1RC753sUfMFbDSvNUte8F0"

    }

    response = requests.get(url, headers=headers)
    response.raise_for_status()

    data = response.json()
     # Extract series data
    series = data.get("series", [])

    # Build DataFrame
    df = pd.DataFrame(series)
    if df.empty:
        return df

    # Convert timestamp and localize
    df["timestamp"] = pd.to_datetime(df["d"]).dt.tz_convert(tz)
    
    # Select relevant columns and rename for clarity
    df = df.rename(columns={
        "c": "close",
        "o": "open",
        "h": "high",
        "l": "low",
        "v": "volume"
    })[["timestamp", "open", "high", "low", "close", "volume"]]

    return df


if __name__ == "__main__":
    # Fetch and print today's minute trades
    #print("Fetching today's minute trades...")
     # Call the function to fetch data

    df = fetch_minute_trades_today()
    print(df)