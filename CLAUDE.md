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

---

## Python Module Map (`finance/`)

```
finance/
├── config/settings.py          ★ Single source of truth for all config
├── utils/logger.py             ★ Structured logging (loguru) — use everywhere
├── PPI/classes/                ★ Single source of truth for PPI broker classes
│   ├── account_ppi.py          — Auth, orders, account management
│   ├── market_ppi.py           — Market data, WebSocket streaming
│   ├── Instrument_class.py     — Sharpe, volatility, QuantLib
│   └── Opciones_class.py       — Black-Scholes, GARCH, Greeks
├── BINANCE/monitor/            — Real-time Binance 

```

### Key Invariants

1. **No hardcoded credentials** — all secrets via `.env` + `finance.config.settings`
2. **No duplicate PPI classes** — `finance/PPI/classes/` is the only copy
3. **No duplicate indicator logic** — reuse `finance/HFT/dashboard/calcultions.py`
4. **All backtest data** enters via `MarketDataBacktester.load_market_data()`
5. **All backtest results** persist to `backtest_runs` table in PostgreSQL
6. **Active futures instrument** is always queried dynamically — never hardcoded
7. **`total_volume` in `ticks`** is cumulative daily — volume per period = `MAX - MIN`

---

## Coding Standards

### Configuration
```python
# Always
from finance.config import settings
host = settings.db.host
# Never hardcode: host = "192.168.0.244"
```

### Logging
```python
# Always
from finance.utils.logger import logger
logger.info("Loading data for {instrument}", instrument=instrument)
# Never: print("Loading data")
```

### Imports — PPI classes (single source of truth)
```python
from finance.PPI.classes.market_ppi import Market_data
from finance.PPI.classes.account_ppi import Account
from finance.PPI.classes.Instrument_class import Instrument
from finance.PPI.classes.Opciones_class import Opciones
# Never import from finance.dashboard.classes.* or finance.HFT.backtest.PPI.*
```

### Active futures instrument
```python
# Always query dynamically
active = await session.call_tool("get_active_instruments", {})
instrument = next(r["instrument"] for r in active if "DDF_DLR" in r["instrument"])
# Never: instrument = "M:rx_DDF_DLR_MAR26"
```

---

## Scraper Server

- **This project (AlgoTrading)** = consumer / processor / backtester. Runs locally.
- **Scraper server (`192.168.1.244` / `100.112.16.115` tailscale)** = data producer. Ingests market data into PostgreSQL + MySQL.
- SSH: `ssh 192.168.1.244` — project at `/home/julian/python/programming/`

| Service | Runs on | What it does |
|---------|---------|-------------|
| `binance_monitor.service` | 192.168.1.244 | Binance kline WebSocket → `binance_ticks`. Mon–Fri 10:00–17:00 ART only |
| `wsclient.service` | 192.168.1.244 | Matriz WebSocket → `ticks`. Mon–Fri 10:00–17:00 ART |
| crontab `order_side.py` | 192.168.1.244 | Polls Matriz REST → `orders` every 2 min during market hours |

No new rows outside market hours is expected, not a bug.

---

## External Services

| Service | Protocol | Credential Keys | Usage |
|---------|----------|-----------------|-------|
| PPI (Portfolio Personal) | REST + WebSocket | `PPI_PUBLIC_KEY`, `PPI_PRIVATE_KEY` | Orders, market data |
| Binance | WebSocket (kline) | `BINANCE_API_KEY`, `BINANCE_API_SECRET` | Crypto prices |
| Matriz.eco | WebSocket | Session cookies via Playwright | HFT futures ticks |
| MAE REST API | HTTP/REST | None (public) | Dólar MEP, FX futures |
| BYMA REST API | HTTP/REST | Static token in header | CEDEARs, options chain |

---

## Workflow Rules (Mandatory)

### GLPI Ticket Lifecycle

Every task MUST have a GLPI ticket opened BEFORE any work begins. No code, no file edits, no commits until the ticket is open.

**Known user IDs:**
| ID | Name | Role |
|----|------|------|
| 13 | AlgoTrade Server | This agent — always the requester |
| 15 | Scraper-Server | Assign scraper-server tickets here |

**Use MCP tools** for all GLPI operations: `create_server_ticket`, `complete_server_ticket`, `list_server_tickets`, `proxy_health`. **Never use curl.**

**Full flow (3 steps before work, 1 step after):**
```
# Auth
POST http://100.112.16.115:8080/api/v2.2/token
  {grant_type:"password", client_id:"5880211c5e72134f1ae47dda08377e4b503bd3d15f93d858dda5ab82a4a000e0",
   client_secret:"b6d8fbdc08f6443abce916dae0d5184f56793a50782130e3c6fa6153692d165c",
   username:"AlgoTrade Server", password:"45237348", scope:"api user"}

# Create ticket → get {id}
POST /Assistance/Ticket  {name, content, type:2, urgency:3, impact:3, priority:3}

# MANDATORY: add AlgoTrade Server (id:13) as requester
POST /Assistance/Ticket/<id>/TeamMember  {type:"User", id:13, role:"requester"}

# --- DO WORK ---

# Close ticket (complete_server_ticket MCP tool does steps 4+5 automatically)
```

### Commit Rule
After every task where files were modified: `git add`, `git commit -m "<type>: <desc>"`, `git push`. Do this BEFORE closing the GLPI ticket.

### Changelog Rule
After every turn where files were edited or created, prepend bullets under today's UTC date in `CHANGELOG.md`. Tag each bullet: `[feat]`, `[fix]`, `[refactor]`, `[chore]`, `[docs]`. Never add an entry for `CHANGELOG.md` itself.

### Verification Rule
After every implementation, verify before declaring done:
1. Service/process running?
2. Data flowing (metrics populated)?
3. Visible in Grafana?

### No-Stall Rule
Never run long-lived processes in the foreground of a tool call. Always use `systemd` for persistent services. Never use `sleep N && ...` for waits > 10s.
