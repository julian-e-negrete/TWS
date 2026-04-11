from ppi_client.api.constants import ACCOUNTDATA_TYPE_ACCOUNT_NOTIFICATION, ACCOUNTDATA_TYPE_PUSH_NOTIFICATION, \
    ACCOUNTDATA_TYPE_ORDER_NOTIFICATION
from ppi_client.ppi import PPI

import pandas as pd
import numpy as np



from datetime import datetime
import json
import traceback
import os

from finance.PPI.classes.account_ppi import Account
from finance.PPI.classes.market_ppi import Market_data

from finance.PPI.classes.Instrument_class import Instrument




def main():
    ppi = PPI(sandbox=False)
    
    account = Account(ppi)  
            
   
    market = Market_data(account.ppi)
    
    date_format = "%Y-%m-%d"

    start_date = datetime.strptime('2024-06-01', date_format)
    end_date = datetime.now()
    
    # Diccionario con tickers como claves y valores con subdiccionario
    tickers = [
    "ALUA", "BBAR", "BMA", "BYMA", "CEPU", "COME", "CRES", "EDN", "GGAL", 
    "IRSA", "LOMA", "METR", "MIRG", "PAMP", "SUPV", "TECO2", "TGNO4", 
    "TGSU2", "TRAN", "TXAR", "VALO", "YPFD"
]

    for ticker in tickers:   
        lst_historical = market.get_historical_data(ticker,"Acciones", "A-24HS", start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
        df = pd.DataFrame(lst_historical)
        if len(df) == 0:
            continue
        instrument_cl = Instrument (df)
        
        sharpe_ratio = instrument_cl.Sharpe_ratio()

        if(sharpe_ratio >= 0.1):
            print(ticker)

            print(f"Sharpe Ratio: {sharpe_ratio:.2f}")
    
    
    """
    # Energy Sector Stocks
    energy_stocks = [
        "YPFD", "PAMP", "TGSU2", "CEPU", "EDN", 
        "TRAN", "METR", "CAPX", "CGPA2"
    ]

    # Financial Sector Stocks
    financial_stocks = [
        "BBAR", "BMA", "GGAL", "BHIP", "SUPV", 
        "BPAT", "VALO"
    ]

    # Utilities Sector Stocks
    utilities_stocks = [
        "EDN", "TGNO4", "GBAN"
    ]

    print("ENERGY: \n\n")
    for i in energy_stocks:   
        print(i)
        lst_historical = market.get_historical_data(i,"Acciones", "A-24HS", start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
        df = pd.DataFrame(lst_historical)
        instrument_cl = Instrument (df)
        
        sharpe_ratio = instrument_cl.Sharpe_ratio()
        print(f"Sharpe Ratio: {sharpe_ratio:.2f}")

        if(sharpe_ratio >= 1):
            print(f"Sharpe Ratio: {sharpe_ratio:.2f}")

    print("\n\nFINANCIAL: \n\n")
    for i in financial_stocks:   
        print(i)

        lst_historical = market.get_historical_data(i,"Acciones", "A-24HS", start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
        df = pd.DataFrame(lst_historical)
        instrument_cl = Instrument (df)
        
        sharpe_ratio = instrument_cl.Sharpe_ratio()
        print(f"Sharpe Ratio: {sharpe_ratio:.2f}")
        
        if(sharpe_ratio >= 1):
            print(f"Sharpe Ratio: {sharpe_ratio:.2f}")
    
    print("\n\nUtilites: \n\n")
    for i in utilities_stocks:   
        print(i)

        lst_historical = market.get_historical_data(i,"Acciones", "A-24HS", start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
        df = pd.DataFrame(lst_historical)
        instrument_cl = Instrument (df)
        
        sharpe_ratio = instrument_cl.Sharpe_ratio()
        print(f"Sharpe Ratio: {sharpe_ratio:.2f}")
        
        if(sharpe_ratio >= 1):
            print(f"Sharpe Ratio: {sharpe_ratio:.2f}")

    """


if __name__ == '__main__':
    os.system("cls")
    main()
