import httpx
import asyncio
import pandas as pd

# feth data by date
async def fetch_data():
    url = "https://matbarofex.primary.ventures/api/v2/series/securities/rx_DDF_DLR_ENE26"
    params = {
        "resolution": "D",
        "from": "2024-04-25T00:00:00.000Z",
        "to": "2025-07-18T00:00:00.000Z",
        "_ds": "1752758786364-102097"
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.5",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Sec-GPC": "1",
        "Referer": "https://matbarofex.primary.ventures/security/rx_DDF_DLR_ENE26"
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, headers=headers)
        data = response.json()
        return data


if __name__ == "__main__":
    response = asyncio.run(fetch_data())
    df = pd.DataFrame(response['series'])
    df['d'] = pd.to_datetime(df['d'])  # Convert date to datetime
    df = df.rename(columns={
        'd': 'date',
        'o': 'open',
        'h': 'high',
        'l': 'low',
        'c': 'close',
        'v': 'volume'
    })

    # Optional: reorder columns
    df = df[['date', 'open', 'high', 'low', 'close', 'volume']]
    
    print(df)
    import mplfinance as mpf

    df.set_index('date', inplace=True)
    mpf.plot(df, type='candle', style='charles', volume=True)

# To run:
# asyncio.run(fetch_data())
