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


from .account_ppi import Account
from .market_ppi import Market_data

class Instrument:
    
    def __init__(self, df_p ) -> None:
        self.df = df_p
        self.structurate_df(self.df)
        self.risk_free_rate = 0.048 # usa sovereign bond interest rate
        
        
        
    def structurate_df(self, df_p):
        df_p['date'] = pd.to_datetime(df_p['date'])
        df_p.set_index('date', inplace=True)

        # Calcular los rendimientos diarios de los precios
        df_p['Daily Return'] = df_p['price'].pct_change()
        df_p['Daily Return'] = df_p['Daily Return'].fillna(0)
        
        self.df = df_p
        
    def Sharpe_ratio(self):
        risk_free_return = self.risk_free_rate / 252  # Tasa libre de riesgo diaria
        excess_return = self.df['Daily Return'].mean() - risk_free_return
        sharpe_ratio_daily = excess_return / self.df['Daily Return'].std()
        sharpe_ratio_annualized = sharpe_ratio_daily * (252 ** 0.5)  # Anualización
        
        return sharpe_ratio_annualized
    
    def working_days_diff(self, start, end, calendar):
        # Ensure start date is earlier than end date
        if start > end:
            start, end = end, start
        # Include end date by adding 1 day
        adjusted_end = end + 1
        return calendar.businessDaysBetween(start, adjusted_end)