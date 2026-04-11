
import yfinance as yf
import matplotlib.pyplot as plt
import matplotlib
import pandas as pd

from datetime import datetime
import os






# Set the backend to TkAgg for Linux GUI display
matplotlib.use('TkAgg')


leverage_currency = "BTC-USD"



assets = [leverage_currency, 'EWZ']
start_date = '2021-01-01'
end_date = datetime.now()

# Download the data
data = yf.download(assets, start=start_date, end=end_date)['Close']

# Create a figure and a primary y-axis
fig, ax1 = plt.subplots(figsize=(14, 7))

# Plot Bitcoin on the primary y-axis
ax1.plot(data.index, data[leverage_currency], label=leverage_currency, color='orange')
ax1.set_xlabel('Date')
ax1.set_ylabel(f'{leverage_currency} (USD)', color='orange')
ax1.tick_params(axis='y', labelcolor='orange')

# Create a secondary y-axis for EWZ
ax2 = ax1.twinx()
ax2.plot(data.index, data['EWZ'], label='Brazil ETF (EWZ)', color='blue')
ax2.set_ylabel('Brazil ETF (EWZ) Price (USD)', color='blue')
ax2.tick_params(axis='y', labelcolor='blue')

# Add title and grid
plt.title(f'{leverage_currency} and Brazil ETF (EWZ) Prices')
ax1.grid(True)

# Show the plot
plt.show()


