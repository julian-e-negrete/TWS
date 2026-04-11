import requests

url = "https://api.nasdaq.com/api/quote/BBD/info?assetclass=stocks"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0) Gecko/20100101 Firefox/141.0",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.5",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "Sec-GPC": "1",
    "Referer": "https://www.nasdaq.com/"
}

response = requests.get(url, headers=headers)
data = response.json()

print(data)
