# DATA_SPEC.md — TWS Data Layer Reference

This document is the single authoritative reference for every data pathway in the TWS
AlgoTrading project. It is intended to be read *instead of* reading source files. An AI
agent or a new developer should be able to understand where data comes from, how it moves
through the system, and where it ends up, without opening any `.rs` or `.py` file.

All paths are relative to the repository root (`/home/haraidasan/programming/gitrepositories/TWS/`).

---

## 1. Data Flow Overview

```
External feed                 Scraper / Job              Storage
─────────────                 ─────────────              ───────
Matriz.eco WebSocket  ──────► scrapers/matriz/run.py ──► PostgreSQL: ticks, orders
ByMA REST             ──────► scrapers/byma/run.py   ──► PostgreSQL: ticks, orders
MAE REST (DLR)        ──────► scrapers/mae/run.py    ──► PostgreSQL: ticks
Binance WebSocket     ──────► scrapers/BINANCE/run.py──► Redis pub/sub + PostgreSQL: binance_ticks, binance_trades
US Futures (yfinance) ──────► job/futuros_tick.py   ──► PostgreSQL: us_futures_ticks, us_futures_ohlcv
Solana DEX            ──────► (scraper)              ──► PostgreSQL: solana_dex_trades
PPI REST              ──────► (scraper)              ──► PostgreSQL: ppi_ohlcv, ppi_options_chain
ByMA relevant facts   ──────── (inline fetch)        ──► Redis key: news:cache (30-min TTL)

                   ┌─────────────────────────────────────────────────────┐
                   │  Rust TUI  (tws_terminal/src/)                      │
                   │                                                     │
  Redis pub/sub ──►│  network/websocket.rs                               │
  (all 5 channels) │    → parse JSON → WebSocketMessage enum             │
                   │    → ws_tx  (UnboundedSender<WebSocketMessage>)     │
                   │                                                     │
  Keyboard ────────│  ui/event_handler.rs                                │
                   │    → key_rx (UnboundedSender<KeyEvent>)             │
                   │                                                     │
  PostgreSQL ──────│  db/mod.rs  (tokio-postgres async queries)          │
  (on demand)      │    ↓ called inside tokio::spawn                     │
                   │    → db_tx  (UnboundedSender<DbMessage>)            │
                   │                                                     │
                   │  ui/app.rs — TradingApp (single shared mutable state)
                   │    handle_websocket_message()  ← ws_rx              │
                   │    handle_db_message()         ← db_rx              │
                   │    handle_input()              ← key_rx             │
                   │    render()  (33 ms timer)                          │
                   └─────────────────────────────────────────────────────┘
```

**Render loop cadence:** 33 ms timer fires; `TradingApp::render()` reads immutable state
from the fields populated by the three inbound channels above and draws the Ratatui frame.
No blocking I/O ever runs inside `render()`.

---

## 2. PostgreSQL Query Functions (`tws_terminal/src/db/mod.rs`)

### Connection

| Function | Signature | Notes |
|---|---|---|
| `connect` | `async fn connect() -> Result<Client>` | Reads `POSTGRES_HOST/PORT/USER/PASSWORD/DB` env vars; defaults to `100.112.16.115:5432 / marketdata`. Spawns driver task. |
| `connect_arc` | `async fn connect_arc() -> Result<Arc<Client>>` | Same but wraps in `Arc` for sharing across `tokio::spawn` tasks. |

### Filter Type

```rust
pub struct HistFilter {
    pub date:       Option<NaiveDate>,   // filter by calendar day (UTC)
    pub instrument: Option<String>,      // substring LIKE match
}
```

### Row Types

```rust
pub struct HistTick        { time, instrument, bid_price, ask_price, last_price, total_volume: i64 }
pub struct HistOrder       { time, instrument, price, volume: i64, side: String }  // side: "B" or "S"
pub struct HistBinanceTick { timestamp, symbol, open, high, low, close, volume: f64 }
pub struct HistBinanceTrade{ time, symbol, price, qty: f64, is_buyer_maker: bool }
pub struct OptionRow       { instrument, last_price, bid, ask: f64 }
pub struct FuturesRow      { instrument, last_price, bid, ask: f64 }
pub struct UsFuturesOhlcv  { time, symbol, open, high, low, close: f64, volume: i64 }
pub struct MarketRow       { symbol, last_price, change_pct: f64, region, asset_class: String }
```

### Query Function Reference

| Function | Tables Queried | Key WHERE / Logic | Returns | DbMessage variant populated |
|---|---|---|---|---|
| `fetch_ticks(client, limit, f)` | `ticks` | `time::date = $date` AND `LOWER(instrument) LIKE $pattern`; if no date, last 2 days | `Vec<HistTick>` (DESC by time) | `DbMessage::Ticks` |
| `fetch_orders(client, limit, f)` | `orders` | Same filter pattern as fetch_ticks | `Vec<HistOrder>` (DESC by time) | `DbMessage::Orders` |
| `fetch_binance_ticks(client, limit, f)` | `binance_ticks` | `timestamp::date = $date` AND `UPPER(symbol) LIKE $pattern`; if no date, last 2 days | `Vec<HistBinanceTick>` | `DbMessage::BinanceTicks` |
| `fetch_binance_trades(client, limit, f)` | `binance_trades` | Same filter as binance_ticks | `Vec<HistBinanceTrade>` | `DbMessage::BinanceTrades` |
| `fetch_binance_price_history(client, symbol, hours)` | `binance_ticks` | `symbol = $1 AND timestamp > NOW() - interval` ORDER ASC | `Vec<u64>` (close × 100 as integers) | `DbMessage::BinancePriceHistory(symbol, points)` |
| `fetch_distinct_instruments(client)` | `ticks` | `time > NOW() - 7 days`; fallback to 30 days if empty (holiday) | `Vec<String>` sorted | `DbMessage::Instruments` |
| `fetch_distinct_dates(client)` | `ticks` + `binance_ticks` | UNION of last 90 days, DISTINCT dates | `Vec<String>` DESC | `DbMessage::Dates` |
| `fetch_distinct_binance_symbols(client)` | `binance_ticks` | `timestamp > NOW() - 7 days` | `Vec<String>` | `DbMessage::BinanceSymbols` |
| `fetch_options_chain(client)` | `ticks` (bid/ask) + `orders` (last trade) | `instrument LIKE '%GFGC%' OR LIKE '%GFGV%'` AND last 7 days; joins via HashMap keyed on stripped `M:` prefix | `Vec<OptionRow>` | `DbMessage::OptionsChain` |
| `fetch_last_price(client, instrument)` | `orders` first, then `ticks` fallback | Orders table strips `M:` prefix; returns single row | `f64` | `DbMessage::GgalSpot` (when called for GGAL) |
| `fetch_futures_curve(client)` | `ticks` | `instrument LIKE 'M:%DDF_DLR%' AND NOT LIKE '%A'` last 30 days; sorted by expiry month/year | `Vec<FuturesRow>` (max 3 near contracts) | `DbMessage::FuturesCurve` |
| `fetch_futures_ticks(client, instrument, limit)` | `ticks` | Exact `instrument = $1` match, last 200 rows DESC | `Vec<HistTick>` | `DbMessage::FuturesTicks` |
| `fetch_distinct_merval_instruments(client, _days)` | `ticks` | Excludes `%DDF_DLR%`; 7-day window, 30-day fallback, max 300 | `Vec<String>` | `DbMessage::MervalInstruments` |
| `fetch_instrument_price_series(client, instrument)` | `ticks` | `time_bucket('1 minute', time)`, last session date via CTE | `Vec<(f64, f64)>` index vs LAST price | (superseded by with_times variant) |
| `fetch_instrument_price_series_with_times(client, instrument, (bucket_interval, lookback))` | `ticks` | TimescaleDB `time_bucket()` from last tick backwards by lookback; timestamps converted to ART (UTC-3) | `(Vec<(f64,f64)>, Vec<String>)` points + ART labels | `DbMessage::MervalPriceSeries` |
| `fetch_instrument_orders(client, instrument)` | `orders` | Strips `M:` prefix; last 500 rows DESC | `Vec<HistOrder>` | `DbMessage::MervalInstrumentOrders` |
| `fetch_us_futures_ohlcv(client, symbol, limit)` | `us_futures_ohlcv` | Exact symbol, reversed to oldest-first for charting | `Vec<UsFuturesOhlcv>` | `DbMessage::UsFuturesOhlcv` |
| `fetch_us_futures_last_prices(client)` | `us_futures_ticks` | `DISTINCT ON (symbol)` latest per symbol | `Vec<(String, f64)>` | (used internally in fetch_markets_live) |
| `fetch_markets_live(client)` | `us_futures_ticks` (prices) + `us_futures_ohlcv` (change%) | Two queries, joined in Rust HashMap; last 2 days; change = (close-open)/open×100 | `Vec<MarketRow>` | `DbMessage::MarketsData` |

### Inline BS Math (`db/mod.rs` is NOT the location — see `ui/app.rs`)

The pure-Rust Black-Scholes implementation lives in `TradingApp` impl blocks in
`tws_terminal/src/ui/app.rs`, not in `db/mod.rs`. See Section 5 for details.

---

## 3. Redis Channels (`tws_terminal/src/network/`)

Redis URL: `redis://100.112.16.115:6379` (no auth), constant `REDIS_URL` in `websocket.rs`.

The subscriber (`network/websocket.rs::connect_websocket`) subscribes to all five channels
in a single connection and dispatches to `WebSocketMessage` variants via `serde_json`.

| Redis Channel | Payload struct | WebSocketMessage variant | TradingApp field updated |
|---|---|---|---|
| `binance:ticks` | `BinanceTick` | `WebSocketMessage::TickUpdate(BinanceTick)` | `symbol_map` (via `BinanceSymbolData::update`), `symbols_by_volume`, `selected_symbol`; triggers DB seed for first tick per symbol |
| `binance:trades` | `BinanceTrade` | `WebSocketMessage::TradeUpdate(BinanceTrade)` | `recent_trades` (VecDeque cap 200, push_front) |
| `us_futures:ticks` | `UsFuturesTick` | `WebSocketMessage::UsFuturesTick(UsFuturesTick)` | `us_futures_live` HashMap (symbol → (current, prev)), `us_futures_history` (cap 500) |
| `matriz:ticks` | `MatrizTick` | `WebSocketMessage::MatrizTick(MatrizTick)` | `merval_live` HashMap, `merval_live_sorted` Vec (sorted, auto-selects row 0) |
| `matriz:orders` | `MatrizOrder` | `WebSocketMessage::MatrizOrder(MatrizOrder)` | `orders` Vec (cap 500) |

**Payload field types** (from `network/mod.rs`):

```rust
BinanceTick   { symbol, timestamp: String, open, high, low, close, volume: f64 }
BinanceTrade  { symbol, time: String, price, quantity (renamed from "qty"), is_buyer_maker, trade_id: u64 }
UsFuturesTick { symbol, last_price: f64, last_volume: u64 }
MatrizTick    { instrument, bid_price, ask_price, last_price, high, low, prev_close: f64 }
MatrizOrder   { instrument, price: f64, volume: u64, side: String }
```

All numeric fields use a custom `de_f64_or_str` / `de_u64_or_str` deserializer that
accepts either JSON numbers or quoted-string numbers in the same field.

**Connection lifecycle:** `connect_websocket` runs an infinite retry loop with 5-second
back-off. On each attempt it sends `WebSocketMessage::Connected("binance")` on success
and `WebSocketMessage::Disconnected("binance")` on drop. The `binance_connected` field
in `TradingApp` tracks this state for the status bar.

---

## 4. TUI Trigger → DbMessage → Field Map (`tws_terminal/src/ui/app.rs`)

All trigger functions follow the same pattern: clone `db_tx` and `db_client`, spawn a
`tokio::spawn` task, call `db/mod.rs` functions inside it, and send `DbMessage` variants
back through the channel. The main loop receives them via `db_rx` and calls
`handle_db_message`.

| Trigger Function | Keyboard / Condition | DbMessage sent | `handle_db_message` effect | TradingApp field(s) |
|---|---|---|---|---|
| `trigger_historical_fetch()` | `s` on Binance/Merval tab (switches to Historical subtab); also fires autocomplete fetch on first use | `Ticks`, `Orders`, `BinanceTicks`, `BinanceTrades`; optionally `Instruments`, `Dates`, `BinanceSymbols` | Sets 4 hist_* Vecs; populates autocomplete lists | `hist_ticks`, `hist_orders`, `hist_binance_ticks`, `hist_binance_trades`, `available_instruments`, `available_dates`, `available_binance_symbols` |
| `trigger_merval_instruments_fetch()` | `s` to Historical on Merval if instruments empty | `MervalInstruments` | Replaces `merval_instruments`; auto-selects row 0 | `merval_instruments`, `merval_inst_list_state` |
| `trigger_merval_price_series(&instrument)` | `Enter` on instrument list; `t` to cycle time range | `MervalPriceSeries`, `MervalInstrumentOrders` | Sets price series + labels; sets detail orders | `merval_selected_instr`, `merval_price_series`, `merval_price_labels`, `merval_detail_orders` |
| `trigger_options_fetch()` | `3` (tab switch); `r` (refresh); `Enter` on Options tab | `GgalSpot`, `OptionsChain` | Sets spot price and chain; clears `options_loading` | `ggal_spot`, `options_chain`, `options_loading` |
| `fetch_futures_ticks_for(&instrument)` | Called automatically after `FuturesCurve` arrives; also on `←`/`→` in Futures tab | `FuturesTicks` | Replaces futures tick table; resets `TableState` | `futures_ticks`, `futures_ticks_state` |
| `trigger_futures_fetch()` | `4` (tab switch); `r` (refresh) | `FuturesCurve` | Sets curve; auto-calls `fetch_futures_ticks_for` for first contract | `futures_curve` |
| `trigger_news_fetch()` | `5` (tab switch); `r` (refresh) | `News` | Replaces news items; clears `news_loading` | `news_items`, `news_loading` |
| `trigger_us_futures_ohlcv()` | `7` (tab switch); `s` on UsFutures tab; `↑`/`↓` in UsFutures Historical | `UsFuturesOhlcv` | Replaces OHLCV vec | `us_futures_ohlcv` |
| `trigger_markets_fetch()` | `6` (tab switch) | `MarketsData` | Rebuilds `markets_data` HashMap | `markets_data` |
| (inline on TickUpdate) | First WebSocket tick for a new symbol | `BinancePriceHistory(symbol, points)` | Calls `symbol_map[symbol].seed_history(points)` | `symbol_map` price history |

**Note on `trigger_news_fetch`:** This function does NOT query PostgreSQL. It:
1. Checks Redis key `news:cache` first (30-minute TTL).
2. If miss, fetches ByMA relevant facts API (`open.bymadata.com.ar`), NewsAPI (if `NEWSAPI_KEY` env var is set), and three Yahoo Finance RSS feeds concurrently.
3. Deduplicates by headline, sorts by time, stores result in Redis, then sends `DbMessage::News`.

---

## 5. TradingApp State Fields (`tws_terminal/src/ui/app.rs`)

### Enums Used for Navigation

| Enum | Variants | Purpose |
|---|---|---|
| `ExchangeTab` | `Binance, Merval, Options, Futures, News, Markets, UsFutures` | Active main tab; keyboard shortcuts `1`–`7` |
| `SubTab` | `RealTime, Historical` | Per-tab sub-view; `s` key toggles |
| `MervalHistTab` | `Stocks, Options, Bonds, Favorites` | Filter category inside MERVAL Historical |
| `MervalTimeRange` | `Min5, Min30, Hour1, Day1, Days7, Days30` | Chart time window; `t` key cycles; maps to `(bucket_interval, lookback)` SQL pairs |
| `InputMode` | `Normal, EditingOrder, FilterEdit, AddingFavorite, CalcEdit` | Keyboard input state machine |
| `HistFocus` | `Top, Bottom` | Which of the two panes is active in Historical view |

### Fields Grouped by Tab

**Global / Infrastructure**

| Field | Type | Purpose | How Populated |
|---|---|---|---|
| `active_tab` | `ExchangeTab` | Current main tab | Keyboard |
| `input_mode` | `InputMode` | Modal input state | Keyboard |
| `db_tx` | `Option<UnboundedSender<DbMessage>>` | Channel to send queries; set by `main.rs` | Set once at startup |
| `db_client` | `Option<Arc<tokio_postgres::Client>>` | Persistent PG connection reused by all triggers | Set once at startup via `connect_arc()` |
| `binance_connected` | `bool` | Redis connection status | `WebSocketMessage::Connected/Disconnected` |
| `error_message` | `Option<String>` | Displayed in status bar | `WebSocketMessage::Error` |
| `hist_loading` | `bool` | Guards against double-trigger | Set `true` in trigger; cleared in `handle_db_message` |
| `hist_error` | `Option<String>` | DB error display | `DbMessage::Error` |
| `filter` | `FilterState` | Date + instrument filter for Historical queries | FilterEdit input mode |
| `available_instruments` | `Vec<String>` | Autocomplete pool for filter | `DbMessage::Instruments` |
| `available_dates` | `Vec<String>` | Autocomplete pool for filter | `DbMessage::Dates` |
| `available_binance_symbols` | `Vec<String>` | Autocomplete pool for Binance filter | `DbMessage::BinanceSymbols` |

**Binance Tab**

| Field | Type | Purpose | How Populated |
|---|---|---|---|
| `binance_subtab` | `SubTab` | RealTime vs Historical | `s` key |
| `symbol_map` | `HashMap<String, BinanceSymbolData>` | Live OHLCV per symbol | `WebSocketMessage::TickUpdate` |
| `symbols_by_volume` | `Vec<String>` | Keys of `symbol_map` sorted by USD volume DESC | Recomputed on each `TickUpdate` |
| `selected_symbol` | `Option<String>` | Currently highlighted symbol | Keyboard `↑`/`↓`; auto-set to first on connect |
| `recent_trades` | `VecDeque<RecentTrade>` | Ring buffer of last 200 trades | `WebSocketMessage::TradeUpdate` |
| `seeded_symbols` | `HashSet<String>` | Guards one-time history seed per symbol | Set on first `TickUpdate` for symbol |
| `hist_binance_ticks` | `Vec<HistBinanceTick>` | Historical 1-min OHLCV rows | `DbMessage::BinanceTicks` |
| `hist_binance_trades` | `Vec<HistBinanceTrade>` | Historical trade rows | `DbMessage::BinanceTrades` |

**MERVAL Tab**

| Field | Type | Purpose | How Populated |
|---|---|---|---|
| `merval_subtab` | `SubTab` | RealTime vs Historical | `s` key |
| `merval_live` | `HashMap<String, MervalLiveInstrument>` | Live quote per instrument (key = full `M:bm_MERV_*` name) | `WebSocketMessage::MatrizTick` |
| `merval_live_sorted` | `Vec<String>` | Sorted keys of `merval_live` for stable table display | Updated on each `MatrizTick` for new instrument |
| `merval_live_state` | `TableState` | Scroll/selection for live table | Keyboard |
| `orders` | `Vec<Order>` | Live executed orders, cap 500 | `WebSocketMessage::MatrizOrder` |
| `hist_ticks` | `Vec<HistTick>` | Historical MERVAL tick rows | `DbMessage::Ticks` |
| `hist_orders` | `Vec<HistOrder>` | Historical MERVAL order rows | `DbMessage::Orders` |
| `merval_hist_tab` | `MervalHistTab` | Category filter (Stocks/Options/Bonds/Favorites) | Keys `1`–`4` in Historical mode |
| `merval_instruments` | `Vec<String>` | Full list of distinct MERVAL instruments | `DbMessage::MervalInstruments` |
| `merval_inst_list_state` | `ListState` | Selection in instrument browser list | Keyboard |
| `merval_selected_instr` | `Option<String>` | Currently charted instrument | Set in `trigger_merval_price_series` |
| `merval_time_range` | `MervalTimeRange` | Chart resolution | `t` key cycles |
| `merval_price_series` | `Vec<(f64, f64)>` | (index, price) chart data points | `DbMessage::MervalPriceSeries` |
| `merval_price_labels` | `Vec<String>` | ART-formatted time labels per point | `DbMessage::MervalPriceSeries` |
| `merval_detail_orders` | `Vec<HistOrder>` | Recent orders for selected instrument | `DbMessage::MervalInstrumentOrders` |
| `favorites` | `Vec<String>` | User-pinned instrument ticker strings | `AddingFavorite` input mode |

**Options Tab**

| Field | Type | Purpose | How Populated |
|---|---|---|---|
| `options_underlyings` | `Vec<&'static str>` | Selectable underlyings: `["GGAL","SUPV","PBRD","PAMP","YPFD"]` | Hardcoded in `new()` |
| `options_underlying_idx` | `usize` | Selected underlying index | Keyboard `←`/`→` |
| `options_chain` | `Vec<OptionRow>` | All calls + puts from DB | `DbMessage::OptionsChain` |
| `options_chain_state` | `TableState` | Selection state for calls panel | Keyboard `↑`/`↓` |
| `options_puts_state` | `TableState` | Selection state for puts panel | Keyboard `↑`/`↓` |
| `options_loading` | `bool` | Prevents duplicate fetches | Set in trigger; cleared on receive |
| `ggal_spot` | `f64` | GGAL last trade price from `orders` table | `DbMessage::GgalSpot` |
| `options_show_calls` | `bool` | Which panel (calls/puts) has focus | `Tab` key toggles |
| `calc_open` | `bool` | BS calculator overlay visible | `c` key |
| `calc_iv` | `String` | User-entered IV override | `CalcEdit` input mode |
| `calc_result` | `Option<(f64,f64,f64,f64,f64,f64)>` | (price, Δ, Γ, Θ, vega, rho) from inline BS | Computed on `Enter` in CalcEdit |

**Inline BS / Greeks in `TradingApp` (defined in `ui/app.rs`)**

These are pure-Rust methods, not DB calls:

| Method | Signature | Notes |
|---|---|---|
| `bs_price` | `fn bs_price(s,k,t,r,sigma,is_call) -> f64` | Standard closed-form Black-Scholes |
| `bs_greeks` | `fn bs_greeks(s,k,t,r,sigma,is_call) -> (f64,f64,f64,f64,f64)` | Returns (delta, gamma, vega, theta, rho) |
| `implied_vol` | `fn implied_vol(market_price,s,k,t,r,is_call) -> f64` | 60-iteration bisection; NaN on impossible price |
| `parse_strike` | `fn parse_strike(instrument) -> f64` | Extracts digits from BYMA ticker; handles ×10 encoding |
| `parse_expiry_days` | `fn parse_expiry_days(instrument) -> f64` | Parses `ENE/FEB/.../DIC` month token; defaults to 30/365 |
| `short_ticker` | `fn short_ticker(instrument) -> String` | Strips `M:bm_MERV_` prefix and `_24hs`/`_48hs` suffix |

**Futures Tab**

| Field | Type | Purpose | How Populated |
|---|---|---|---|
| `futures_curve` | `Vec<FuturesRow>` | DLR contracts near→far (max 3) | `DbMessage::FuturesCurve` |
| `futures_selected` | `usize` | Index into `futures_curve` | `←`/`→` keys |
| `futures_ticks` | `Vec<HistTick>` | Tick history for selected contract | `DbMessage::FuturesTicks` |
| `futures_ticks_state` | `TableState` | Scroll state for tick table | Keyboard |

**US Futures Tab**

| Field | Type | Purpose | How Populated |
|---|---|---|---|
| `us_futures_subtab` | `SubTab` | RealTime vs Historical | `s` key |
| `us_futures_live` | `HashMap<String,(f64,f64)>` | `(current_price, previous_price)` per symbol | `WebSocketMessage::UsFuturesTick` |
| `us_futures_history` | `HashMap<String,Vec<(f64,f64)>>` | `(index, price)` sparkline data, cap 500 | `WebSocketMessage::UsFuturesTick` |
| `us_futures_selected` | `usize` | Index into `us_futures_symbols` | `↑`/`↓` keys |
| `us_futures_ohlcv` | `Vec<UsFuturesOhlcv>` | Daily OHLCV bars for selected symbol | `DbMessage::UsFuturesOhlcv` |
| `us_futures_symbols` | `Vec<&'static str>` | `["ES=F","NQ=F","YM=F","CL=F","GC=F","SI=F","ZB=F"]` | Hardcoded in `new()` |

**News Tab**

| Field | Type | Purpose | How Populated |
|---|---|---|---|
| `news_items` | `Vec<NewsItem>` | Aggregated news from ByMA + NewsAPI + Yahoo RSS | `DbMessage::News` |
| `news_state` | `ListState` | Scroll selection | Keyboard |
| `news_loading` | `bool` | Loading guard | Set in trigger; cleared on receive |

`NewsItem` struct: `{ time: String, source: String, headline: String, url: String, description: String }`.
`Enter` on a selected news item spawns `xdg-open <url>`.

**Markets Tab**

| Field | Type | Purpose | How Populated |
|---|---|---|---|
| `markets_data` | `HashMap<String, MarketRow>` | Latest price + change% per global symbol | `DbMessage::MarketsData` |

---

## 6. MCP Server Tools (`mcp_server/server.py`)

The MCP server uses FastMCP 3.2.0. Start with: `PYTHONPATH=. .venv/bin/python3 mcp_server/server.py`.

Internal helpers: `_pg(sql, params)` uses SQLAlchemy + psycopg2 to PostgreSQL at
`100.112.16.115:5432/marketdata`. `_pg_write(sql, params)` returns rowcount. `_mysql(sql, params)` connects to MySQL at `100.112.16.115:3306/investments`.

Caching: `cache_get`/`cache_set` from `data/cache.py`; `TTL_MARKET` (short) and `TTL_HISTORICAL` (longer) constants. Redis `100.112.16.115:6379` used for both pub/sub and MCP cache.

### Section 1 — Schema / Project Context

| Tool | Underlying Query / Computation | Returns |
|---|---|---|
| `get_project_schema()` | `pg_class` + `information_schema.columns` + TimescaleDB metadata | `dict` keyed by table name: `{total_size, row_estimate, is_hypertable, columns[]}` |
| `get_instrument_conventions()` | Pure dict — no DB query | Naming patterns, prefix rules, known symbol lists, volume note, timezone note |

### Section 2 — Ticks (BYMA Real-Time Quotes)

| Tool | Table | Key Params | Returns |
|---|---|---|---|
| `get_ticks(instrument, limit=100)` | `ticks` | `WHERE instrument = :instrument ORDER BY time DESC LIMIT :limit` (max 1000) | `list[dict]`: time, instrument, bid_price, ask_price, last_price, total_volume, high, low, prev_close |
| `get_ohlcv(instrument, bucket="1 minute", hours_back=24)` | `ticks` | `time_bucket()`, volume = MAX−MIN total_volume | `list[dict]`: bucket, instrument, open, high, low, close, volume |
| `get_active_instruments(days_back=3, filter_pattern="")` | `ticks` | `DISTINCT instrument` with optional LIKE; critical for finding current DLR contract | `list[dict]`: instrument |
| `get_spread(instrument, bucket="1 hour", days_back=7)` | `ticks` | `AVG/MIN/MAX(ask_price - bid_price)` per bucket | `list[dict]`: bucket, spread_avg, spread_min, spread_max |

### Section 3 — Orders (BYMA Executed Trades)

| Tool | Table | Key Params | Returns |
|---|---|---|---|
| `get_orders(hours_back=2, instrument="")` | `orders` | Optional instrument filter; NOTE: no `M:` prefix in `orders` | `list[dict]`: time, instrument, price, volume, side (`B`=buy, `S`=sell) |
| `get_order_flow(days_back=1, instrument_pattern="")` | `orders` | Aggregates buy/sell volume per instrument | `list[dict]`: instrument, vol_buy, vol_sell, num_trades |

### Section 4 — Options Chain

| Tool | Tables | Key Params | Returns |
|---|---|---|---|
| `get_options_chain(underlying="GGAL", days_back=7)` | `ticks` (bid/ask) + `orders` (last price) | Calls `GFGC%`, puts `GFGV%`; computes IV and Greeks via Python scipy | `dict`: `{spot, options: [{instrument, short, type, strike, expiry_days, last, bid, ask, iv, delta, gamma, vega, theta, rho}]}` |
| `get_active_options_instruments(underlying="GGAL", days_back=7)` | `ticks` | DISTINCT instrument LIKE `%GFG%C%` or `%GFG%V%` | `list[str]` of instrument names |

### Section 5 — Futures / DLR

| Tool | Table | Key Params | Returns |
|---|---|---|---|
| `get_futures_curve(days_back=30)` | `ticks` | `LIKE 'M:%DDF_DLR%' NOT LIKE '%A'`; sorted by expiry month | `list[dict]`: instrument, last_price, bid_price, ask_price |
| `get_futures_ticks(instrument, limit=200)` | `ticks` | Exact instrument match DESC | `list[dict]`: time, instrument, bid_price, ask_price, last_price, total_volume |

### Section 6 — CCL (Contado con Liquidación)

| Tool | Table / Computation | Returns |
|---|---|---|
| `get_ccl_rate()` | `ticks` WHERE instrument IN `(AL30_24hs, AL30D_24hs)` + `calculate_ccl()` from `math/dlr.py` | `dict`: al30_bid, al30_ask, al30d_bid, al30d_ask, ccl_mid, ccl_bid, ccl_ask |
| `calculate_ccl_from_prices(al30_bid, al30_ask, al30d_bid, al30d_ask)` | Pure math: `ccl_mid = (al30_bid+al30_ask)/2 / (al30d_bid+al30d_ask)/2` | `dict`: ccl_mid, ccl_bid, ccl_ask |
| `calculate_dlr_fair_value(spot, days, rate_ars, rate_usd=0.0)` | `math/dlr.py::estimate_dlr_fair_value`; formula: `F = S × e^((r_ars−r_usd)×T)` | `dict`: fair_value, spot, days, rate_ars, rate_usd |

### Section 7 — Binance

| Tool | Table | Key Params | Returns |
|---|---|---|---|
| `get_binance_ticks(symbol, limit=60)` | `binance_ticks` | ORDER BY timestamp DESC; max 1440 | `list[dict]`: timestamp, open, high, low, close, volume |
| `get_binance_latest()` | `binance_ticks` | `DISTINCT ON (symbol)` latest close | `list[dict]`: symbol, price, timestamp |
| `get_binance_trades(symbol, limit=100)` | `binance_trades` | Max 500; this is a 2.4 GB table | `list[dict]`: time, symbol, price, qty, is_buyer_maker, trade_id |
| `get_binance_ohlcv(symbol, bucket="1 hour", days_back=7)` | `binance_ticks` | `time_bucket()`; volume = SUM(volume) (already incremental) | `list[dict]`: bucket, symbol, open, high, low, close, volume |

### Section 8 — US Futures & Global Markets

| Tool | Table | Key Params | Returns |
|---|---|---|---|
| `get_us_futures_live()` | `us_futures_ticks` | `DISTINCT ON (symbol)` WHERE region IS NOT NULL | `list[dict]`: symbol, price, region, asset_class, time |
| `get_us_futures_ohlcv(symbol, limit=30)` | `us_futures_ohlcv` | ORDER BY time DESC | `list[dict]`: time, symbol, open, high, low, close, volume, region, asset_class |

### Section 9 — Solana DEX

| Tool | Table | Key Params | Returns |
|---|---|---|---|
| `get_solana_trades(symbol="SOL/USDC", limit=100)` | `solana_dex_trades` | Max 500 | `list[dict]`: time, symbol, price, qty, source_dex, is_buyer_maker, pair_address |
| `get_solana_ohlcv(symbol="SOL/USDC", bucket="1 hour", days_back=3)` | `solana_dex_trades` | `time_bucket()` | `list[dict]`: bucket, symbol, open, high, low, close, volume |

### Section 10 — PPI Historical Data

| Tool | Table | Key Params | Returns |
|---|---|---|---|
| `get_ppi_ohlcv(ticker="GGAL", limit=60)` | `ppi_ohlcv` | ORDER BY date DESC | `list[dict]`: date, ticker, type, open, high, low, close, volume |
| `get_ppi_options_chain(underlying="GGAL", as_of_date="")` | `ppi_options_chain` | Latest date if as_of_date omitted; subquery for MAX(date) | `list[dict]`: ticker, option_type, strike, expiry, date, open, high, low, close, volume |

### Section 11 — Backtest & ML Results

| Tool | Table | Key Params | Returns |
|---|---|---|---|
| `get_backtest_results(instrument="", strategy="", limit=50)` | `bt_strategy_runs` | Optional LIKE filters on instrument and strategy | `list[dict]`: id, run_at, instrument, strategy, date, total_return, sharpe, max_drawdown, win_rate, num_trades, profit_factor, expectancy, metadata |
| `get_best_strategies(instrument, top_n=10)` | `bt_strategy_runs` | GROUP BY strategy; WHERE sharpe > 0; ORDER BY avg_sharpe DESC | `list[dict]`: strategy, instrument, avg_sharpe, avg_return, avg_drawdown, avg_win_rate, run_count |
| `get_ml_episodes(instrument="GGAL_OPTIONS", limit=100)` | `ml_training_episodes` | ORDER BY ts DESC | `list[dict]`: ts, instrument, run_date, stage, episode, reward, steps, loss, accuracy, regimes_covered |
| `get_signal_stats(run_id=0)` | `signal_stats` | All if run_id=0; filter by run_id otherwise | `list[dict]` |

### Section 12 — Math / Analytics

| Tool | Library Function | Returns |
|---|---|---|
| `calculate_bs_price(S,K,T,r,sigma,opt_type="C")` | `math/options.py::black_scholes` | `dict`: price, S, K, T, r, sigma, opt_type |
| `calculate_greeks(S,K,T,r,sigma,opt_type="C")` | `math/greeks.py::greeks_scipy` (finite-difference) | `dict`: delta, gamma, vega, theta, rho, S, K, T |
| `calculate_implied_vol(S,K,T,r,market_price,opt_type="C")` | `math/options.py::implied_volatility` (Brent's method) | `dict`: iv, S, K, T, market_price + greeks if iv is valid |

### Section 13 — Redis Live Snapshot

| Tool | Mechanism | Returns |
|---|---|---|
| `get_redis_live_snapshot(timeout_ms=2000)` | Subscribes to all 5 channels, collects messages for `timeout_ms`, returns latest per channel | `dict`: status, channels_received, data (latest JSON per channel) |

### Section 14 — Write Tools

| Tool | Table | Effect |
|---|---|---|
| `save_backtest_result(strategy_name, instrument, sharpe_ratio, total_return, max_drawdown, ...)` | `bt_strategy_runs` | INSERT one row; returns `{"saved": true}` |

---

## 7. Python Math Layer

All math modules are in `math/` at the repository root. The MCP server loads them via a
`importlib` path trick (to avoid shadowing Python's built-in `math` C module) and registers
them under the `tws_math` alias in `sys.modules`.

### `math/options.py`

| Export | Signature | Algorithm | Called by |
|---|---|---|---|
| `black_scholes(S,K,T,r,sigma,opt_type)` | Returns `float` price | Standard closed-form; uses `scipy.stats.norm.cdf` | `calculate_bs_price` MCP tool; `get_options_chain` MCP tool |
| `implied_volatility(S,K,T,r,market_price,opt_type)` | Returns `float` IV or `NaN` | Brent's method via `scipy.optimize.brentq` | `calculate_implied_vol` MCP tool; `get_options_chain` MCP tool |

### `math/greeks.py`

| Export | Signature | Algorithm | Called by |
|---|---|---|---|
| `greeks_scipy(S,K,T,r,sigma,opt_type)` | Returns `(delta, gamma, vega, theta, rho)` | Finite-difference numerical differentiation using `scipy` | `calculate_greeks` MCP tool; `get_options_chain` MCP tool; `calculate_implied_vol` MCP tool |

### `math/dlr.py`

| Export | Signature | Algorithm | Called by |
|---|---|---|---|
| `calculate_ccl(al30_bid,al30_ask,al30d_bid,al30d_ask)` | Returns `(ccl_mid, ccl_bid, ccl_ask)` | `mid = (bid+ask)/2`; `bid_ccl = al30_bid/al30d_ask`; `ask_ccl = al30_ask/al30d_bid` | `get_ccl_rate` MCP tool; `calculate_ccl_from_prices` MCP tool |
| `estimate_dlr_fair_value(spot,days,rate_ars,rate_usd=0.0)` | Returns `float` fair value | `F = spot × e^((rate_ars − rate_usd) × days/365)` | `calculate_dlr_fair_value` MCP tool |

**Rust vs Python BS:** The Rust TUI has its own inline Black-Scholes implementation in
`TradingApp` methods (`ui/app.rs::bs_price`, `bs_greeks`, `implied_vol`). This uses an
Abramowitz & Stegun error-function polynomial (no external deps). The Python MCP server
uses `scipy` for both IV (Brent's method) and Greeks (finite-difference), which is
numerically more robust but requires the Python environment. The two implementations are
independent and should agree to within ~1 bp for realistic inputs.

---

## 8. Adding a New Data Source

Follow these steps when adding a new data type end-to-end. Example: adding `ppi_ohlcv`
historical chart data to the MERVAL tab.

### Step 1: Add the SQL query function in `tws_terminal/src/db/mod.rs`

```rust
#[derive(Clone, Debug)]
pub struct PpiOhlcvRow {
    pub date:   chrono::NaiveDate,
    pub ticker: String,
    pub open:   f64,
    pub close:  f64,
    // ... other fields
}

pub async fn fetch_ppi_ohlcv(client: &Client, ticker: &str, limit: i64) -> Result<Vec<PpiOhlcvRow>> {
    let rows = client.query(
        "SELECT date, ticker, open::float8, close::float8
         FROM ppi_ohlcv WHERE ticker = $1 ORDER BY date DESC LIMIT $2",
        &[&ticker, &limit],
    ).await?;
    Ok(rows.iter().map(|r| PpiOhlcvRow {
        date:   r.get(0),
        ticker: r.get(1),
        open:   r.get(2),
        close:  r.get(3),
    }).collect())
}
```

### Step 2: Add a `DbMessage` variant in `tws_terminal/src/ui/app.rs`

```rust
pub enum DbMessage {
    // ... existing variants ...
    PpiOhlcv(Vec<crate::db::PpiOhlcvRow>),
}
```

### Step 3: Add a trigger function in `TradingApp` impl

```rust
fn trigger_ppi_ohlcv_fetch(&mut self, ticker: &str) {
    let Some(tx) = self.db_tx.clone() else { return };
    let t = ticker.to_string();
    let client = self.db_client.clone();
    tokio::spawn(async move {
        if let Some(c) = Self::get_db_client(client).await {
            match crate::db::fetch_ppi_ohlcv(&c, &t, 60).await {
                Ok(rows) => { let _ = tx.send(DbMessage::PpiOhlcv(rows)); }
                Err(e)   => { let _ = tx.send(DbMessage::Error(format!("{e}"))); }
            }
        }
    });
}
```

### Step 4: Handle the variant in `handle_db_message`

```rust
pub fn handle_db_message(&mut self, msg: DbMessage) {
    self.hist_loading = false;
    match msg {
        // ... existing arms ...
        DbMessage::PpiOhlcv(rows) => { self.ppi_ohlcv = rows; }
        // ...
    }
}
```

### Step 5: Add the field to `TradingApp` struct and initialise in `new()`

```rust
// in struct definition
pub ppi_ohlcv: Vec<crate::db::PpiOhlcvRow>,

// in TradingApp::new()
ppi_ohlcv: Vec::new(),
```

### Step 6: Wire up the trigger

Call `self.trigger_ppi_ohlcv_fetch("GGAL")` from the appropriate keyboard handler in
`handle_input()` or from `on_tab_switch()`.

### Step 7: Render the data

In the relevant `render_*` function, read `self.ppi_ohlcv` and pass data to Ratatui
widgets. All rendering is read-only; never mutate state inside a render function.

---

*Last updated: 2026-04-09. Generated from reading `tws_terminal/src/db/mod.rs`,
`tws_terminal/src/ui/app.rs`, `tws_terminal/src/network/websocket.rs`,
`tws_terminal/src/network/mod.rs`, and `mcp_server/server.py`.*
