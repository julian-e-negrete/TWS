import aiohttp
import asyncio
import pandas as pd
from config import api_key_prod, api_key_UAT

async def fetch_data():
    url = "https://api.mae.com.ar/MarketData/v1/mercado/cotizaciones/rentafija"
    
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key_prod,  # Removed curly braces - use the variable directly
        "Cookie": "incap_ses_1233_3007564=FsWPHCdNPBt+wWO6Yn8cEXlDo2gAAAAAANQXkXeRX2dZDmEldjUGNA==; nlbi_3007564=LAdPeGrkqlKriYSz88KSKQAAAADRdnIZG6r8xthVUdMtg3ec; visid_incap_3007564=BDzKW/a7QDKGIFUE0/y+Q3lDo2gAAAAAQUIPAAAAAADjBAFD31mS/Y9ZfFTJEm4z"
    }
    
    params = {
        # Optional parameters - include only if needed
        # "segmento": "BT",
        "plazo": "000",
        # "moneda": "D",
        # "ticker": "AL30D",
        # "pageNumber": 1
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as response:
                response.raise_for_status()
                data = await response.json()
                return data
                
    except aiohttp.ClientError as e:
        print(f"HTTP Error: {e}")
        return None

async def main():
    print("Fetching data...")
    data = await fetch_data()
    
    if not data:
        print("Failed to fetch data")
        return
    
    df = pd.DataFrame(data)
    
    if df.empty:
        print("No data available")
        return
    
    # Example filtering (uncomment if needed)
    # df = df[["ticker","descripcion", "fechaLiquidacion", "moneda", "segmento", "plazo", "volumen", "minimo", "maximo", "ultimo", "variacion"]]
    print(df.tail())
    # print(lecap_df)
    df = df[["ticker","descripcion", "moneda", "segmento", "plazo", "volumenAcumulado", "precioUltimo", "variacion"]]
    #print(df['ticker'].str.contains('S15G5', case=False, na=False))
    lecap_df = df[df['descripcion'].str.contains('LECAP', case=False, na=False) & df["segmento"].str.contains("Bilateral TRD", case=False, na=False)]
    print("LECAP Data:")
    print(lecap_df)

if __name__ == "__main__":
    asyncio.run(main())