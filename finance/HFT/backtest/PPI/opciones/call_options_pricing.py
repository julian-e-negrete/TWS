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

# Now import the required modules

from finance.PPI.classes import Account, Market_data, Instrument, Opciones

import QuantLib as ql


import re

def call_option_pricing(data_calls):
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
    recent_days = 30
    df = df.tail(recent_days)
    Opciones_class = Opciones(df, account, market)

    daily_volatility = Opciones_class.daily_volatility()
    annual_volatility = Opciones_class.annual_volatility()

    delta = len(Opciones_class.df['Daily Return'].dropna())

    print(f"Desviación estándar diaria: {(daily_volatility * 100):.2f}%")
    print(f"Volatilidad en {delta} dias: {(annual_volatility * 100):.2f}%")



    precio_accion = market.get_market_data(ticker, "ACCIONES", "A-24HS")


    # Define option parameters
    spot_price = precio_accion["price"]  # Current price of the stock



    # Define option parameters
    risk_free_rate = 0.35
    #risk_free_rate = market.get_market_data("PESOS31", "CAUCIONES", "A-24HS")
    #risk_free_rate = risk_free_rate["price"] / 100 # tasa plazos fijos en pesos/tasa de caucion
    print(f"risk free rate: {risk_free_rate * 100}%")

    volatility = annual_volatility

    today = ql.Date().todaysDate()
    day_count = ql.Actual365Fixed()  # Day count convention

    print(f"Actual stock price: {spot_price}")
    
   
    for index, row in data_calls.iterrows():
        
        
        strike_price = row['strikePrice']
        
        expiry = today + ql.Period(int(row['daysToMaturity']), ql.Days)

        precio_opcion = market.get_market_data(row['symbol'].strip().upper(), "OPCIONES", "A-24HS")
        # Calculate the time to maturity in years
        
        
        T = day_count.yearFraction(today, expiry)

        # no tiene volumen
        # if(precio_opcion['price'] != 0):
        #print(row['symbol'])

        
        print(f"\nProcessing option: {row['symbol']}")
        print(f"spot price: {spot_price}")
        print(f"Days to Maturity: {expiry}")
        print(f"Strike Price: {strike_price}")
        print(f"volatility: {volatility}")
        print(f"Precio actual de la opcion: {precio_opcion['price']}")
        option_price = Opciones_class.quantlib_option_price(spot_price, strike_price, expiry, risk_free_rate, volatility)
        option_price = Opciones_class.black_scholes_model(spot_price, strike_price, T, risk_free_rate, volatility)

        print(option_price)

                #print(f"Precio actual de la opcion: {precio_opcion['price']}")
                # print(print(f"Precio calculado {option_price:.2f} "))
                # print("")









