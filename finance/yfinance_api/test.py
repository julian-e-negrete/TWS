import yfinance as yf
import time

# Function to simulate WebSocket-like streaming
def stream_data(ticker_symbol):
    while True:
        data = yf.download(ticker_symbol, period="1d", interval="1m", progress=False)
        print(f"Latest Data for {ticker_symbol}:")
        print(data.tail(1))  # Print the most recent data
        time.sleep(60)  # Sleep for 60 seconds before fetching new data

# Start streaming AAPL data
stream_data("AAPL")
