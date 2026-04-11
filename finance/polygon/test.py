import requests
import pandas as pd 
import time

from finance.config import settings

url = "https://api.polygon.io/v3/reference/options/contracts"
## get all contracts of a ticker
api_key = settings.polygon.api_key
params = {
    "underlying_ticker": "GGAL",
    "contract_type": "call",
    "expired": "false",
    "order": "asc",
    "limit": 10,
    "sort": "expiration_date",
    "apiKey": f"{api_key}"
}

response = requests.get(url, params=params)

if response.ok:
    data = response.json()
    df = pd.json_normalize(data["results"])
    print(df)
else:
    print(response.status_code, response.text)



# for index, row in df.iterrows():
#     contract_url = f"https://api.polygon.io/v3/reference/options/contracts/{row['ticker']}"
#     params = {"apiKey": api_key}
#     time.sleep(12)
#     response = requests.get(contract_url, params=params)
#     if response.ok:
#         data = response.json()
#         print(data)
#     else:
#         print(response.status_code, response.text)
    


