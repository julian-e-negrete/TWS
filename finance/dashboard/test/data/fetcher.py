import yfinance as yf

ars_usd = yf.Ticker("ARS=X")
ars_usd_last_price = ars_usd.fast_info['lastPrice']

def get_stock_data(ticker, period="1mo", interval="1d"):
    try:
        data = yf.Ticker(ticker).history(period=period, interval=interval)
        
        
        # relacion adr -> accion // 10 -> 1
        data["Close"] /=  10
        # lo multiplico por el precio del dolar libre
        data["Close"] *= ars_usd_last_price
        
        return data
    except Exception as e:
        return None

def get_options_chain():
    try:
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
