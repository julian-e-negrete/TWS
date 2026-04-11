import yfinance as yf

ticker = "BTC-USD"
data = yf.download(ticker, period="7d", interval="1h", progress=False)

if data.empty:
    print(f"⚠️ No data found for {ticker}")
else:
    print(f"✅ Data retrieved for {ticker}:\n", data.tail())
