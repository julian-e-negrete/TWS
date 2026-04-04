import numpy as np
import pandas as pd

def get_dlr_multiplier(instrument_name: str) -> float:
    """
    Returns the contract multiplier for DLR instruments.
    Standard for rx_DDF_DLR is 1000.
    """
    if 'rx_DDF_DLR' in instrument_name:
        return 1000.0
    return 100.0

def calculate_ccl(al30_bid, al30_ask, al30d_bid, al30d_ask):
    """
    Calculates the implicit CCL (Contado con Liquidación) rate.
    CCL = AL30_ARS / AL30D_USD.
    Returns (ccl_mid, ccl_bid, ccl_ask).
    """
    al30_mid = (al30_bid + al30_ask) / 2.0
    al30d_mid = (al30d_bid + al30d_ask) / 2.0
    
    ccl_mid = al30_mid / al30d_mid
    
    # Worst case: buy AL30 at ask, sell AL30D at bid
    ccl_bid = al30_bid / al30d_ask
    ccl_ask = al30_ask / al30d_bid
    
    return ccl_mid, ccl_bid, ccl_ask

def estimate_dlr_fair_value(spot_usd_ars, days_to_expiry, t_rate_ars, t_rate_usd=0.0):
    """
    Simple forward fair value for DLR futures.
    F = S * e^((r_ars - r_usd) * T)
    """
    T = days_to_expiry / 365.0
    return spot_usd_ars * np.exp((t_rate_ars - t_rate_usd) * T)
