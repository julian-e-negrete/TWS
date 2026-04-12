from ppi_client.api.constants import ACCOUNTDATA_TYPE_ACCOUNT_NOTIFICATION, ACCOUNTDATA_TYPE_PUSH_NOTIFICATION, \
    ACCOUNTDATA_TYPE_ORDER_NOTIFICATION
from ppi_client.ppi import PPI

import pandas as pd
import numpy as np



from datetime import datetime
import json
import traceback
import os

from PPI.classes.account_ppi import Account
from PPI.classes.market_ppi import Market_data

from PPI.classes.Instrument_class import Instrument




def main():
    ppi = PPI(sandbox=False)
    
    account = Account(ppi)  
            
   
    market = Market_data(account.ppi)
    
    date_format = "%Y-%m-%d"

    start_date = datetime.strptime('2024-01-01', date_format)
    end_date = datetime.now()

    lst_historical = market.get_historical_data("","", "A-24HS", start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
    df = pd.DataFrame(lst_historical)
    instrument_cl = Instrument (df)
    
    sharpe_ratio = instrument_cl.Sharpe_ratio()
    print(f"Sharpe Ratio: {sharpe_ratio:.2f}")



if __name__ == '__main__':
    os.system("cls")
    main()
