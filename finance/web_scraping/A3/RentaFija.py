import aiohttp
import asyncio
import time
import pandas as pd
from rich.console import Console

async def fetch_data():
    url = "https://api.marketdata.mae.com.ar/api/mercado/datos/RF"
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
    
    print("Fetching data...")
    data = asyncio.run(fetch_data())
    df = pd.DataFrame(data)

    df = df[["ticker","descripcion", "fechaLiquidacion", "moneda", "segmento", "plazo", "volumen", "minimo", "maximo", "ultimo", "variacion"]]
    # convierto en procentaje
    # df["variacion"] = df["variacion"] *100
    
    lecap_df = df[df['descripcion'].str.contains('LECAP', case=False, na=False)]

    print(f"LECAP Data:")
    print(lecap_df)
    
    
    
    

    # console = Console()
    # console.print(f"[bold green]{subset.iloc[0]}![/bold green]")
    # #print(usmep_data_minorista["ultimo"])
    

