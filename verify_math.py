import numpy as np
from core.math.greeks import greeks_scipy
from core.math.binomial import binomial_american, binomial_greeks

def test_math_engine():
    S, K, T, r, sigma = 100, 100, 0.5, 0.05, 0.2
    
    print("Testing European Greeks (Scipy):")
    delta, gamma, vega, theta, rho = greeks_scipy(S, K, T, r, sigma, 'C')
    print(f"Delta: {delta:.4f}, Gamma: {gamma:.4f}, Vega: {vega:.4f}, Theta: {theta:.4f}, Rho: {rho:.4f}")
    
    print("\nTesting American Option (Binomial):")
    price = binomial_american(S, K, T, r, sigma, N=200, opt_type='C')
    print(f"Price: {price:.4f}")
    
    print("\nTesting American Greeks (Binomial):")
    delta_a, gamma_a, vega_a, theta_a, rho_a = binomial_greeks(S, K, T, r, sigma, N=200, opt_type='C')
    print(f"Delta: {delta_a:.4f}, Gamma: {gamma_a:.4f}, Vega: {vega_a:.4f}, Theta: {theta_a:.4f}, Rho: {rho_a:.4f}")

if __name__ == "__main__":
    test_math_engine()
