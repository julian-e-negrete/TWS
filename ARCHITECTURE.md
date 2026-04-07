# TWS Terminal — Architecture & Function Reference

> Complete audit of the Rust TUI application: data flow, module responsibilities, and function index.
> Last updated: 2026-04-05

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        tws_terminal (Rust)                          │
│                                                                     │
│  main.rs ──── tokio runtime, 3 channels, 30fps render loop         │
│     │                                                               │
│     ├── network/websocket.rs ── Redis pub/sub subscriber            │
│     ├── ui/app.rs ──────────── TradingApp state + render + input   │
│     ├── db/mod.rs ──────────── PostgreSQL query functions           │
│     └── ui/event_handler.rs ── keyboard input thread               │
└─────────────────────────────────────────────────────────────────────┘
         │                    │                    │
    Redis pub/sub        PostgreSQL           HTTP (reqwest)
    100.112.16.115:6379  100.112.16.115:5432  NewsAPI / ByMA / Yahoo
         │                    │
    binance:ticks        marketdata DB
    binance:trades       (TimescaleDB)
```

---

## 2. Entry Point — `main.rs`

### Startup sequence
1. Load `.env` from workspace root via `dotenvy`
2. Initialize Crossterm raw mode + alternate screen
3. Create `Terminal<CrosstermBackend>`
4. Spawn 3 concurrent tasks:
   - `connect_websocket(ws_tx)` — Redis subscriber (tokio task, loops forever)
   - `spawn_input_task()` — keyboard reader (OS thread, blocking)
   - Render interval — 33ms timer (~30 fps)
5. Create `TradingApp::new()`, inject `db_tx` sender
6. Enter `tokio::select!` event loop

### Channels

| Channel | Type | Direction | Purpose |
|---------|------|-----------|---------|
| `ws_tx / ws_rx` | `UnboundedChannel<WebSocketMessage>` | Redis → App | Live Binance klines + trades |
| `db_tx / db_rx` | `UnboundedChannel<DbMessage>` | DB tasks → App | Historical data, options chain, news |
| `key_rx` | `UnboundedReceiver<KeyEvent>` | OS thread → App | Keyboard input |

### Event loop (tokio::select!)
```
Every 33ms  → terminal.draw(|f| app.render(f))
ws_rx msg   → app.handle_websocket_message(msg)
db_rx msg   → app.handle_db_message(msg)
key_rx key  → app.handle_input(key) → false = quit
```

---

## 3. Network Layer — `src/network/`

### `mod.rs` — Message types

| Type | Fields | Source |
|------|--------|--------|
| `BinanceTick` | symbol, open, high, low, close, volume | Redis `binance:ticks` |
| `BinanceTrade` | symbol, time, price, quantity, is_buyer_maker | Redis `binance:trades` |
| `WebSocketMessage` | enum: TickUpdate, TradeUpdate, Connected, Disconnected, Error, PriceUpdate, OrderUpdate | — |

Both `BinanceTick` and `BinanceTrade` use custom deserializers (`de_f64_or_str`, `de_u64_or_str`) that accept both JSON strings and numbers.

### `websocket.rs` — Redis subscriber

| Function | Signature | Description |
|----------|-----------|-------------|
| `connect_websocket` | `(tx: UnboundedSender<WebSocketMessage>) -> Result<()>` | Outer retry loop. Calls `try_connect`, sleeps 5s on failure, loops forever |
| `try_connect` | `(tx) -> Result<()>` | Opens Redis connection, subscribes to `binance:ticks` + `binance:trades`, dispatches messages to `tx` |

**Redis server:** `100.112.16.115:6379`  
**Channels:** `binance:ticks`, `binance:trades`

---

## 4. Database Layer — `src/db/mod.rs`

All functions are `async`, take a `&Client` (tokio-postgres), return `Result<Vec<T>>`.

### Connection
```rust
connect() -> Result<Client>
// Reads: POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
// Default: 100.112.16.115:5432 / marketdata
```

### Row types

| Struct | Fields | Table |
|--------|--------|-------|
| `HistTick` | time, instrument, bid_price, ask_price, last_price, total_volume | `ticks` |
| `HistOrder` | time, instrument, price, volume, side | `orders` |
| `HistBinanceTick` | timestamp, symbol, open, high, low, close, volume | `binance_ticks` |
| `HistBinanceTrade` | time, symbol, price, qty, is_buyer_maker | `binance_trades` |
| `OptionRow` | instrument, last_price, bid, ask | `ticks` + `orders` |
| `FuturesRow` | instrument, last_price, bid, ask | `ticks` |
| `HistFilter` | date: Option<NaiveDate>, instrument: Option<String> | — |

### Query functions

| Function | Query | Notes |
|----------|-------|-------|
| `fetch_ticks(client, limit, filter)` | `SELECT ... FROM ticks WHERE time::date=$1 AND LOWER(instrument) LIKE $2 ORDER BY time DESC LIMIT $3` | Supports date + instrument filter |
| `fetch_orders(client, limit, filter)` | Same pattern on `orders` | |
| `fetch_binance_ticks(client, limit, filter)` | Same on `binance_ticks` | |
| `fetch_binance_trades(client, limit, filter)` | Same on `binance_trades` | |
| `fetch_options_chain(client)` | Two-step: DISTINCT instruments (7d, bid>0), then per-instrument: MAX(bid)/MIN(ask) from last session date + last trade from `orders` | Returns liquid GFGC/GFGV options only |
| `fetch_futures_curve(client)` | DISTINCT ON (instrument) last tick per DDF_DLR contract, last 90d, ordered by time DESC, LIMIT 3 | Returns 3 most recently active contracts |
| `fetch_futures_ticks(client, instrument, limit)` | `SELECT ... FROM ticks WHERE instrument=$1 ORDER BY time DESC LIMIT $2` | Per-contract tick history |
| `fetch_last_price(client, instrument)` | Tries `orders` first, falls back to `ticks.last_price` | Used for GGAL spot |
| `fetch_distinct_instruments(client)` | `SELECT DISTINCT instrument FROM ticks ORDER BY instrument` | Autocomplete candidates |
| `fetch_distinct_dates(client)` | UNION of dates from `ticks` + `binance_ticks`, last 90 | Autocomplete candidates |
| `fetch_distinct_binance_symbols(client)` | `SELECT DISTINCT symbol FROM binance_ticks` | Autocomplete candidates |

---

## 5. UI Layer — `src/ui/app.rs`

### Enums

| Enum | Variants | Purpose |
|------|----------|---------|
| `ExchangeTab` | Binance, Merval, Options, Futures, News | Active main tab |
| `SubTab` | RealTime, Historical | Binance/MERVAL sub-mode |
| `MervalHistTab` | Stocks, Options, Bonds, Favorites | MERVAL historical category |
| `InputMode` | Normal, EditingOrder, FilterEdit, AddingFavorite, CalcEdit | Current keyboard context |
| `HistFocus` | Top, Bottom | Which historical panel receives scroll |
| `FilterField` | Date, Instrument | Active filter input field |

### Key structs

| Struct | Purpose |
|--------|---------|
| `TradingApp` | All application state — single source of truth |
| `FilterState` | Filter inputs + parsed `HistFilter` + dropdown candidates |
| `NewsItem` | time, source, headline, url |
| `BinanceSymbolData` | Per-symbol OHLCV + sparkline history |
| `ExchangeData` | MERVAL live price + sparkline |
| `RecentTrade` | Live Binance trade for the trades panel |

### `TradingApp` state groups

| Group | Fields |
|-------|--------|
| Navigation | `active_tab`, `binance_subtab`, `merval_subtab`, `merval_hist_tab` |
| Binance live | `symbol_map`, `symbols_by_volume`, `selected_symbol`, `recent_trades`, `binance_connected` |
| MERVAL live | `merval_data`, `orders`, `orders_table_state` |
| Historical | `hist_ticks`, `hist_orders`, `hist_binance_ticks`, `hist_binance_trades`, `hist_loading`, `hist_error` |
| Historical scroll | `hist_ticks_state`, `hist_orders_state`, `hist_binance_ticks_state`, `hist_binance_trades_state`, `hist_focus` |
| Filter | `filter: FilterState`, `available_instruments`, `available_dates`, `available_binance_symbols` |
| Favorites | `favorites`, `fav_selected`, `fav_input`, `fav_ticks_state`, `fav_orders_state`, `fav_focus`, `fav_dropdown`, `fav_dropdown_idx` |
| Options | `options_chain`, `options_chain_state`, `options_puts_state`, `options_show_calls`, `options_loading`, `ggal_spot` |
| Calculator | `calc_open`, `calc_iv`, `calc_result` |
| Futures | `futures_curve`, `futures_selected`, `futures_ticks`, `futures_ticks_state` |
| News | `news_items`, `news_state`, `news_loading` |
| Channel | `db_tx: Option<UnboundedSender<DbMessage>>` |

### `DbMessage` variants

| Variant | Payload | Trigger |
|---------|---------|---------|
| `Ticks` | `Vec<HistTick>` | Historical fetch |
| `Orders` | `Vec<HistOrder>` | Historical fetch |
| `BinanceTicks` | `Vec<HistBinanceTick>` | Historical fetch |
| `BinanceTrades` | `Vec<HistBinanceTrade>` | Historical fetch |
| `Instruments` | `Vec<String>` | First historical fetch (autocomplete) |
| `Dates` | `Vec<String>` | First historical fetch (autocomplete) |
| `BinanceSymbols` | `Vec<String>` | First historical fetch (autocomplete) |
| `OptionsChain` | `Vec<OptionRow>` | Options tab load |
| `GgalSpot` | `f64` | Options tab load |
| `FuturesCurve` | `Vec<FuturesRow>` | Futures tab load |
| `FuturesTicks` | `Vec<HistTick>` | Futures contract selection |
| `News` | `Vec<NewsItem>` | News tab load / refresh |
| `Error` | `String` | Any failed DB/HTTP task |

### Public methods

| Method | Description |
|--------|-------------|
| `new()` | Initialize all state with defaults |
| `handle_websocket_message(msg)` | Route `WebSocketMessage` → update live data |
| `handle_db_message(msg)` | Route `DbMessage` → update historical/options/futures/news state |
| `handle_input(key) -> bool` | Process keyboard event; returns `false` to quit |
| `render(frame)` | Top-level render dispatcher |

### Private fetch triggers (spawn tokio tasks → send DbMessage)

| Method | Spawns task for |
|--------|----------------|
| `trigger_historical_fetch()` | All 4 historical tables + autocomplete (first time only) |
| `trigger_options_fetch()` | Options chain + GGAL spot |
| `trigger_futures_fetch()` | Futures curve (3 contracts) |
| `fetch_futures_ticks_for(instrument)` | Ticks for one futures contract |
| `trigger_news_fetch()` | ByMA relevant facts + NewsAPI + Yahoo Finance RSS |

### Math functions (pure Rust, no deps)

| Function | Description |
|----------|-------------|
| `bs_price(s,k,t,r,sigma,is_call)` | Black-Scholes option price |
| `bs_greeks(s,k,t,r,sigma,is_call)` | Returns (delta, gamma, vega, theta, rho) |
| `implied_vol(market_price,s,k,t,r,is_call)` | Bisection method, 60 iterations, 1e-6 precision |
| `norm_cdf(x)` | Standard normal CDF via `libm_erf` approximation |
| `parse_strike(instrument)` | Extracts strike from BYMA ticker: raw/10 normally, raw if 10000–19999 |
| `option_sort_key(instrument)` | Returns (series_letter, strike×10) for sorting |
| `short_ticker(instrument)` | Strips `M:bm_MERV_` prefix and `_24hs` suffix |
| `parse_expiry_days(instrument)` | Parses month name from instrument → days/365; defaults to 30/365 |

### Render methods

| Method | Renders |
|--------|---------|
| `render(frame)` | Top-level dispatcher — routes to tab-specific renders |
| `render_tabs` | 5-tab bar with color coding |
| `render_subtabs` | Real-Time / Historical toggle (Binance + MERVAL only) |
| `render_status_bar` | Context-aware status line per active tab |
| `render_input_area` | Context-aware controls hint |
| `render_filter_bar` | Date + instrument filter with dropdown overlay |
| `render_binance_view` | Symbol list + sparkline + OHLCV stats |
| `render_recent_trades` | Live trade tape for selected symbol |
| `render_merval_view` | MERVAL sparkline + stats |
| `render_orders_table` | Live order management table |
| `render_historical_placeholder` / `_bottom` | Binance historical tables |
| `render_merval_historical` | MERVAL historical dispatcher (routes to sub-tabs) |
| `render_merval_hist_tabs` | [1]Stocks [2]Options [3]Bonds [4]Favorites tab bar |
| `render_category_ticks` / `_orders` | Filtered tick/order tables per MERVAL category |
| `render_favorites_view` | Favorites list + sparkline + OHLCV + tick/order tables |
| `render_options_tab` | Calls table (left) + Puts table (right) + BS calculator (optional right panel) |
| `render_futures_tab` | BarChart term structure + tick table for selected contract |
| `render_news_tab` | Scrollable news list with source badges |

---

## 6. Data Flow Diagrams

### Live Binance data
```
Scraper server (100.112.16.115)
  └── binance_monitor.service
        └── Binance WebSocket → Redis pub/sub
              ├── binance:ticks  → ws_rx → handle_websocket_message(TickUpdate)
              │                          → symbol_map[symbol].update(ohlcv)
              └── binance:trades → ws_rx → handle_websocket_message(TradeUpdate)
                                         → recent_trades.push_front(trade)
```

### Historical data fetch
```
User presses [s] on Binance/MERVAL tab
  → trigger_historical_fetch()
      → tokio::spawn {
          db::connect() → PostgreSQL 100.112.16.115:5432
          fetch_ticks()         → DbMessage::Ticks
          fetch_orders()        → DbMessage::Orders
          fetch_binance_ticks() → DbMessage::BinanceTicks
          fetch_binance_trades()→ DbMessage::BinanceTrades
          [first time only]
          fetch_distinct_instruments() → DbMessage::Instruments
          fetch_distinct_dates()       → DbMessage::Dates
          fetch_distinct_binance_symbols() → DbMessage::BinanceSymbols
        }
  → db_rx → handle_db_message() → stores in hist_* fields
```

### Options chain fetch
```
User switches to Options tab (or presses [r])
  → trigger_options_fetch()
      → tokio::spawn {
          [parallel]
          fetch_last_price("M:bm_MERV_GGAL_24hs") → DbMessage::GgalSpot
          fetch_options_chain() {
            1. DISTINCT instruments WHERE GFGC/GFGV AND time > 7d AND bid>0 AND ask>0
            2. Per instrument:
               MAX(bid)/MIN(ask) from last session date  → best bid/ask
               last price from orders table              → last trade
          } → DbMessage::OptionsChain
        }
  → handle_db_message() → ggal_spot, options_chain
  → render_options_tab() → compute IV (bisection) + Greeks per row
```

### News fetch
```
User switches to News tab (or presses [r])
  → trigger_news_fetch()
      → tokio::spawn {
          [sequential]
          POST open.bymadata.com.ar/relevant-facts
            (danger_accept_invalid_certs=true, token header)
            → parse data[].{fecha, emisor, referencia, descarga}
            → DbMessage::News(byma_items)

          GET newsapi.org/v2/everything?q=finance+markets
            (User-Agent: TWS-Terminal/1.0)
            → parse articles[].{publishedAt, source.name, title, url}
            → DbMessage::News(newsapi_items)

          GET feeds.finance.yahoo.com/rss/2.0/headline?s=GGAL,^MERV,YPF,SUPV
            → parse RSS XML items via extract_xml_tag()
            → DbMessage::News(yahoo_items)

          merge + sort by time desc → DbMessage::News(all_items)
        }
```

---

## 7. Key Bindings Reference

### Global
| Key | Action |
|-----|--------|
| `1` | Switch to Binance tab |
| `2` | Switch to MERVAL tab |
| `3` | Switch to Options tab |
| `4` | Switch to Futures tab |
| `5` | Switch to News tab |
| `←` / `→` | Previous / next tab (context-sensitive on Options/Futures) |
| `q` | Quit |

### Binance / MERVAL (Real-Time)
| Key | Action |
|-----|--------|
| `s` | Toggle Real-Time / Historical |
| `↑↓` | Navigate symbol list (Binance) / order list (MERVAL) |
| `o` | Enter new order (MERVAL) |

### Binance / MERVAL (Historical)
| Key | Action |
|-----|--------|
| `f` | Open filter editor (date + instrument dropdown) |
| `Tab` | Switch filter field (Date ↔ Instrument) |
| `↑↓` | Navigate dropdown / scroll table |
| `Enter` | Apply filter + re-fetch |
| `p` | Switch focus between top/bottom panel |
| `s` | Back to Real-Time |

### MERVAL Historical sub-tabs
| Key | Action |
|-----|--------|
| `1` | Stocks category |
| `2` | Options category |
| `3` | Bonds category |
| `4` | Favorites |
| `a` | Add favorite (with autocomplete dropdown) |
| `d` | Delete selected favorite |
| `←→` | Navigate between favorites |

### Options tab
| Key | Action |
|-----|--------|
| `Tab` | Toggle Calls ↔ Puts panel focus |
| `↑↓` | Scroll focused panel |
| `c` | Open/close BS calculator |
| `Enter` | Load chain / compute Greeks (in CalcEdit mode) |
| `r` | Refresh chain |

### Futures tab
| Key | Action |
|-----|--------|
| `←→` | Switch selected contract |
| `↑↓` | Scroll tick table |
| `r` | Refresh |

### News tab
| Key | Action |
|-----|--------|
| `↑↓` | Scroll |
| `Enter` | Open article in browser (`xdg-open`) |
| `r` | Refresh |

---

## 8. External Dependencies

| Crate | Version | Purpose |
|-------|---------|---------|
| `ratatui` | 0.26 | TUI rendering |
| `crossterm` | 0.27 | Terminal raw mode + events |
| `tokio` | 1 (full) | Async runtime |
| `tokio-postgres` | 0.7 | PostgreSQL async client |
| `redis` | 0.24 | Redis pub/sub client |
| `reqwest` | 0.11 (json, native-tls) | HTTP for news APIs |
| `serde` / `serde_json` | 1.0 | JSON serialization |
| `chrono` | 0.4 | Date/time handling |
| `dotenvy` | 0.15 | `.env` file loading |
| `anyhow` | 1.0 | Error handling |

---

## 9. External Services

| Service | Protocol | Auth | Data |
|---------|----------|------|------|
| Redis @ 100.112.16.115:6379 | TCP pub/sub | None | Live Binance klines + trades |
| PostgreSQL @ 100.112.16.115:5432 | TCP | POSTGRES_* env vars | All historical market data |
| ByMA open API | HTTPS (invalid cert) | Static token header | Relevant facts (news) |
| NewsAPI.org | HTTPS | NEWSAPI_KEY env var | Financial news headlines |
| Yahoo Finance RSS | HTTPS | User-Agent header | GGAL/MERVAL/YPF/SUPV news |

---

## 10. Known Limitations

| Issue | Detail |
|-------|--------|
| Options expiry | `parse_expiry_days()` cannot parse expiry from BYMA tickers — uses fixed 30-day assumption |
| GGAL spot | Fetched from `orders` table last trade; may be stale outside market hours |
| Options LOB | `MAX(bid)/MIN(ask)` from last session reconstructs best bid/ask but is not a real-time LOB |
| ByMA documents | PDF download requires authenticated browser session; app opens the ByMA portal page instead |
| Binance live | Only BTCUSDT/USDTARS and other symbols pushed by the scraper server are available |
| Market hours | No data on weekends/holidays; historical queries return last available session |
