# scrapers/byma/run.py — P4 BYMA REST scraper / SPEC §1 P4 / T-MOD-1
import asyncio
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
import json
import aiohttp
import pandas as pd
from logger import get_logger
from fetch import async_fetch
from notifier import notify

_log = get_logger("byma")
URL = "https://open.bymadata.com.ar/vanoms-be-core/rest/api/bymadata/free/cedears"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0",
    "Accept": "application/json, text/plain, */*",
    "Token": "dc826d4c2dde7519e882a250359a23a0",
    "Content-Type": "application/json",
    "Referer": "https://open.bymadata.com.ar/",
}
PAYLOAD = {"excludeZeroPxAndQty": True, "T1": True, "T0": False}


async def run():
    conn = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=conn) as session:
        status, body = await async_fetch(session, "POST", URL, headers=HEADERS, data=json.dumps(PAYLOAD))
        df = pd.DataFrame(json.loads(body))
        _log.info("BYMA fetched %d rows", len(df))
        return df


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except Exception as e:
        notify("byma", e)
        raise
