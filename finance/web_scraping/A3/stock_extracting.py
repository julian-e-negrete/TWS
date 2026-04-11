import requests
from bs4 import BeautifulSoup

url = "https://finance.yahoo.com/quote/AAPL"
headers = {"User-Agent": "Mozilla/5.0"}
res = requests.get(url, headers=headers)
soup = BeautifulSoup(res.text, "html.parser")

def extract_data(label):
    try:
        return soup.find("td", {"data-test": f"{label}-value"}).text.strip()
    except:
        return None

data = {
    "Price": soup.find("fin-streamer", {"data-field": "regularMarketPrice"}).text,
    "Previous Close": extract_data("PREV_CLOSE"),
    "Open": extract_data("OPEN"),
    "Bid": extract_data("BID"),
    "Ask": extract_data("ASK"),
    "Day's Range": extract_data("DAYS_RANGE"),
    "52 Week Range": extract_data("FIFTY_TWO_WK_RANGE"),
    "Volume": extract_data("TD_VOLUME"),
    "Avg Volume": extract_data("AVERAGE_VOLUME_3MONTH"),
    "Market Cap": extract_data("MARKET_CAP"),
    "Beta": extract_data("BETA_5Y"),
    "PE Ratio (TTM)": extract_data("PE_RATIO"),
    "EPS (TTM)": extract_data("EPS_RATIO"),
    "Earnings Date": extract_data("EARNINGS_DATE"),
    "Div & Yield": extract_data("DIVIDEND_AND_YIELD"),
    "Ex-Dividend Date": extract_data("EX_DIVIDEND_DATE"),
    "1y Target Est": extract_data("ONE_YEAR_TARGET_PRICE"),
}

print(data)
