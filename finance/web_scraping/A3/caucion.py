import aiohttp
import asyncio
import pandas as pd
import humanize

async def fetch_data():
    url = "https://api.marketdata.mae.com.ar/api/mercado/datos/CAU"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.5",
        "Content-Type": "application/json",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "Sec-GPC": "1",
        "Priority": "u=4",
        "Referer": "https://marketdata.mae.com.ar/"
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            return await response.json()



# Example to run the async function
if __name__ == "__main__":
    data = asyncio.run(fetch_data())
    df = pd.DataFrame(data)
    if(df.empty):
        print("No data available")
        exit()

    # Convert date fields to datetime
    #df['fechaLiquidacion'] = pd.to_datetime(df['fechaLiquidacion'], errors='coerce')

    # Example: filter by ticker
    # usmep_data = df[df['ticker'] == 'USMEP']
    # usmep_data_minorista = usmep_data[usmep_data['segmento'] == 'Minorista' ]
    subset = df[["descripcion", "ultimaTasa", "volumen", "variacion"]]

# Format as string
    for _, row in subset.iterrows():
        print(
            f"{row['descripcion']} | Tasa: {row['ultimaTasa']}% | Volumen: {humanize.intword(row['volumen'])} | Variación: {row['variacion']}%"
        )
    #print(df)
# 
