import numpy as np
from .options import black_scholes

# Optional QuantLib import
try:
    import QuantLib as ql
except ImportError:
    ql = None

def greeks_scipy(S, K, T, r, sigma, opt_type='C'):
    """
    Calculate Greeks using finite differences and Scipy BS.
    Returns (delta, gamma, vega, theta).
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return np.nan, np.nan, np.nan, np.nan
        
    h = 0.001
    p0 = black_scholes(S, K, T, r, sigma, opt_type)
    
    # Delta & Gamma (Spot shift)
    p_u = black_scholes(S * (1 + h), K, T, r, sigma, opt_type)
    p_d = black_scholes(S * (1 - h), K, T, r, sigma, opt_type)
    delta = (p_u - p_d) / (2 * S * h)
    gamma = (p_u - 2 * p0 + p_d) / (S * h)**2
    
    # Vega (Vol shift)
    p_v = black_scholes(S, K, T, r, sigma + h, opt_type)
    vega = (p_v - p0) / h
    
    # Theta (Time shift - 1 day)
    # T is in years, 1 day = 1/365
    T_next = max(0, T - 1/365.0)
    p_t = black_scholes(S, K, T_next, r, sigma, opt_type)
    theta = (p_t - p0) * 365.0  # Annualized theta
    
    return delta, gamma, vega, theta

def greeks_quantlib(S, K, T, r, sigma, opt_type='C', expiry_date=None):
    """
    Calculate Greeks using QuantLib.
    If expiry_date (ql.Date) is not provided, it assumes T years from today.
    Returns (npv, delta, gamma, vega, theta, rho, iv).
    """
    if ql is None:
        raise ImportError("QuantLib is not installed.")
        
    ql_type = ql.Option.Call if opt_type == 'C' else ql.Option.Put
    payoff = ql.PlainVanillaPayoff(ql_type, K)
    
    # Set evaluation date if not set
    today = ql.Settings.instance().evaluationDate
    if expiry_date is None:
        # Approximate expiry from T
        days = int(T * 365)
        expiry_date = today + days
        
    exercise = ql.EuropeanExercise(expiry_date)
    european_option = ql.VanillaOption(payoff, exercise)
    
    # Setup market data handles
    spot_handle = ql.QuoteHandle(ql.SimpleQuote(S))
    rate_handle = ql.YieldTermStructureHandle(
        ql.FlatForward(0, ql.NullCalendar(), ql.QuoteHandle(ql.SimpleQuote(r)), ql.Actual360())
    )
    vol_handle = ql.BlackVolTermStructureHandle(
        ql.BlackConstantVol(0, ql.NullCalendar(), ql.QuoteHandle(ql.SimpleQuote(sigma)), ql.Actual360())
    )
    process = ql.BlackScholesProcess(spot_handle, rate_handle, vol_handle)
    
    engine = ql.AnalyticEuropeanEngine(process)
    european_option.setPricingEngine(engine)
    
    try:
        npv = european_option.NPV()
        delta = european_option.delta()
        gamma = european_option.gamma()
        vega = european_option.vega()
        theta = european_option.theta()
        rho = european_option.rho()
        iv = european_option.impliedVolatility(npv, process)
        return npv, delta, gamma, vega, theta, rho, iv
    except Exception:
        return (np.nan,) * 7
