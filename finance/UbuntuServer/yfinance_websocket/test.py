import yfinance as yf

ticker = "BTC-USD"
data = yf.download(ticker, period="max", interval="1d", progress=False)

if data.empty:
    print(f"⚠️ No data found for {ticker}")
else:
    print(f"✅ Data retrieved for {ticker}:\n", data.tail())


