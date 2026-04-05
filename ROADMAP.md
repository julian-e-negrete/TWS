# ROADMAP.md — TWS Implementation Plan

> This document tracks the full implementation plan for the TWS Trader Workstation TUI.
> Status: ✅ = done, 🔲 = pending

---

## Phase 0 — Foundation (completed before this session)

| Task | Status |
|------|--------|
| Rust TUI skeleton (Ratatui + Crossterm) | ✅ |
| Redis WebSocket subscriber | ✅ |
| Binance live tab (klines + trades) | ✅ |
| MERVAL live tab (price + sparkline) | ✅ |
| Python math modules (BS, Greeks, Binomial, DLR) | ✅ |
| Python scrapers (Matriz, ByMA, MAE, Binance) | ✅ |
| MCP server (PostgreSQL + MySQL tools) | ✅ |
| pydantic-settings config | ✅ |

---

## Phase 1 — Historical Data in TUI (this session)

### 1.1 PostgreSQL connection from Rust
- Added `tokio-postgres` + `dotenvy` to `Cargo.toml`
- `src/db/mod.rs` — connection helper + 4 query functions
- `.env` loaded at startup via `dotenvy::from_path`

### 1.2 Historical tab (Binance + MERVAL)
- `[s]` toggles Real-Time / Historical subtab
- Historical fetches last 200 rows from `ticks`, `orders`, `binance_ticks`, `binance_trades`
- `DbMessage` channel carries results back to app state
- Tables rendered with `render_stateful_widget` (colors preserved)

### 1.3 Scroll + panel focus
- 4 `TableState`s for historical tables
- `[↑↓]` scrolls focused panel
- `[p]` switches focus between top/bottom panel
- Cyan border on focused panel

### 1.4 Filter with autocomplete dropdown
- Filter bar shows Date + Instrument fields
- `[f]` opens filter editor, `[Tab]` switches fields
- Typing filters a dropdown of known instruments/dates from DB
- `[↑↓]` navigates dropdown, `[Enter]` selects + re-fetches
- Binance tab uses `available_binance_symbols`; MERVAL uses `available_instruments`

### 1.5 MERVAL historical sub-tabs
- `[1-4]` inside MERVAL Historical: Stocks / Options / Bonds / Favorites
- Instruments classified by pattern matching (GFGC/GFGV = options, AL30/GD30 = bonds, rest = stocks)

### 1.6 Favorites panel
- `[a]` adds instrument (with autocomplete dropdown from DB)
- `[d]` deletes selected favorite
- `[←→]` navigates between favorites
- Selected favorite shows: sparkline of last_price + OHLCV stats bar + ticks table + orders table

---

## Phase 2 — New Tabs (this session)

### 2.1 Options tab (`[3]`)
**Chain viewer:**
- Left panel: underlying selector (GGAL, SUPV, PBRD, PAMP, YPFD) — `[↑↓]` + `[Enter]` to load
- Main panel: table with `Instrument | Last | Bid | Ask | IV% | Δ | Γ | Θ | Vega`
- IV computed via Newton-Raphson (20 iterations, pure Rust)
- Greeks computed from BS closed-form (pure Rust, no deps)
- Expiry parsed from instrument suffix (e.g. `OCT25` → days to expiry)

**BS Calculator panel (`[c]`):**
- Right panel (30% width), toggled with `[c]`
- 6 fields: S, K, T(days), r, σ, Type(C/P)
- `[Tab]` cycles fields, `[Enter]` computes
- Output: Price, Δ, Γ, Θ, Vega, Rho

### 2.2 Futures tab (`[4]`)
- `BarChart` widget: one bar per contract, label = last 5 chars (e.g. `MAR26`), value = last price
- Shows last 3 `rx_DDF_DLR_*` contracts (most recent by instrument name)
- `[←→]` switches selected contract
- Bottom panel: scrollable tick table for selected contract
- `[r]` re-fetches

### 2.3 News tab (`[5]`)
- Two parallel `reqwest` tasks on tab switch:
  - **ByMA**: POST to `open.bymadata.com.ar` relevant-facts endpoint
  - **Reuters**: GET `newsapi.org/v2/top-headlines?sources=reuters`
- Results merged and sorted by time descending
- `[ByMA]` badge in cyan, `[Reuters]` badge in yellow
- `[↑↓]` scrolls, `[r]` refreshes

---

## Phase 3 — Optimization (planned)

| Task | Priority | Effort |
|------|----------|--------|
| Redis cache (market data TTL 5s, historical TTL 1h) | High | 8–10h |
| DB indexes on `(instrument, timestamp)` | Medium | 2h |
| Paginated historical fetch (load more on scroll end) | Medium | 4h |
| Persist favorites to disk (JSON sidecar) | Low | 2h |
| Options: fetch live chain from ByMA API (not just DB ticks) | High | 6h |
| Futures: CCL calculation panel (AL30/AL30D spread) | Medium | 4h |

---

## Phase 4 — Scalability (planned)

| Task | Effort |
|------|--------|
| Data Ingestion microservice (FastAPI) | 20–24h |
| RabbitMQ message queue | 12h |
| GitHub Actions CI/CD | 8h |
| Prometheus + Grafana monitoring | 12h |
| Test coverage → 60% | 12–16h |

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Rust TUI (Ratatui) | Zero-copy rendering, sub-millisecond frame times, no GC pauses |
| tokio-postgres (not sqlx) | Simpler API, no macro magic, easier async integration |
| BS/Greeks in Rust (not Python FFI) | Avoids subprocess overhead; math is trivial to reimplement |
| NewsAPI for Reuters | Reuters discontinued public RSS; NewsAPI free tier covers the use case |
| `DbMessage` channel pattern | Keeps DB I/O off the render thread; no blocking in the 30fps loop |
| Dropdown autocomplete from DB | Avoids hardcoding instrument lists; always reflects actual data |
