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



import os

try:
    import QuantLib as ql
except ImportError:
    ql = None



from .account_ppi import Account
from .market_ppi import Market_data
from .Instrument_class import Instrument




class Opciones:
    
    def __init__(self, df_p, account_p, market_p ) -> None:
    
        self.account = account_p       
        self.market = market_p
        self.df = df_p
        self.instrument_cl = Instrument(self.df)

        self.df = self.instrument_cl.df
        
 
  
    def daily_volatility(self):
        returns = self.df['Daily Return'].dropna()
        return returns.std()

    def annual_volatility(self):
        daily_vol = self.daily_volatility()
        return daily_vol * (252 ** 0.5)



    def garch_model(self, delta_p):
        # Validate inputs
        if not isinstance(delta_p, (int, float)) or delta_p <= 0:
            raise ValueError("delta_p must be a positive number representing the number of days.")

        if 'Daily Return' not in self.df.columns:
            raise KeyError("The DataFrame must contain a 'Daily Return' column.")

        df_p = self.df.copy()  # Work on a copy to avoid modifying the original DataFrame

        # Scale the returns to avoid optimizer warnings
        df_p['Scaled Return'] = df_p['Daily Return'] * 10  # Scaling by 10 as recommended

        # GARCH(1, 1) Model
        model = arch_model(df_p['Scaled Return'], vol='Garch', p=1, q=1, dist='normal', rescale=False)
        garch_fit = model.fit(disp="off")

        # Obtain the conditional daily and annualized volatility
        scaled_daily_volatility = garch_fit.conditional_volatility
        daily_garch_volatility = scaled_daily_volatility / 10  # Reverse scaling
        annual_garch_volatility = daily_garch_volatility.iloc[-1] * np.sqrt(delta_p)

        # Return volatility and formatted message
        return annual_garch_volatility, f"Conditional volatility (GARCH, over {delta_p} days): {annual_garch_volatility * 100:.2f}%"

    
    
    
    
    
    def black_scholes_model(self, S, K, T, r, sigma):
        # print(f"{S}, {K}, {T}, {r}, {sigma}")
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

    def black_scholes_put(self, S, K, T, r, sigma):
        # Calculate d1 and d2
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        
        # Calculate put option price
        put_price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
        return put_price
    

    def implied_volatility_call(self, S, K, T, r, market_price):
        """ Calcula la volatilidad implícita usando Black-Scholes y el precio de mercado """
        def difference(sigma):
            return self.black_scholes_model(S, K, T, r, sigma) - market_price
        
        # Buscar sigma que minimice la diferencia
        try:
            iv = brentq(difference, 1e-5, 5)  # Buscamos entre valores razonables de sigma
            return iv
        except ValueError:
            return np.nan
        
        
    def quantlib_option_price(self, spot_price, strike_price, expiry, risk_free_rate, volatility):
        # Define option type
        payoff = ql.PlainVanillaPayoff(ql.Option.Call, strike_price)
        exercise = ql.EuropeanExercise(expiry)

        # Create option
        european_option = ql.VanillaOption(payoff, exercise)

        # Set up pricing engine
        spot_handle = ql.QuoteHandle(ql.SimpleQuote(spot_price))
        rate_handle = ql.YieldTermStructureHandle(ql.FlatForward(0, ql.NullCalendar(), ql.QuoteHandle(ql.SimpleQuote(risk_free_rate)), ql.Actual360()))
        vol_handle = ql.BlackVolTermStructureHandle(ql.BlackConstantVol(0, ql.NullCalendar(), ql.QuoteHandle(ql.SimpleQuote(volatility)), ql.Actual360()))
        process = ql.BlackScholesProcess(spot_handle, rate_handle, vol_handle)

        engine = ql.AnalyticEuropeanEngine(process)
        european_option.setPricingEngine(engine)
        
        delta = european_option.delta()
        gamma = european_option.gamma()
        vega = european_option.vega()
        theta = european_option.theta() 
        rho = european_option.rho()
        
        iv = european_option.impliedVolatility(european_option.NPV(), process)
        
        return european_option.NPV(), delta, gamma, vega, theta, rho, iv