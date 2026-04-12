from ppi_client.api.constants import ACCOUNTDATA_TYPE_ACCOUNT_NOTIFICATION, ACCOUNTDATA_TYPE_PUSH_NOTIFICATION, \
    ACCOUNTDATA_TYPE_ORDER_NOTIFICATION
from ppi_client.ppi import PPI

import pandas as pd
import numpy as np

# GARCH MODEL
from arch import arch_model

# BLACK SCHOLES MODEL
from scipy.stats import norm
#Implied volatility
from scipy.optimize import brentq


from datetime import datetime
import json
import traceback
import sys
import os


current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, '..'))
sys.path.append(parent_dir)


from PPI.classes import Account, Market_data, Instrument
import QuantLib as ql





def main():
    # Change sandbox variable to False to connect to production environment
    ppi = PPI(sandbox=False)
    
    account = Account(ppi)
            
    # Get available balance
    #account.get_available_balance()
    
    #account.get_active_orders()
    

    
    
    
    market = Market_data(account.ppi)
    #con esto puedo obtener todos los instrumentos que esten relacionados a esos parametros
    #lst_opciones = market.get_instrument("MET","BYMA", "ACCIONES")
    """
    
    
    df = pd.DataFrame(lst_opciones)
    
    headers = df.columns
    
    for i in df["ticker"]:
        market.get_market_data(i, "OPCIONES", "A-72")
        #market.search_current_book(i,"OPCIONES","A-24HS")
        #market.get_historical_data(i,"OPCIONES", "A-24HS", "2024-12-01", "2024-12-31")
    """    
    
    from datetime import datetime
    date_format = "%Y-%m-%d"

    start_date = datetime.strptime('2024-01-01', date_format)
    end_date = datetime.now()

    
    
    #print(df.describe())
    lst_historical = market.get_historical_data("GGAL","ACCIONES", "A-24HS", start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
    df = pd.DataFrame(lst_historical)
    #print(df.columns)
    instrument_cl = Instrument (df)

    
    
    delta = len(instrument_cl.df['Daily Return'].dropna())  # Number of valid trading days in the period

    # Calcular la desviación estándar de los rendimientos diarios
    daily_volatility = instrument_cl.df['Daily Return'].std()

    # Calcular la volatilidad anualizada
    annual_volatility = daily_volatility * np.sqrt(delta)  # 252 días de negociación en un año
    
    
    sigma  = garch_model(instrument_cl.df, delta)
    
    print(f"Desviación estándar diaria: {(daily_volatility * 100):.2f}%")
    print(f"Volatilidad en {delta} dias: {(annual_volatility * 100):.2f}%")
    
    
    precio_accion = market.get_market_data("GGAL", "ACCIONES", "A-24HS")
    
    precio_opcion27 = market.get_market_data("GFGC75783A", "OPCIONES", "A-24HS")
    
    precio_opcion29 = market.get_market_data("GFGC77783A", "OPCIONES", "A-24HS")
    
    precio_opcion31 = market.get_market_data("GFGC82783A", "OPCIONES", "A-24HS")

    # precio_opcion33 = market.get_market_data("METC3300FE", "OPCIONES", "A-24HS")

    # precio_opcion35 = market.get_market_data("METC3500FE", "OPCIONES", "A-24HS")

    
    S = precio_accion["price"]  # Precio actual de la acción (en pesos)
    K = 75783  # Precio de ejercicio (en pesos)    

    calendar = ql.UnitedStates(ql.UnitedStates.NYSE)  # NYSE calendar for US holidays

    today = datetime.today()
    start_date = ql.Date(today.day, today.month, today.year)  # Convert to QuantLib Date
    end_date = ql.Date(21, 2, 2025)  # Expiry date  

    days_to_expiry = instrument_cl.working_days_diff(start_date, end_date, calendar)

    #days_to_expiry = 44  # Días hasta el vencimiento
    r = 0.048  # Tasa libre de riesgo (4.8% anual, en proporción) sovereing bonds interest rate in a year
    T = days_to_expiry / 365  # Tiempo hasta el vencimiento en años 
    market_price = precio_opcion27["price"]  # Prima observada en el mercado
    
    box_width = 70

    print("-" * (box_width+ 2))
    """ METC2700FE """
    print(f"Precio actual de la opcion CALL(METC2700FE): {market_price}")
    call_price = black_scholes_model(S, K, T, r, annual_volatility)

    print(f"Precio de la opción Call(METC2700FE) calculado: {call_price:.2f} pesos")
    
    iv = implied_volatility_call(S, K, T, r, market_price)
    print(f"Volatilidad implícita: {iv * 100:.2f}%")
    print("-" * (box_width + 2))
    
    
    """ METC2900FE """
    market_price = precio_opcion29["price"]  # Prima observada en el mercado
    K = 2900 
    
    print(f"Precio actual de la opcion CALL(METC2900FE): {market_price}")
    call_price = black_scholes_model(S, K, T, r, annual_volatility)

    print(f"Precio de la opción Call(METC2900FE) calculado: {call_price:.2f} pesos")
    
    iv = implied_volatility_call(S, K, T, r, market_price)
    print(f"Volatilidad implícita: {iv * 100:.2f}%")
    print("-" * (box_width + 2))
 
 
    """ METC3100FE """
    market_price = precio_opcion31["price"]  # Prima observada en el mercado
    K = 3100
    print(f"Precio actual de la opcion CALL(METC3100FE): {market_price}")
    call_price = black_scholes_model(S, K, T, r, annual_volatility)

    print(f"Precio de la opción Call(METC3100FE) calculado: {call_price:.2f} pesos")
    
    # Calcular la volatilidad implícita
    iv = implied_volatility_call(S, K, T, r, market_price)
    print(f"Volatilidad implícita: {iv * 100:.2f}%")
    
    print("-" * (box_width + 2))

    # market_price = precio_opcion33["price"]  # Prima observada en el mercado
    # K = 3300
    # print(f"Precio actual de la opcion CALL(METC3300FE): {market_price}")
    # call_price = black_scholes_model(S, K, T, r, annual_volatility)

    # print(f"Precio de la opción Call(METC3300FE) calculado: {call_price:.2f} pesos")

    # # Calcular la volatilidad implícita
    # iv = implied_volatility_call(S, K, T, r, market_price)
    # print(f"Volatilidad implícita: {iv * 100:.2f}%")

    # print("-" * (box_width + 2))


    # market_price = precio_opcion35["price"]  # Prima observada en el mercado
    # K = 3500
    # print(f"Precio actual de la opcion CALL(METC3500FE): {market_price}")
    # call_price = black_scholes_model(S, K, T, r, annual_volatility)

    # print(f"Precio de la opción Call(METC3500FE) calculado: {call_price:.2f} pesos")
    
    # Calcular la volatilidad implícita
    iv = implied_volatility_call(S, K, T, r, market_price)
    print(f"Volatilidad implícita: {iv * 100:.2f}%")
    
    print("-" * (box_width + 2))

    try:
        print("------")

    except Exception as e:
        print(datetime.now())
        print(f"ERROR: '{e}' ")




"""
calculo del modelo garch para la volatilidad
    
"""
def garch_model(df_p, delta_p):
    df_p['Scaled Return'] = df_p['Daily Return'] * 10
    
    # Modelo GARCH(1, 1)
    model = arch_model(df_p['Scaled Return'], vol='Garch', p=1, q=1, dist='normal')
    garch_fit = model.fit(disp="off")

    # Obtener la volatilidad condicional anualizada
    daily_garch_volatility = garch_fit.conditional_volatility / 10
    annual_garch_volatility = daily_garch_volatility.iloc[-1] * np.sqrt(delta_p ** 0.5)

    print(f"Volatilidad condicional (GARCH, en {delta_p} dias): {(annual_garch_volatility * 100):.2f}%")
    return annual_garch_volatility

    
    
        

def black_scholes_model(S, K, T, r, sigma):
    """
    Calcula el precio de una opción Call usando el modelo Black-Scholes.
    S: Precio del subyacente
    K: Precio de ejercicio
    T: Tiempo hasta el vencimiento en años
    r: Tasa libre de riesgo
    sigma: Volatilidad anualizada
    """
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    
    call_price = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    return call_price

def implied_volatility_call(S, K, T, r, market_price):
    """ Calcula la volatilidad implícita usando Black-Scholes y el precio de mercado """
    def difference(sigma):
        return black_scholes_model(S, K, T, r, sigma) - market_price
    
    # Buscar sigma que minimice la diferencia
    try:
        iv = brentq(difference, 1e-5, 5)  # Buscamos entre valores razonables de sigma
        return iv
    except ValueError:
        return np.nan
    



if __name__ == '__main__':
    os.system("cls")
    main()
