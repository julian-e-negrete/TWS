from ppi_client.api.constants import ACCOUNTDATA_TYPE_ACCOUNT_NOTIFICATION, ACCOUNTDATA_TYPE_PUSH_NOTIFICATION, \
    ACCOUNTDATA_TYPE_ORDER_NOTIFICATION
from ppi_client.ppi import PPI

import pandas as pd
import numpy as np



from datetime import datetime
import sys
import os

# Dynamically add the parent directory (PPI) to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, '..'))
sys.path.append(parent_dir)

# Now import the required modules

from finance.PPI.classes import Account, Market_data, Instrument, Opciones

import QuantLib as ql


def main():
    ppi = PPI(sandbox=False)
    
    account = Account(ppi)
            
   
    market = Market_data(account.ppi)
    
      
     
    date_format = "%Y-%m-%d"

    start_date = datetime.strptime('2024-01-01', date_format)
    end_date = datetime.now()
    
    ticker = input("Ingrese el Ticker: ")
    

    lst_historical = market.get_historical_data(ticker.upper().strip(),"ACCIONES", "A-24HS", start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
    df = pd.DataFrame(lst_historical)
    
    Opciones_class = Opciones(df, account, market)

    daily_volatility = Opciones_class.daily_volatility()
    annual_volatility = Opciones_class.annual_volatility()
    
    delta = len(Opciones_class.df['Daily Return'].dropna())        

    print(f"Desviación estándar diaria: {(daily_volatility * 100):.2f}%")
    print(f"Volatilidad en {delta} dias: {(annual_volatility * 100):.2f}%")
    
    
    precio_accion = market.get_market_data(ticker.upper().strip(), "ACCIONES", "A-24HS")
    
    
    # Define option parameters
    spot_price = precio_accion["price"]  # Current price of the stock
    strike_price = 9778.3
    
    
    expiry = ql.Date(21, 4, 2025)  # Expiry date
    risk_free_rate = 0.048  # 4.8% risk-free rate(1 year bond interes rate usa sovereign bonds)
    
    option_price , message = Opciones_class.quantlib_option_price(spot_price, strike_price, expiry, risk_free_rate, annual_volatility)
    
    
    print(message)
    
    
    

    

if __name__ == '__main__':
    os.system("cls")
    main()
