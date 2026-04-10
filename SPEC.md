# SPEC.md — TWS Trader Workstation Technical Specification

> Permanent anchor document. All agents and contributors must treat this as the source of truth.
> Last updated: 2026-04-10

---

## 1. Project Goal

A high-performance terminal for Argentine and crypto markets, inspired by Interactive Brokers TWS. Focused on research and data visualization, not order execution. Modular architecture with a Rust TUI frontend and Python data pipeline backend.

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────┐
│                  tws_terminal (Rust)                │
│  Ratatui TUI — 7 tabs: Binance, MERVAL, Options,   │
│  Futures, News, Markets, US Futures                 │
│  ├── src/ui/app.rs      — app state + render        │
│  ├── src/db/mod.rs      — PostgreSQL queries        │
│  ├── src/network/       — Redis WebSocket           │
│  └── src/data/          — data structs              │
└────────────────┬────────────────────────────────────┘
                 │ tokio-postgres / reqwest
┌────────────────▼────────────────────────────────────┐
│         PostgreSQL marketdata (TimescaleDB)         │
│         Host: 100.112.16.115:5432                   │
│  Tables: ticks, orders, binance_ticks,              │
│          binance_trades, backtest_runs              │
└────────────────┬────────────────────────────────────┘
                 │ scrapers (Python)
┌────────────────▼────────────────────────────────────┐
│  Scraper Server (192.168.1.244 / 100.112.16.115)   │
│  ├── wsclient.service       — Matriz WebSocket      │
│  ├── binance_monitor.service — Binance klines       │
│  └── crontab order_side.py  — Matriz REST orders    │
└─────────────────────────────────────────────────────┘
```

---

## 3. TUI Specification

### 3.1 Tabs

| # | Tab | Key | Data Source |
|---|-----|-----|-------------|
| 1 | Binance | `1` | Redis `binance:ticks` / `binance:trades` (live) + `binance_ticks` / `binance_trades` (historical) |
| 2 | MERVAL | `2` | Redis `matriz:ticks` / `matriz:orders` (live, per-instrument) + `ticks` / `orders` (historical) |
| 3 | Options | `3` | `ticks` WHERE instrument LIKE `%GFGC%` OR `%GFGV%` + Black-Scholes IV + Greeks |
| 4 | Futures | `4` | `ticks` WHERE instrument LIKE `%DDF_DLR%` (last 3 contracts, dynamic) |
| 5 | News | `5` | ByMA REST API + NewsAPI + Yahoo Finance RSS — cached in Redis `news:cache` (30 min TTL) |
| 6 | Markets | `6` | `us_futures_ticks` + `us_futures_ohlcv` — live prices per region |
| 7 | US Futures | `7` | `us_futures_ticks` (live) + `us_futures_ohlcv` (OHLCV chart) |

### 3.2 MERVAL Historical Sub-tabs

| # | Category | Instrument Pattern |
|---|----------|--------------------|
| 1 | Stocks | Not options, not bonds (GGAL, SUPV, PAMP, etc.) |
| 2 | Options | Contains `GFGC` or `GFGV` |
| 3 | Bonds | Contains `AL30`, `GD30`, `AE38`, `AL35`, `GD35` |
| 4 | Favorites | User-defined list, persisted in app state |

### 3.3 Key Bindings

| Key | Context | Action |
|-----|---------|--------|
| `1-7` | Global | Switch main tab directly |
| `Tab` / `→` | Global | Next tab (cycles) |
| `←` | Global | Previous tab |
| `q` | Global | Quit |
| `s` | Binance / MERVAL | Toggle Real-Time / Historical |
| `f` | Historical | Open filter editor (date + instrument dropdown) |
| `r` | Options / Futures / News | Refresh data |
| `c` | Options | Toggle BS calculator panel |
| `Enter` | Options / News | Load chain for selected underlying / open article URL |
| `↑↓` | All | Scroll / navigate |
| `←→` | Futures / Favorites | Switch contract / navigate list |
| `p` | Historical | Switch focus between top/bottom panel |
| `a` / `d` | Favorites | Add / delete favorite |

---

## 4. Data Contract

### 4.1 PostgreSQL Tables

#### `ticks` (TimescaleDB hypertable)
| Column | Type | Notes |
|--------|------|-------|
| `time` | TIMESTAMPTZ | UTC |
| `instrument` | TEXT | See §4.3 naming |
| `bid_price`, `ask_price`, `last_price` | NUMERIC(18,6) | |
| `bid_volume`, `ask_volume` | BIGINT | |
| `total_volume` | BIGINT | **Cumulative daily** — volume per period = MAX−MIN |
| `high`, `low`, `prev_close` | NUMERIC(18,6) | |

#### `orders` (TimescaleDB hypertable)
| Column | Type | Notes |
|--------|------|-------|
| `time` | TIMESTAMPTZ | UTC |
| `instrument` | VARCHAR(50) | Without `M:` prefix |
| `price` | NUMERIC(18,6) | |
| `volume` | BIGINT | |
| `side` | CHAR(1) | `B` = buy, `S` = sell |

#### `binance_ticks` (TimescaleDB hypertable)
| Column | Type | Notes |
|--------|------|-------|
| `symbol` | VARCHAR(20) | e.g. `BTCUSDT`, `USDTARS` |
| `timestamp` | TIMESTAMPTZ | UTC, 1-min klines |
| `open`, `high`, `low`, `close`, `volume` | NUMERIC(18,6) | |

#### `binance_trades` (TimescaleDB hypertable)
| Column | Type | Notes |
|--------|------|-------|
| `time` | TIMESTAMPTZ | UTC |
| `symbol` | TEXT | |
| `price`, `qty` | NUMERIC(18,6) | |
| `is_buyer_maker` | BOOLEAN | true = sell aggression |
| `trade_id` | BIGINT | |

#### `us_futures_ticks`
| Column | Type | Notes |
|--------|------|-------|
| `time` | TIMESTAMPTZ | UTC |
| `symbol` | TEXT | e.g. `ES=F`, `^GSPC`, `EURUSD=X` |
| `last_price` | NUMERIC | |
| `last_volume` | BIGINT | |
| `region` | TEXT | `usa`, `europe`, `asia`, `argentina`, `brazil` (nullable) |
| `asset_class` | TEXT | `indices`, `futures`, `fx` (nullable) |

#### `us_futures_ohlcv`
| Column | Type | Notes |
|--------|------|-------|
| `time` | TIMESTAMPTZ | UTC |
| `symbol` | TEXT | |
| `open`, `high`, `low`, `close` | NUMERIC | |
| `volume` | BIGINT | |
| `region` | TEXT | (nullable) |
| `asset_class` | TEXT | (nullable) |

### 4.2 Query Rules
- All timestamps UTC; convert to ART with `AT TIME ZONE 'America/Argentina/Buenos_Aires'`
- `total_volume` is cumulative — use `MAX - MIN` for period volume
- Use `time_bucket()` for OHLCV aggregation on compressed chunks
- No data on weekends or Argentine market holidays
- Market hours: 10:00–17:00 ART Mon–Fri

### 4.3 Instrument Naming

| Prefix | Market | Example |
|--------|--------|---------|
| `M:bm_MERV_` | BYMA equities/bonds | `M:bm_MERV_AL30_24hs` |
| `M:rx_DDF_DLR_` | MatbaRofex FX futures | `M:rx_DDF_DLR_MAR26` |
| (none) | Binance | `BTCUSDT`, `USDTARS` |

Active futures contract changes monthly — always query dynamically:
```sql
SELECT DISTINCT instrument FROM ticks WHERE time > NOW() - INTERVAL '3 days' AND instrument LIKE '%DDF_DLR%'
```

---

## 5. Options Pricing Engine

### 5.1 Black-Scholes (Rust, inline)

```
Price = S·N(d1) − K·e^(−rT)·N(d2)          [Call]
Price = K·e^(−rT)·N(−d2) − S·N(−d1)        [Put]

d1 = [ln(S/K) + (r + σ²/2)·T] / (σ·√T)
d2 = d1 − σ·√T
```

Greeks computed analytically from the same d1/d2.

### 5.2 Implied Volatility

Newton-Raphson, 20 iterations, starting at σ=0.3. Convergence threshold: vega < 1e-10.

### 5.3 Expiry Parsing

Instrument suffix `OCT25`, `MAR26`, etc. → last calendar day of that month → T = days/365.

### 5.4 Inputs for Calculator

| Field | Default | Notes |
|-------|---------|-------|
| S | — | Spot price |
| K | — | Strike |
| T | — | Days to expiry |
| r | 0.05 | Risk-free rate (annual) |
| σ | — | Volatility (decimal, e.g. 0.30) |
| Type | C | `C` = Call, `P` = Put |

---

## 6. News Pipeline

### 6.1 ByMA Relevant Facts
- Endpoint: `POST https://open.bymadata.com.ar/vanoms-be-core/rest/api/bymadata/free/bnown/relevant-facts`
- Auth: static token header `dc826d4c2dde7519e882a250359a23a0`
- Payload: `{ filter: true, publishDateFrom, publishDateTo, texto: "" }`
- Fields used: `publishDate`, `issuerName`, `description`

### 6.2 Reuters via NewsAPI
- Endpoint: `GET https://newsapi.org/v2/top-headlines?sources=reuters&pageSize=20&apiKey=...`
- Key stored in `.env` as `NEWSAPI_KEY`
- Fields used: `publishedAt`, `title`

All three sources fetched in parallel on tab switch or `[r]`. Results merged, deduplicated by headline, and sorted by time descending.

### 6.3 Redis Cache

News is cached in Redis under key `news:cache` (JSON array of `NewsItem`) with a 30-minute TTL. On subsequent opens the cached result is served instantly without hitting external APIs. Cache is invalidated by TTL or manually via `DEL news:cache`.

---

## 7. Backtesting (Python)

See `backtesting.md` steering file for full rules. Key invariants:

- Data always via `MarketDataBacktester.load_market_data()`
- Timestamps always UTC
- `total_volume` is cumulative — volume per period = MAX − MIN
- Results always persisted to `backtest_runs` table
- Commission: 0.5% per side (1% round-trip)
- Max 2 contracts for DLR futures

### Strategy Signature
```python
def strategy(
    current_market: OrderBookSnapshot | None,
    recent_trades: list[MarketTrade],
    current_position: dict,
    current_cash: float
) -> list[dict]:
    return [{'direction': Direction.BUY, 'volume': 1,
             'order_type': OrderType.MARKET, 'instrument': '...', 'price': None}]
```

---

## 8. Environment Variables

| Variable | Purpose |
|----------|---------|
| `POSTGRES_HOST` | PostgreSQL host |
| `POSTGRES_PORT` | PostgreSQL port (default 5432) |
| `POSTGRES_USER` | PostgreSQL user |
| `POSTGRES_PASSWORD` | PostgreSQL password |
| `POSTGRES_DB` | Database name (marketdata) |
| `REDIS_HOST` | Redis host for live WebSocket data |
| `REDIS_PORT` | Redis port (default 6379) |
| `NEWSAPI_KEY` | NewsAPI.org key for Reuters |
| `BINANCE_API_KEY` | Binance API key |
| `BINANCE_SECRET_KEY` | Binance secret |
| `PPI_PUBLIC_KEY` | PPI broker public key |
| `PPI_PRIVATE_KEY` | PPI broker private key |

---

## 9. Module Map

```
tws_terminal/src/
├── main.rs              — tokio runtime, channel wiring, event loop
│                          establishes shared Arc<Client> at startup
├── ui/app.rs            — TradingApp state, render, input handling
│                          db_client: Option<Arc<Client>> shared across triggers
├── db/mod.rs            — all PostgreSQL queries (time-bounded to prevent full scans)
│                          connect_arc() returns Arc<Client>
│                          fetch_markets_live() for Markets tab
├── network/
│   ├── mod.rs           — message types, deserializers
│   └── websocket.rs     — Redis subscriber (5 channels)
└── data/
    ├── mod.rs           — BinanceSymbolData, ExchangeData, MervalLiveInstrument, RecentTrade
    ├── tick.rs          — Tick struct
    └── order.rs         — Order struct

mcp_server/server.py     — FastMCP server, 34 tools (DB + analytics + Redis)
.mcp.json                — Claude Code project-scoped MCP registration

math/
├── options.py           — Black-Scholes, implied_volatility
├── greeks.py            — greeks_scipy, greeks_quantlib
├── binomial.py          — CRR binomial tree (American options)
└── dlr.py               — CCL calculation, DLR fair value

data/
├── loader.py            — load_tick_data, load_order_data
├── binance_loader.py    — load_binance_data
├── byma_client.py       — ByMAClient (options chain, relevant facts)
└── aggregator.py        — OHLCV aggregation helpers

scrapers/
├── matriz/run.py        — Matriz WebSocket → ticks table + Redis matriz:ticks
├── byma/run.py          — BYMA REST → CEDEARs
├── mae/run.py           — MAE REST → Dólar MEP
└── BINANCE/run.py       — Binance WebSocket → binance_ticks/trades + Redis binance:ticks
```

---

## 10. Performance Notes

- **Shared DB connection**: `Arc<tokio_postgres::Client>` established at startup in `main.rs`, stored in `TradingApp.db_client`. All trigger functions reuse it, falling back to `connect()` if None. Eliminates per-action TCP + Postgres handshake (~100–200 ms).
- **Concurrent queries**: `trigger_historical_fetch` uses `tokio::join!` to pipeline all 4 table queries on one connection.
- **Time bounds on all queries**: every query is scoped to a recent interval (`2 days` for live data, `7 days` for distinct instruments) to avoid full scans on 14M+ row hypertables.
- **News Redis cache**: `news:cache` key with 30 min TTL — avoids 3 external API calls on every tab open.
- **Markets tab**: populated from `us_futures_ticks` + `us_futures_ohlcv` on tab switch, keyed by symbol in `HashMap<String, MarketRow>`.

---

## 11. Validation Checklist (before production)

- [ ] Strategy tested on ≥ 3 contracts
- [ ] Win rate > 40% out-of-sample
- [ ] Profit factor > 1.5
- [ ] Max drawdown < 20%
- [ ] Sharpe ratio > 1.0
- [ ] Results persisted in `backtest_runs`
- [ ] No hardcoded credentials
- [ ] No duplicate PPI classes
- [ ] All timestamps UTC
