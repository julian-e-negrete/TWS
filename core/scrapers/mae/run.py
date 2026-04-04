# scrapers/mae/run.py — P1 MAE REST scraper / SPEC §1 P1 / T-MOD-1
import asyncio
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
import aiohttp
import pandas as pd
from logger import get_logger
from fetch import async_fetch
from notifier import notify

_log = get_logger("mae")
URL = "https://api.marketdata.mae.com.ar/api/mercado/datos/FOR"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Referer": "https://marketdata.mae.com.ar/",
}


async def run():
    async with aiohttp.ClientSession() as session:
        status, body = await async_fetch(session, "GET", URL, headers=HEADERS)
        import json
        data = json.loads(body)
        df = pd.DataFrame(data)
        if df.empty:
            _log.warning("MAE returned empty dataset")
            return df
        _log.info("MAE fetched %d rows", len(df))
        return df


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except Exception as e:
        notify("mae", e)
        raise
