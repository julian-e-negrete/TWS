import asyncio
import yfinance as yf
import websockets
import json


# Default tickers (will be updated by the client)
default_tickers = ["BTC-USD", "ETH-USD", "SOL-USD"]

async def get_stock_data(ticker):
    """Fetches the latest available 5-minute data for a given ticker."""
    data = yf.download(ticker, period="1d", interval="5m", progress=False, auto_adjust=False)
    if data.empty:
        return {"error": f"No data for {ticker}"}
    
    
    last_row = data.tail(1).to_dict(orient='records')[0]
    last_row = {str(k): v for k, v in last_row.items()}
    return last_row

async def send_stock_data(websocket, path):
    """Handles communication with a single client: receives tickers & sends data."""
    tickers = default_tickers.copy()  # Start with default tickers
    
    try:
        async for message in websocket:
            try:
                request = json.loads(message)
                if "tickers" in request and isinstance(request["tickers"], list):
                    tickers = request["tickers"]  # Update tickers based on client request
                    print(f"✅ Updated tickers: {tickers}")
            except json.JSONDecodeError:
                print("⚠️ Invalid JSON received")

            while True:
                stock_data = {}
                for ticker in tickers:
                    data = await get_stock_data(ticker)
                    
                    stock_data[ticker] = data
                
                json_data = json.dumps(stock_data)
                await websocket.send(json_data)
                await asyncio.sleep(60)  # Update every 60 seconds

    except websockets.exceptions.ConnectionClosed:
        print("🔌 Client disconnected")

async def main():
    server = await websockets.serve(send_stock_data, "0.0.0.0", 8765)
    print("✅ WebSocket Server Started: ws://0.0.0.0:8765")
    await server.wait_closed()

if __name__ == "__main__":
    asyncio.run(main())
