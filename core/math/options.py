import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq

def black_scholes(S, K, T, r, sigma, opt_type='C'):
    """
    Standard Black-Scholes pricing.
    S: Spot price
    K: Strike price
    T: Time to expiry (years)
    r: Risk-free rate
    sigma: Volatility
    opt_type: 'C' for Call, 'P' for Put
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    
    if opt_type == 'C':
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:
        return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

def implied_volatility(S, K, T, r, market_price, opt_type='C'):
    """
    Finds IV using Brent's method.
    """
    if market_price <= 0 or T <= 0:
        return np.nan
        
    def difference(sigma):
        return black_scholes(S, K, T, r, sigma, opt_type) - market_price
    
    try:
        # Search between 0.001% and 500% vol
        return brentq(difference, 1e-5, 5.0)
    except (ValueError, RuntimeError):
        return np.nan
