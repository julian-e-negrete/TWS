import ssl
import aiohttp
import asyncio
import pandas as pd
import json

async def fetch_data():
    url = "https://open.bymadata.com.ar/vanoms-be-core/rest/api/bymadata/free/cedears"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.5",
        "Cache-Control": "no-cache,no-store,max-age=1,must-revalidate",
        "Token": "dc826d4c2dde7519e882a250359a23a0",
        "Expires": "1",
        "Options": "renta-variable",
        "Content-Type": "application/json",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Sec-GPC": "1",
        "Referer": "https://open.bymadata.com.ar/"
    }
    payload = {
        "excludeZeroPxAndQty": True,
        "T1": True,
        "T0": False
    }

    conn = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=conn) as session:
        async with session.post(url, headers=headers, data=json.dumps(payload)) as response:
            print("Status:", response.status)
            #text = await response.text()
            #print("Raw response:", text)
            return await response.json()


# Example to run the async function
if __name__ == "__main__":
    result = asyncio.run(fetch_data())
    
    df = pd.DataFrame(result)
    
    print(df[df["symbol"] == "BBDD"])

    # Convert date fields to datetime
    
    #print(df)
# 
