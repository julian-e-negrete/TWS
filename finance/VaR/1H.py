import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Portfolio details
portfolio = {
    'MELI.BA': {'shares': 2, 'purchase_price': 18300},
    'TSLA.BA': {'shares': 1, 'purchase_price': 26600},
    'AMZN.BA': {'shares': 2, 'purchase_price': 1706}
}

# Define the rolling download function for intraday data
def download_intraday_data(ticker, start, end, interval='1h'):
    """Download intraday data for a ticker between two dates using rolling chunks."""
    data = pd.DataFrame()
    current_start = start
    while current_start < end:
        current_end = min(current_start + timedelta(days=60), end)
        try:
            # Define valid market hours (ART)
            market_open_art = 10  # 10:00 ART
            market_close_art = 17  # 17:00 ART
            
            chunk = yf.download(ticker, 
                                start=current_start.strftime('%Y-%m-%d'),
                                end=current_end.strftime('%Y-%m-%d'),
                                interval=interval)['Adj Close']
            
            # Ensure the index is in UTC
            chunk.index = chunk.index.tz_localize('UTC') if chunk.index.tz is None else chunk.index
            
            # Convert UTC to ART (UTC-3)
            chunk.index = chunk.index.tz_convert('Etc/GMT+3')
            
            # Filter for valid market hours (10:00–17:00 ART)
            chunk = chunk.between_time(f"{market_open_art}:00", f"{market_close_art}:00")
            
            
            data = pd.concat([data, chunk])
        except Exception as e:
            print(f"Error downloading data for {ticker}: {e}")
        current_start = current_end
    return data

# Define the date range
start_date = datetime(2024, 1, 1)
end_date = datetime(2024, 11, 15)

# Download intraday data for each stock
intraday_data = {}
for ticker in portfolio.keys():
    print(f"Downloading intraday data for {ticker}...")
    intraday_data[ticker] = download_intraday_data(ticker, start=start_date, end=end_date)

# Ensure all tickers' data are properly formatted
valid_tickers = {
    ticker: data for ticker, data in intraday_data.items() 
    if isinstance(data, pd.Series) or isinstance(data, pd.DataFrame) and not data.empty
}

# If no valid data is found
if not valid_tickers:
    raise ValueError("No valid intraday data found for any ticker in the portfolio.")

# Combine data into a single DataFrame
intraday_prices = pd.concat(valid_tickers.values(), axis=1)

# Assign proper column names (tickers) to the DataFrame
intraday_prices.columns = valid_tickers.keys()

# Drop rows with missing data to ensure all tickers have aligned timestamps
intraday_prices = intraday_prices.dropna()

# Debugging step: Print the first rows of the combined DataFrame
print(intraday_prices.head())

print(intraday_prices.tail())

# Calculate hourly returns
intraday_returns = np.log(intraday_prices / intraday_prices.shift(1)).dropna()

# Proceed with portfolio calculations
total_value = sum([portfolio[ticker]['shares'] * portfolio[ticker]['purchase_price'] for ticker in portfolio])
weights = np.array([
    portfolio[ticker]['shares'] * portfolio[ticker]['purchase_price'] / total_value 
    for ticker in valid_tickers.keys()
])

# Covariance matrix of hourly returns
cov_matrix_intraday = intraday_returns.cov()

# Portfolio mean return and volatility (hourly)
portfolio_mean_intraday = np.dot(weights, intraday_returns.mean())
portfolio_volatility_intraday = np.sqrt(np.dot(weights.T, np.dot(cov_matrix_intraday, weights)))

# Calculate VaR at 95% confidence level (1-hour horizon)
z_score = -1.65  # Z-score for 95% confidence (negative for loss)
portfolio_var_intraday = portfolio_mean_intraday - z_score * portfolio_volatility_intraday

# Portfolio Value at Risk in monetary terms (1-hour horizon)
VaR_value_intraday = portfolio_var_intraday * total_value

print(f"Intraday Portfolio Value at Risk (1-hour, 95% confidence): ${VaR_value_intraday:,.2f}")

# Monte Carlo simulation for CVaR
simulations = 10000  # Number of simulations
mu = portfolio_mean_intraday  # Hourly mean return
sigma = portfolio_volatility_intraday  # Hourly volatility

# Simulate portfolio returns over 1 hour
simulated_returns = np.random.normal(mu, sigma, simulations)

# Simulate portfolio values after 1 hour
portfolio_simulated_values = total_value * (1 + simulated_returns)

# Calculate 5th percentile VaR threshold
VaR_threshold_intraday = np.percentile(portfolio_simulated_values, 5)

# Calculate CVaR as the mean of losses beyond the VaR threshold
CVaR_intraday = portfolio_simulated_values[portfolio_simulated_values <= VaR_threshold_intraday].mean()

print(f"Intraday Portfolio Conditional Value at Risk (1-hour, 95% confidence): ${CVaR_intraday:,.2f}")
