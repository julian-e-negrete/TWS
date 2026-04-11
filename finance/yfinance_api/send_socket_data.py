import asyncio
import yfinance as yf
import websockets
import json
import time

# List of tickers you're interested in
tickers = ['AAPL', 'GOOG', 'TSLA']

# Function to fetch stock data from Yahoo Finance
async def get_stock_data(ticker):
    data = yf.download(ticker, period='1d', interval='1m', progress=False)
    return data.tail(1).to_dict()  # Get the most recent 1-minute data

# WebSocket server to send stock data to clients
async def send_stock_data(websocket, path):
    while True:
        # Create a dictionary of latest stock data for all tickers
        stock_data = {}
        
        # Loop through all tickers and get their data
        for ticker in tickers:
            stock_data[ticker] = await get_stock_data(ticker)
        
        # Convert the dictionary to JSON
        json_data = json.dumps(stock_data)
        
        # Send data to client
        await websocket.send(json_data)
        
        # Sleep for 60 seconds (to mimic 1-minute updates)
        await asyncio.sleep(60)

# Start the WebSocket server
async def main():
    server = await websockets.serve(send_stock_data, "localhost", 8765)
    print("WebSocket server started on ws://localhost:8765")
    await server.wait_closed()

# Run the WebSocket server
if __name__ == "__main__":
    asyncio.run(main())
