import numpy as np
import yfinance as yf
import matplotlib.pyplot as plt
import pandas as pd
import os

# Fetch historical data for Tesla (TSLA)
ticker = 'MELI.BA'
path = "C:\\JULIAN\\DESARROLLO\\Python\\AlgoTrading\\monteCarlo\\finance"

csv_filename = f'{path}\\{ticker}_data.csv'

data = yf.download(ticker, start='2024-01-01', end='2024-11-14')
data.to_csv(csv_filename)
    
# Calculate daily returns
data['Daily Return'] = data['Adj Close'].pct_change()

# Calculate mean and volatility from historical data
mu = data['Daily Return'].mean() * 252  # Annualized mean return
sigma = data['Daily Return'].std() * np.sqrt(252)  # Annualized volatility

# Flatten the multi-level columns
data.columns = data.columns.droplevel(1)  # Drop the 'Price' level in the multi-level columns




# Monte Carlo Simulation Parameters
initial_stock_price = data['Adj Close'][-1]  # Last available stock price
days = 252  # Number of trading days in a year
simulations = 10000  # Number of simulations
print(initial_stock_price)

# Run Monte Carlo simulations
final_values = []
for _ in range(simulations):
    # Simulate daily returns over 252 days
    daily_returns = np.random.normal(mu / days, sigma / np.sqrt(days), days)
    # Calculate the stock price over time
    stock_price = initial_stock_price * np.cumprod(1 + daily_returns)[-1]
    final_values.append(stock_price)

# Convert final values into a numpy array for analysis
final_values = np.array(final_values)

# Plot the histogram of final stock prices
plt.hist(final_values, bins=50, edgecolor='black')
plt.title(f"Monte Carlo Simulation: {ticker} Stock Price Distribution")
plt.xlabel("Stock Price")
plt.ylabel("Frequency")
plt.savefig(f"{path}\\{ticker}_Histogram.png")
plt.show()

# Calculate some statistics
mean_value = np.mean(final_values)
percentile_5 = np.percentile(final_values, 5)  # 5th percentile (Value-at-Risk)
percentile_95 = np.percentile(final_values, 95)  # 95th percentile

print(f"Mean final stock price: ${mean_value:,.2f}")
print(f"5th percentile (Value-at-Risk): ${percentile_5:,.2f}")
print(f"95th percentile: ${percentile_95:,.2f}")

