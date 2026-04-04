# TWS Core: Usage Guide

This guide explains how to use the core data loading and financial calculation modules migrated from the AlgoTrading project.

## 1. Installation

Ensure you have all dependencies installed from the provided `requirements.txt`:

```bash
pip install -r requirements.txt
```

> [!NOTE]
> For the QuantLib-based Greeks, ensure `QuantLib` is installed. The `scipy` version works out-of-the-box for a lighter setup.

## 2. Configuration

Set up your `.env` file with the following database credentials (the project uses `python-dotenv` to load these automatically):

```env
# PostgreSQL (HFT Data)
HFT_DB_HOST=100.112.16.115
HFT_DB_PORT=5432
HFT_DB_USER=postgres
HFT_DB_PASSWORD=your_password
HFT_DB_NAME=marketdata

# Redis (Caching)
REDIS_HOST=localhost
REDIS_PORT=6379
```

## 3. Data Loading

### Loading Ticks & Orders (Merval, DLR, Options)

```python
from core.data.loader import load_tick_data, load_order_data

# Load all ticks for a specific date
df_ticks = load_tick_data('2026-04-03')

# Load specifically for a given instrument (e.g., DLR)
df_dlr = load_tick_data('2026-04-03', instrument_filter='M:rx_DDF_DLR_%')

# Load order data
df_orders = load_order_data('2026-04-03')
```

### Loading Binance Data

```python
from core.data.binance_loader import load_binance_data

# Returns synthetic trades and ticks derived from 1-min OHLCV
trades_df, ticks_df = load_binance_data('2026-04-03', 'BTCUSDT')
```

## 4. Financial Calculations

### Option Metrics (Black-Scholes & Greeks)

You can choose between a standard Scipy implementation or a more robust QuantLib one.

```python
from core.math.options import black_scholes, implied_volatility
from core.math.greeks import greeks_scipy, greeks_quantlib

S, K, T, r, sigma = 100, 100, 0.5, 0.05, 0.2

# 1. Scipy (Finite Differences)
delta, gamma, vega, theta = greeks_scipy(S, K, T, r, sigma, opt_type='C')

# 2. QuantLib (Analytic)
npv, d, g, v, t, rho, iv = greeks_quantlib(S, K, T, r, sigma, opt_type='C')
```

### DLR & CCL

```python
from core.math.dlr import get_dlr_multiplier, calculate_ccl

# Get the correct multiplier for DLR futures
mult = get_dlr_multiplier('rx_DDF_DLR_OCT25') # Returns 1000.0

# Calculate CCL implicit rate from bond pair (ARS vs USD)
ccl_mid, ccl_bid, ccl_ask = calculate_ccl(al30_bid, al30_ask, al30d_bid, al30d_ask)
```

## 5. Verification

You can always run the included verification script to ensure everything is working correctly:

```bash
python test_core.py
```
