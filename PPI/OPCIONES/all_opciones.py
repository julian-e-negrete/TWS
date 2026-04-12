from ppi_client.api.constants import ACCOUNTDATA_TYPE_ACCOUNT_NOTIFICATION, ACCOUNTDATA_TYPE_PUSH_NOTIFICATION, \
    ACCOUNTDATA_TYPE_ORDER_NOTIFICATION
from ppi_client.ppi import PPI

import pandas as pd
import numpy as np


from collections import defaultdict
from datetime import datetime
import sys
import os

# Dynamically add the parent directory (PPI) to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, '..'))
sys.path.append(parent_dir)

# Now import the required modules

from PPI.classes import Account, Market_data, Instrument, Opciones

import QuantLib as ql


import re

def main():
    ppi = PPI(sandbox=False)
    
    account = Account(ppi)
            
   
    market = Market_data(account.ppi)
    

    
     
    date_format = "%Y-%m-%d"

    start_date = datetime.strptime('2024-01-01', date_format)
    end_date = datetime.now()

    #ticker = input("ingrese el ticker: ")
    ticker = "GGAL"
    ticker = ticker.strip().upper()


    lst_historical = market.get_historical_data(ticker, "ACCIONES", "A-24HS", start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
    df = pd.DataFrame(lst_historical)
    
    Opciones_class = Opciones(df, account, market)

    daily_volatility = Opciones_class.daily_volatility()
    annual_volatility = Opciones_class.annual_volatility()
    
    delta = len(Opciones_class.df['Daily Return'].dropna())        

    print(f"Desviación estándar diaria: {(daily_volatility * 100):.2f}%")
    print(f"Volatilidad en {delta} dias: {(annual_volatility * 100):.2f}%")
    

    
    precio_accion = market.get_market_data(ticker, "ACCIONES", "A-24HS")


    # Define option parameters
    spot_price = precio_accion["price"]  # Current price of the stock
    
    
    
    opciones_list = market.get_instrument(ticker, "BYMA", "OPCIONES")

        
    
    
    # Regular expression pattern to extract AR$ price and expiration date
    pattern = r"AR\$ (\d+\.\d{2}) Vto\. (\d{2}/\d{2}/\d{4})"
    # Extracted information
    gfgc_data, gfgv_data = extract_and_separate(opciones_list, pattern)
    
    
    after_march = datetime.strptime("2025-03-22", date_format)
    
    # all call options from april to the end of the year
    sorted_grouped_data_calls = filter_and_group_by_expiration(gfgc_data, after_march, spot_price)

    # all PUT options from april to the end of the year
    sorted_grouped_data_PUTS = filter_and_group_by_expiration(gfgv_data, after_march, spot_price)    
    
    
    
    # Print the results
    """
    for expiration_date, items in sorted_grouped_data.items():
        print(f"Expiration Date: {expiration_date.strftime('%d/%m/%Y')}")
        for item in items:
                
            print(f"  Ticker: {item['ticker']}, Price: {item['price']}, Expiration Date: {item['expiration_date']}")
        print()
    
    """
    """
    ALL the information about calls with it's expiration time price and ticker processed
    """    

    
    # Define option parameters
    risk_free_rate = 0.30  # 30% tasa plazos fijos anuales en pesos
    volatility = annual_volatility  
    
    today = ql.Date().todaysDate()
    day_count = ql.Actual365Fixed()  # Day count convention
        
    print(f"Actual stock price: {spot_price}")
    for expiration_date, items in sorted_grouped_data_PUTS.items():
        print(f"Expiration Date: {expiration_date.strftime('%d/%m/%Y')}")
        for item in items:
            strike_price = item['price']
            expiry = ql.Date(item['expiration_date'].day, item['expiration_date'].month, item['expiration_date'].year)
            
            precio_opcion = market.get_market_data(item["ticker"].strip().upper(), "OPCIONES", "A-24HS")
            # Calculate the time to maturity in years
            
            T = day_count.yearFraction(today, expiry)
            
            # no tiene volumen
            if(precio_opcion['price'] != 0):
                print(item["ticker"])    
            
                print(f"Precio actual de la opcion: {precio_opcion['price']}")
                
                
                option_price = Opciones_class.black_scholes_put(spot_price, strike_price, T, risk_free_rate, volatility)
                
                
                
                #print(f"Precio actual de la opcion: {precio_opcion['price']}")
                print(print(f"Precio calculado {option_price:.2f} "))
                print("")
            
        
    
    

    
   
    

# Function to extract the relevant information
def extract_and_separate(data, pattern):
    gfgc_data = []
    gfgv_data = []
    
    for item in data:
        match = re.search(pattern, item['description'])
        if match:
            price = match.group(1)
            expiration_date = match.group(2)
            
            extracted_info = {
                'ticker': item['ticker'],
                'price': price,
                'expiration_date': expiration_date
            }
            if item['ticker'].startswith('GFGC'):
                gfgc_data.append(extracted_info)
            elif item['ticker'].startswith('GFGV'):
                gfgv_data.append(extracted_info)
    
    return gfgc_data, gfgv_data

    
# Function to filter and group data by expiration date (only from today forward)
def filter_and_group_by_expiration(gfgc_data,today, current_price):
    grouped_data = defaultdict(list)

    for item in gfgc_data:
        expiration_date = item['expiration_date']
        # Convert expiration date to datetime object
        expiration_date_obj = datetime.strptime(expiration_date, "%d/%m/%Y")
        
        if (float(item['price']) >= current_price * 10):
            item['price'] = float(item['price']) / 10
        # Check if the expiration date is today or in the future
        if expiration_date_obj >= today:
            extracted_info = {
                'ticker': item['ticker'],
                'price': float(item['price']),  # Convert price to float for proper sorting
                'expiration_date': expiration_date_obj
            }
            grouped_data[expiration_date_obj].append(extracted_info)

    # Sort the grouped data by expiration date and then by price
    sorted_grouped_data = {k: sorted(v, key=lambda x: (k, x['price'])) for k, v in grouped_data.items()}

    return sorted_grouped_data


if __name__ == '__main__':
    os.system("cls")
    main()
