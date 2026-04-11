import asyncio
import threading
import websockets
import json
import pandas as pd
import yfinance as yf

# Shared data store
live_data = {}

def start_websocket_client():
    async def run_client():
        async with websockets.connect("ws://192.168.0.244:8765") as websocket:
            tickers = ["JPY=X", "EURUSD=X","ARS=X", "^TNX", "^FVX", "^IRX", "GGAL.BA", "YPFD.BA", "BBD.BA"]
            await websocket.send(json.dumps({"tickers": tickers}))
            print(f"📤 Sent tickers: {tickers}")

            while True:
                message = await websocket.recv()
                stock_data = json.loads(message)

                # Parse the message
                for ticker, values in stock_data.items():
                    if ticker not in live_data:
                        live_data[ticker] = []
                    clean_entry = {k.split(", ")[0].strip("('"): v for k, v in values.items()}
                    clean_entry["timestamp"] = pd.Timestamp.now()
                    live_data[ticker].append(clean_entry)
                    
    def start_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_client())

    threading.Thread(target=start_loop, daemon=True).start()
    
    
def get_options_chain():
    try:
        

        ars_usd = yf.Ticker("ARS=X")
        ars_usd_last_price = ars_usd.fast_info['lastPrice']

        chain = yf.Ticker("GGAL").option_chain("2025-06-20")
        
        chain.calls["strike"] /=  10
        chain.calls["strike"] *= ars_usd_last_price
        

        chain.calls["lastPrice"] /=  10
        chain.calls["lastPrice"] *= ars_usd_last_price
        
        chain.calls["bid"] /=  10
        chain.calls["bid"] *= ars_usd_last_price
        
        
        chain.calls["ask"] /=  10
        chain.calls["ask"] *= ars_usd_last_price
        
        chain.calls["volume"] *= 10
        
        chain.calls["impliedVolatility"] *=  100  
        
        
         
        chain.puts["strike"] /=  10
        chain.puts["strike"] *= ars_usd_last_price
        
        
        chain.puts["lastPrice"] /=  10
        chain.puts["lastPrice"] *= ars_usd_last_price
        
        chain.puts["bid"] /=  10
        chain.puts["bid"] *= ars_usd_last_price
        
        
        chain.puts["ask"] /=  10
        chain.puts["ask"] *= ars_usd_last_price
        
        chain.puts["volume"] *= 10
        
        chain.puts["impliedVolatility"] *=  100  
        
        
        return chain.calls, chain.puts
    except Exception as e:
        return None, None
