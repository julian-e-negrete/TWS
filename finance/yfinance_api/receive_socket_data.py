import asyncio
import websockets
import json
import pandas as pd
import os

from tabulate import tabulate

# WebSocket client to receive and display stock data
async def receive_stock_data():
    async with websockets.connect("ws://192.168.0.244:8765") as websocket:
        """
        U.S. T-Bill Futures,Jun-2025 (TBF3=F)
        period of data retrieving is 6days, so in sundays no data will be retrieved
        """
        tickers = ["JPY=X","EURUSD=X", "^TNX", "^FVX", "^IRX" ,"ARS=X", "ETH-USD"]
        await websocket.send(json.dumps({"tickers": tickers}))
        print(f"📤 Sent tickers: {tickers}")
        # Store received data
        all_data = []
        
        while True:
            # Receive data from the WebSocket server
            data = await websocket.recv()
            stock_data = json.loads(data)
            
            #print(stock_data)
            normalized_data = {}
            for ticker, values in stock_data.items():
                normalized_data[ticker] = {k.split(", ")[0].strip("('") : v for k, v in values.items()}

            # Convert the received JSON data into a DataFrame
            df = pd.DataFrame.from_dict(normalized_data, orient="index")

            # Add a timestamp for tracking
            df["timestamp"] = pd.Timestamp.now()

            # Store the data in a list
            all_data.append(df)

            os.system("clear")
            # Print the structured DataFrame
            print("\n📊 Received Data:")
            print(tabulate(df, headers="keys", tablefmt="fancy_grid"))
            
            
            await asyncio.sleep(60)  # Wait for the next update

# Run the WebSocket client
if __name__ == "__main__":
    asyncio.run(receive_stock_data())
