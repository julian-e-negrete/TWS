import numpy as np

def binomial_american(S, K, T, r, sigma, N=100, opt_type='C'):
    """
    Price American options using the Cox-Ross-Rubinstein (CRR) Binomial Tree.
    S: Spot price
    K: Strike price
    T: Time to expiry (years)
    r: Risk-free rate
    sigma: Volatility
    N: Number of steps in the tree
    opt_type: 'C' for Call, 'P' for Put
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    
    dt = T / N
    u = np.exp(sigma * np.sqrt(dt))
    d = 1 / u
    p = (np.exp(r * dt) - d) / (u - d)
    df = np.exp(-r * dt)
    
    # Initialize asset prices at maturity
    fs = np.zeros(N + 1)
    for j in range(N + 1):
        spot_at_t = S * (u ** j) * (d ** (N - j))
        if opt_type == 'C':
            fs[j] = max(spot_at_t - K, 0)
        else:
            fs[j] = max(K - spot_at_t, 0)
            
    # Iterate backwards through the tree
    for i in range(N - 1, -1, -1):
        for j in range(i + 1):
            # Continuation value
            fs[j] = df * (p * fs[j + 1] + (1 - p) * fs[j])
            
            # Early exercise check
            spot_at_t = S * (u ** j) * (d ** (i - j))
            if opt_type == 'C':
                exercise_value = max(spot_at_t - K, 0)
            else:
                exercise_value = max(K - spot_at_t, 0)
                
            fs[j] = max(fs[j], exercise_value)
            
    return fs[0]

def binomial_greeks(S, K, T, r, sigma, N=100, opt_type='C'):
    """
    Calculate Greeks for American options using finite differences on the Binomial tree.
    Returns (delta, gamma, vega, theta, rho).
    """
    h = 0.01 * S if S > 0 else 0.01
    dv = 0.01
    dt_shift = 1/365.0
    dr = 0.01
    
    p0 = binomial_american(S, K, T, r, sigma, N, opt_type)
    
    # Delta & Gamma
    p_u = binomial_american(S + h, K, T, r, sigma, N, opt_type)
    p_d = binomial_american(S - h, K, T, r, sigma, N, opt_type)
    delta = (p_u - p_d) / (2 * h)
    gamma = (p_u - 2 * p0 + p_d) / h**2
    
    # Vega
    p_v = binomial_american(S, K, T, r, sigma + dv, N, opt_type)
    vega = (p_v - p0) / dv
    
    # Theta
    T_next = max(0, T - dt_shift)
    p_t = binomial_american(S, K, T_next, r, sigma, N, opt_type)
    theta = (p_t - p0) * 365.0
    
    # Rho
    p_r = binomial_american(S, K, T, r + dr, sigma, N, opt_type)
    rho = (p_r - p0) / dr
    
    return delta, gamma, vega, theta, rho
