import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def get_latest_intraday_volatility_and_mean_return(stock_ticker):
    """
    Calculate intraday volatility and mean return for the most recent trading day.
    """
    # Get the current date and subtract one day
    today = datetime.today()
    yesterday = today - timedelta(days=1)
    
    # Fetch the most recent trading data
    data = yf.download(tickers=stock_ticker, period="1d", interval="1m")
    
    # Check if data is available
    if data.empty:
        return {"error": f"No intraday data available for {stock_ticker}."}
    
    # Calculate intraday returns
    data['Return'] = data['Adj Close'].pct_change()
    
    # Calculate mean return and volatility
    mean_return = data['Return'].mean()
    intraday_volatility = data['Return'].std()
    
    return {
        "Mean Intraday Return": mean_return,
        "Intraday Volatility": intraday_volatility
    }

# Example usage
stock_ticker = "AAPL"  # Replace with the stock ticker
results = get_latest_intraday_volatility_and_mean_return(stock_ticker)
print(f"Results for {stock_ticker}:")
print(results)
