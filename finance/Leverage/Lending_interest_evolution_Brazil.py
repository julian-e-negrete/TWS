import yfinance as yf
import matplotlib.pyplot as plt

import pandas as pd
import nasdaqdatalink as ndl

from datetime import datetime
import os




"""
DATABASE CFTC(COMODITY FUTURES TRADING COMMISION REPORTS)

TABLE	                                        TABLE CODE	TABLE DESCRIPTION
Futures and Options Metrics: OI and NT	        QDL/FON	    Quantitative data on Open Interest and Net Trading.
Legacy Futures and Options Metrics: OI and NT	QDL/LFON	Legacy format, historical data on Open Interest and Net Trading.
Futures and Options Metrics: CR	                QDL/FCR	    Quantitative data on Concentration Ratios.
Commodity Index Trader Supplemental Data	    QDL/CITS	Supplementary data for commodity index traders.


WORLD BANK

WB Data	                                        WB/DATA	    Values for all indicators and countries/regions
WB Metadata	                                    WB/METADATA	Names and descriptions of all indicators
"""

"""
website to check series_id = "https://data.worldbank.org/indicator/FR.INR.LEND?end=2017&locations=JP&start=2000"

FR.INR.LEND for lending interest rates
FR.INR.DPOP for deposit interest rates
FR.INR.TOTL.ZG for total interest rates
"""


from finance.config import settings

ndl.ApiConfig.api_key = settings.ndl.api_key

os.system("clear")



# Fetch the interest rate data for Japan (Lending interest rates)
data = ndl.get_table('WB/DATA', series_id='FR.INR.LEND', country_code='JPN')

# Filter the data by year after retrieving it
data_filtered = data[(data['year'] >= 2000) & (data['year'] <= 2025)]

# Fetch the EWZ index data using yfinance (Brazil ETF)
ewz = yf.download('EWZ', start='2000-01-01', end='2025-01-01')

# Resample the EWZ data to annual data for comparison (using 'YE' for year-end frequency)
ewz_annual = ewz['Close'].resample('YE').last()  # 'YE' is used for year-end frequency

# Print the first few rows of both datasets for debugging
print("Japan Interest Rate Data:")
print(data_filtered.head())

print("EWZ Annual Data:")
print(ewz_annual.head())

# Ensure both datasets have the same years for comparison by checking the common years
common_years = data_filtered['year'].isin(ewz_annual.index.year)

# Filter both datasets to only include common years
data_filtered = data_filtered[common_years]
ewz_annual = ewz_annual.loc[ewz_annual.index.year.isin(data_filtered['year'])]

# Check if we have any data left after filtering
print("Filtered Japan Interest Rate Data:")
print(data_filtered)

print("Filtered EWZ Annual Data:")
print(ewz_annual)

# President names and political alignments
presidents = {
    2003: ("Lula da Silva", "PT"),
    2006: ("Lula da Silva", "PT"),
    2010: ("Dilma Rousseff", "PT"),
    2016: ("Michel Temer", "MDB"),
    2018: ("Jair Bolsonaro", "PSL")
}

# Proceed if there is data to plot
if not data_filtered.empty and not ewz_annual.empty:
    # Create a figure with two subplots (one for each plot)
    fig, axes = plt.subplots(2, 1, figsize=(12, 12))

    # Plot the interest rate data (Japan) in the first subplot
    axes[0].plot(data_filtered['year'], data_filtered['value'], color='blue', label='Japan Interest Rate', marker='o')
    axes[0].set_xlabel('Year')
    axes[0].set_ylabel('Interest Rate (%)', color='blue')
    axes[0].tick_params(axis='y', labelcolor='blue')
    axes[0].set_title('Japan Lending Interest Rate')
    axes[0].grid(True)

    # Plot the EWZ data (Brazil ETF) in the second subplot
    axes[1].plot(ewz_annual.index, ewz_annual, color='red', label='EWZ Index', marker='x')
    axes[1].set_xlabel('Year')
    axes[1].set_ylabel('EWZ Index Price', color='red')
    axes[1].tick_params(axis='y', labelcolor='red')
    axes[1].set_title('Brazil EWZ Index')

    # Add annotations for presidents on the EWZ plot
    for year, (name, party) in presidents.items():
        if year in ewz_annual.index.year:
            y_value = ewz_annual.loc[str(year)].iloc[0]  # Get the first value of the year
            axes[1].annotate(f'{name} ({year})', 
                            xy=(pd.Timestamp(year, 1, 1), y_value), 
                            xytext=(pd.Timestamp(year, 1, 1), y_value * 1.05),
                            fontsize=10, color='black', ha='center', va='bottom')

    axes[1].grid(True)

    # Adjust layout to avoid overlap
    plt.tight_layout()

    # Show the plots
    plt.show()
else:
    print("No common data to plot.")