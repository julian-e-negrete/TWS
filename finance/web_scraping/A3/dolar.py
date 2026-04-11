from finance.utils.logger import logger
import aiohttp
import asyncio
import time
import pandas as pd
from rich.console import Console

async def fetch_data():
    url = "https://api.marketdata.mae.com.ar/api/mercado/datos/FOR"
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
    while True:
        logger.info("Fetching data...")
        data = asyncio.run(fetch_data())
        df = pd.DataFrame(data)
        if df.empty:
            logger.info("couldn't fetch data ")
            exit()

        # Convert date fields to datetime
        #df['fechaLiquidacion'] = pd.to_datetime(df['fechaLiquidacion'], errors='coerce')
        print(df[["ticker","segmento", "minimo", "maximo","ultimo", "variacion"]])
        # Example: filter by ticker
        usmep_data = df[df['ticker'] == 'USMEP']
        usmep_data_minorista = usmep_data[usmep_data['segmento'] == 'Minorista' ]
        subset = usmep_data_minorista[["ticker", "minimo", "maximo","ultimo", "variacion"]]
        

        # console = Console()
        # console.logger.info(f"[bold green]{subset.iloc[0]}![/bold green]")
        #print(usmep_data_minorista["ultimo"])
        time.sleep(60)  # Fetch data every 60 seconds
 
