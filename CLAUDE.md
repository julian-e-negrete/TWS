# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Reference Documents (read these before source files)

| Document | When to use |
|----------|-------------|
| `Documentation/DATA_SPEC.md` | **Primary reference.** Before reading any source file to understand data format, query structure, function location, or trigger→field mapping. Covers every db/mod.rs function, all Redis channels, all MCP tools, and a new-source guide. Note: the root `DATA_SPEC.md` is a *different* file — the server-side ingestion contract. Always use the one in `Documentation/`. |
| `Documentation/ARCHITECTURE.md` | Full Rust TUI module audit — authoritative for module structure. |
| `Documentation/SPEC.md` | Tab specs, key bindings, data contracts. |
| `Documentation/DATA_INVENTORY.md` | Live DB/Redis inventory: row counts, schemas, date ranges. |

## Project Overview

TWS is a terminal trading workstation for Argentine and cryptocurrency markets. It combines a **Rust TUI frontend** (Ratatui + Tokio) with a **Python data pipeline backend**. The app is read-only — research and visualization, not order execution.

## Build & Run Commands

### Rust TUI (primary application)

```bash
cd tws_terminal
cargo run --release      # Build + run
cargo build --release    # Build only
cargo check              # Type-check without building
cargo clippy             # Lint
```

### Python environment

```bash
# From repo root
source .venv/bin/activate
export PYTHONPATH=.

# Run scrapers (each is a long-running background service)
python3 python_modules/scrapers/matriz/run.py
python3 python_modules/scrapers/BINANCE/run.py
python3 python_modules/scrapers/byma/run.py
python3 python_modules/scrapers/mae/run.py

# Run cron jobs
python3 python_modules/job/futuros_tick_by_tick.py
python3 python_modules/job/order_side.py
```

### MCP server

```bash
PYTHONPATH=. python3 python_modules/mcp_server/server.py
```

No Makefile, CI/CD, or test suite is configured.

## Architecture

### Data Flow

```
External feeds → Python scrapers → PostgreSQL / Redis → Rust TUI
```

| Feed | Scraper | Sink |
|------|---------|------|
| Matriz.eco WebSocket | scrapers/matriz/run.py | PostgreSQL `ticks` |
| ByMA REST | scrapers/byma/run.py | PostgreSQL `ticks`, `orders` |
| MAE REST (DLR) | scrapers/mae/run.py | PostgreSQL `ticks` |
| Binance WebSocket | scrapers/BINANCE/run.py | Redis pub/sub + PostgreSQL |

### Rust TUI internals (`tws_terminal/src/`)

The Tokio runtime runs three concurrent tasks connected via unbounded channels:
- **Redis subscriber** (`network/websocket.rs`) → `ws_tx` channel
- **Keyboard reader** (`ui/event_handler.rs`) → `key_rx` channel
- **33 ms render timer**

All TUI state lives in `TradingApp` (`ui/app.rs`, ~3500 lines). It owns five tabs (`ExchangeTab` enum: Binance, Merval, Options, Futures, News). User input navigates tabs, filters, and sub-tabs via an `InputMode` state machine. DB results arrive asynchronously via `DbMessage` sent over a channel from tokio-spawned tasks.

`db/mod.rs` contains all async PostgreSQL queries (tokio-postgres) plus a pure-Rust Black-Scholes / Greeks / IV implementation.

### Python modules (`python_modules/`)

| Path | Purpose |
|------|---------|
| `config/settings.py` | Pydantic BaseSettings with 16+ config classes; singleton via `@lru_cache()` |
| `shared/db_pool.py` | ThreadedConnectionPool (psycopg2) + SQLAlchemy engines |
| `shared/models.py` | Pydantic models: `Tick`, `Order`, `BinanceTick`, `Cookie` |
| `math/options.py` | Black-Scholes, IV (scipy); `math/greeks.py` adds QuantLib Greeks |
| `data/loader.py` | `load_tick_data()`, `load_order_data()` from PostgreSQL |
| `data/byma_client.py` | ByMA REST client (options chain, relevant facts) |
| `mcp_server/server.py` | FastMCP server exposing read-only DB tools to AI agents |

### Infrastructure

- **PostgreSQL + TimescaleDB** at `100.112.16.115:5432`, database `marketdata`
  - Hypertables: `ticks`, `orders`, `binance_ticks`, `binance_trades`, `backtest_runs`
- **MySQL** at `100.112.16.115:3306`, database `investments` (historical OHLCV)
- **Redis** at `100.112.16.115:6379` — channels `binance:ticks`, `binance:trades`

### Environment

All credentials come from `.env` at the repo root (loaded by `dotenvy` in Rust, `pydantic-settings` in Python). Key variables: `POSTGRES_*`, `DB_*` (MySQL), `REDIS_HOST/PORT`, `BINANCE_API_KEY/SECRET`, `MATRIZ_USER/PASSWORD`, `NEWSAPI_KEY`.

## Key Limitations (from ARCHITECTURE.md)

- Options expiry parsing (`parse_expiry_days`) defaults to 30 days when BYMA ticker format is unrecognized.
- GGAL spot price is fetched from the `orders` table last trade — may be stale outside market hours.
- Only Binance symbols actively pushed by the scraper server appear in the live feed.
- No data on weekends/holidays; historical queries return the last available session.

## Documentation

- `Documentation/ARCHITECTURE.md` — full Rust TUI module audit (authoritative reference)
- `Documentation/SPEC.md` — tab specs, key bindings, data contracts
- `Documentation/DATA_SPEC.md` — PostgreSQL/MySQL schema and access patterns
- `Documentation/ROADMAP.md` — Phase 0 (complete) through Phase 3 (planned)
