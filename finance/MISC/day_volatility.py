import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os


def get_7day_volatility_and_mean_return(stock_ticker):
    """
    Calculate the volatility and mean return of a stock around a specific date.

    Args:
        stock_ticker (str): The stock ticker symbol (e.g., "AAPL").
        date (str): The date for analysis in YYYY-MM-DD format.
        window (int): The number of days to calculate historical statistics (default: 30).

    Returns:
        dict: A dictionary with the daily return, mean return, and volatility.
    """
    # Fetch historical daily data
    start_date = (datetime.today() - timedelta(days=720)).strftime("%Y-%m-%d")
    end_date =  (datetime.today() - timedelta(days=1)).strftime("%Y-%m-%d")
   
        
    data = yf.download(tickers=stock_ticker, start=start_date,end=end_date, period="1d")
    
    
    
    # Check if data is available
    if data.empty:
        return {"error": f"No daily data available for {stock_ticker}."}
    
    data.columns = data.columns.droplevel(1)
    df = pd.DataFrame(data)
    
    # get the close values of the data into a list
    columns_values_list = df[["Close"]].values.tolist()
    

    
    
    mean_return = 0
    daily_return_lst = [] 
    
    for i in range(0, len(columns_values_list)):
        if (i == 0): continue;
        daily_return_lst.append((columns_values_list[i][0] - columns_values_list[i-1][0])  / columns_values_list[i-1][0] )
        
    daily_return_lst  = np.array(daily_return_lst)
    # Calculate the mean return
    mean_return = np.mean(daily_return_lst)
    columns_values_list =  np.array(columns_values_list)
    mean_Close = np.mean(columns_values_list)
    percentile_5 = np.percentile(columns_values_list, 5)  # 5th percentile (Value-at-Risk)
    percentile_95 = np.percentile(columns_values_list, 95)  # 95th percentile
    

    # Step 2: Calculate the squared differences from the mean
    squared_differences = []
    for r in daily_return_lst:
        # (Ri ​− Rˉ)2
        squared_difference = (r - mean_return) ** 2
        squared_differences.append(squared_difference)

    # Step 3: Calculate the variance
    variance = sum(squared_differences) / (len(daily_return_lst) - 1)
    
    # Step 4: Calculate the volatility (standard deviation)
    volatility = variance ** 0.5
    
    
    print("|--------------------------------------------------------------------------------------|")
    print(f"Calculations of: {stock_ticker} from: {start_date}  to {end_date}")
    
    print(f"Mean Return: {(mean_return * 100): .3f}%")
    print(f"Variance: {(variance * 100): .3f}%")
    print(f"Volatility: {(volatility * 100): .3f}%")
    
    print(f"\nmean value of stock: {mean_Close}")
    print(f"Total Value-at-Risk (5th Percentile): ${percentile_5}")
    print(f"95th Percentile Price per Share : ${percentile_95}")
    
    
    return daily_return_lst



def SharpeRatio():
    # Load the CSV file
    df = pd.read_excel('C:\\00_Julian\\Personal\\python\\AlgoTrading\\finance\\rentafija\\Export.xlsx', engine='openpyxl')  # Adjust if needed, for now assuming tab delimiter

    # Convert 'Cierre Hoy' (or 'Último Hoy') column to numeric values
    df['volatility'] = pd.to_numeric(df['Variación'], errors='coerce')

    
    
    min_volatility = df['volatility'].min()
    print(min_volatility)
    # Drop missing values (first row will have NaN return)
    #df = df.dropna()
    
    #print(df['Return'])
    """
    # Calculate the mean return and standard deviation of returns
    mean_return = df['Return'].mean()
    std_dev = df['Return'].std()

    # Set the risk-free rate (for example, 0.08/252 for an annual rate of 8%)
    risk_free_rate = 0.08 / 252  # Assuming 8% annual risk-free rate

    # Calculate the Sharpe ratio
    sharpe_ratio = (mean_return - risk_free_rate) / std_dev

    print(f'Sharpe Ratio: {sharpe_ratio}')
    """

os.system("cls")

# Example usage
stock_ticker = "BBD.BA"  # Replace with the stock ticker

daily_values = get_7day_volatility_and_mean_return(stock_ticker)

# Convert daily returns  into a numpy array for analysis

mean_final_price = np.mean(daily_values)

SharpeRatio();