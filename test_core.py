import sys
import os
import numpy as np
import pandas as pd

# Add the project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from core.math.options import black_scholes, implied_volatility
from core.math.greeks import greeks_scipy, greeks_quantlib
from core.math.dlr import get_dlr_multiplier, calculate_ccl

def test_options():
    print("Testing Options Calculations...")
    S, K, T, r, sigma = 100, 100, 1, 0.05, 0.2
    price = black_scholes(S, K, T, r, sigma, 'C')
    iv = implied_volatility(S, K, T, r, price, 'C')
    
    print(f"  BS Price: {price:.4f} (Expected: ~10.4506)")
    print(f"  IV: {iv:.4f} (Expected: 0.2000)")
    assert abs(price - 10.4506) < 0.01
    assert abs(iv - 0.2) < 0.01

def test_greeks():
    print("\nTesting Greeks (Scipy)...")
    S, K, T, r, sigma = 100, 100, 1, 0.05, 0.2
    d, g, v, t = greeks_scipy(S, K, T, r, sigma, 'C')
    print(f"  Delta: {d:.4f}")
    print(f"  Gamma: {g:.4f}")
    print(f"  Vega:  {v:.4f}")
    print(f"  Theta: {t:.4f}")
    
    # Simple check for Delta (ATM Call should be ~0.5 + risk premium)
    assert 0.5 < d < 0.7

    try:
        import QuantLib as ql
        print("\nTesting Greeks (QuantLib)...")
        npv, d_ql, g_ql, v_ql, t_ql, rho, iv = greeks_quantlib(S, K, T, r, sigma, 'C')
        print(f"  NPV:   {npv:.4f}")
        print(f"  Delta: {d_ql:.4f}")
        print(f"  Gamma: {g_ql:.4f}")
        print(f"  Vega:  {v_ql:.4f}")
        print(f"  Theta: {t_ql:.4f}")
        
        # Verify Scipy vs QuantLib
        assert abs(d - d_ql) < 0.01
        assert abs(g - g_ql) < 0.01
    except ImportError:
        print("\nQuantLib not installed, skipping QL tests.")

def test_dlr():
    print("\nTesting DLR/CCL Logic...")
    mult = get_dlr_multiplier('rx_DDF_DLR_OCT25')
    print(f"  Multiplier for DLR: {mult}")
    assert mult == 1000.0
    
    c_m, c_b, c_a = calculate_ccl(12000, 12100, 10, 10.1)
    print(f"  CCL Mid: {c_m:.2f}")
    assert abs(c_m - 1205/1.005) < 100 # Rough check

if __name__ == "__main__":
    try:
        test_options()
        test_greeks()
        test_dlr()
        print("\nALL CORE TESTS PASSED!")
    except Exception as e:
        print(f"\nTESTS FAILED: {e}")
        sys.exit(1)
