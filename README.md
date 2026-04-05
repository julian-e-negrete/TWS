# TWS — Trader Workstation

A high-performance terminal for Argentine and crypto markets, inspired by Interactive Brokers TWS. Built in Rust (Ratatui TUI) with a Python data pipeline backend.

## Architecture

```
tws_terminal/     — Rust TUI (Ratatui) — main application
math/             — Python: Black-Scholes, Greeks, Binomial, CCL/DLR
data/             — Python: DB loaders, ByMA client, Binance loader
scrapers/         — Python: Matriz WebSocket, ByMA REST, MAE REST, Binance
mcp_server/       — Python: MCP tools for PostgreSQL + MySQL access
config/           — Python: pydantic-settings config
shared/           — Python: DB pool, models, cookie management
job/              — Python: cron jobs (tick capture, order polling)
monitor/          — Python: alerting, data stream monitoring
```

**Databases (on 100.112.16.115):**
- PostgreSQL `marketdata` — HFT ticks, orders, backtest results (TimescaleDB)
- MySQL `investments` — historical OHLCV

## TUI Tabs

| Key | Tab | Description |
|-----|-----|-------------|
| `1` | Binance | Live kline data via Redis WebSocket. Real-time + historical. |
| `2` | MERVAL | Argentine market data (BYMA/Matriz). Real-time + historical. |
| `3` | Options | GGAL/SUPV/PBRD option chains with IV and Greeks. BS calculator. |
| `4` | Futures | DLR futures term structure (last 3 contracts). |
| `5` | News | ByMA relevant facts + Reuters via NewsAPI. |

## Quick Start

```bash
# 1. Copy and fill credentials
cp .env.example .env

# 2. Run the TUI
cd tws_terminal
cargo run --release

# 3. Run Python scrapers (data ingestion)
PYTHONPATH=. python3 scrapers/matriz/run.py
PYTHONPATH=. python3 scrapers/byma/run.py
```

## TUI Key Bindings

| Key | Action |
|-----|--------|
| `1-5` | Switch tab |
| `Tab` / `→` | Next tab |
| `s` | Toggle Real-Time / Historical (Binance, MERVAL) |
| `f` | Open filter (date + instrument dropdown) |
| `r` | Refresh data (Options, Futures, News) |
| `c` | Toggle BS calculator (Options tab) |
| `↑↓` | Scroll / navigate |
| `←→` | Switch contract (Futures) / navigate favorites |
| `p` | Switch panel focus (top/bottom) |
| `a` / `d` | Add / delete favorite instrument |
| `q` | Quit |

## Environment Variables

See `.env.example`. Key variables:

```
POSTGRES_HOST / POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB
NEWSAPI_KEY       — NewsAPI.org key for Reuters headlines
REDIS_HOST        — Redis host for live WebSocket data
```

## Data Sources

| Source | Protocol | Data |
|--------|----------|------|
| Matriz.eco | WebSocket | HFT futures ticks (bid/ask/last) |
| BYMA REST | HTTP | CEDEARs, equities, options chain |
| MAE REST | HTTP | Dólar MEP, FX futures |
| Binance | WebSocket | Crypto klines + aggTrades |
| ByMA MarketData | REST | Relevant facts / news |
| NewsAPI (Reuters) | REST | International financial news |

## Python Modules

```bash
# Option pricing
from math.options import black_scholes, implied_volatility
from math.greeks import greeks_scipy, greeks_quantlib
from math.binomial import binomial_american, binomial_greeks
from math.dlr import calculate_ccl, estimate_dlr_fair_value

# Data
from data.loader import load_tick_data, load_order_data
from data.binance_loader import load_binance_data
from data.byma_client import ByMAClient
```

See `USAGE_GUIDE.md` for detailed examples and `SPEC.md` for the full technical specification.
