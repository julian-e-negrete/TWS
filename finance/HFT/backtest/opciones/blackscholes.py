

import pandas as pd


from datetime import datetime


# Dynamically add the parent directory (PPI) to sys.path

# Now import the required modules

from finance.PPI.classes import  Market_data, Instrument, Opciones


import QuantLib as ql




def black_scholes_model(underliying,symbol, strike_price, expiry, spot_price, Opciones_class, annual_volatility, risk_free_rate, backtest = True ):
     
   
    
    # print(f"Desviación estándar diaria: {(daily_volatility * 100):.2f}%")
    # print(f"Volatilidad en {delta} dias: {(annual_volatility * 100):.2f}%")


    
    #risk_free_rate = market.get_market_data("PESOS31", "CAUCIONES", "A-24HS")
    #risk_free_rate = risk_free_rate["price"] / 100 # tasa plazos fijos en pesos/tasa de caucion
    #print(f"risk free rate: {risk_free_rate * 100}%")
    
    
    volatility = annual_volatility

    today = ql.Date().todaysDate()
    day_count = ql.Actual365Fixed()  # Day count convention
    
    option_price, delta, gamma, vega, theta, rho, iv = Opciones_class.quantlib_option_price(spot_price, strike_price, expiry, risk_free_rate, volatility)

    # actual_option_price = market.get_market_data(symbol, "OPCIONES", "A-24HS")

    # return option_price, actual_option_price["price"],delta, gamma, vega, theta, rho, iv

    #actual_option_price = market.get_market_data(symbol, "OPCIONES", "A-24HS")
    if backtest:
        
        return option_price, 0,delta, gamma, vega, theta, rho, iv
    
    else:
        return option_price, 0,delta, gamma, vega, theta, rho, iv
    