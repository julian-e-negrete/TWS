# Data Inventory

Current state of all data stores as of 2026-04-09.

---

## Redis — `100.112.16.115:6379`

Redis 6.0.16. Currently **0 keys** — no scrapers are actively publishing.

Two pub/sub channels are defined but have 0 subscribers when scrapers are down:

| Channel | Publisher | Consumer |
|---------|-----------|----------|
| `binance:ticks` | `scrapers/BINANCE/run.py` | Rust TUI (`network/websocket.rs`) |
| `binance:trades` | `scrapers/BINANCE/run.py` | Rust TUI |

Message format on `binance:ticks`: JSON `BinanceTick` (symbol, timestamp, open, high, low, close, volume).  
Message format on `binance:trades`: JSON `BinanceTrade` (symbol, time, price, qty, is_buyer_maker, trade_id).

Redis is used only as a real-time fan-out bus — no data is persisted here. When the scraper is running, messages arrive at ~1-minute OHLCV cadence per symbol.

---

## PostgreSQL — `100.112.16.115:5432` / `marketdata`

### Hypertables (TimescaleDB)

These tables use TimescaleDB chunk partitioning. Row counts from `COUNT(*)` are accurate; `pg_class.reltuples` shows 0 for the parent table and should be ignored.

| Table | Rows | Size | Date Range | Notes |
|-------|------|------|------------|-------|
| `ticks` | 14,318,026 | 484 MB | 2025-08-05 → now | 47 chunks |
| `orders` | 572,895 | 116 MB | 2025-08-04 → now | 26 chunks |
| `binance_trades` | 15,193,558 | 2,461 MB | 2026-03-30 → now | 3 chunks; largest table |
| `solana_dex_trades` | 312,771 | 73 MB | 2026-04-01 → now | 3 chunks |
| `binance_ticks` | 122,382 | 19 MB | 2025-08-05 → now | 7 chunks; 1-min OHLCV |
| `us_futures_ticks` | 106,868 | 12 MB | 2026-04-06 → now | 2 chunks |
| `us_futures_ohlcv` | 80,459 | 14 MB | 2026-04-02 → now | 2 chunks |

#### `ticks`

Source: Matriz.eco WebSocket (feeds `M:bm_*` and `M:rx_*` instruments).

```
time          timestamptz  NOT NULL   -- partition key
instrument    text         NOT NULL   -- e.g. "M:bm_MERV_GGAL_24hs"
bid_volume    bigint
bid_price     numeric
ask_price     numeric
ask_volume    bigint
last_price    numeric
total_volume  bigint
low           numeric
high          numeric
prev_close    numeric
```

Top instruments by tick density (last 7 days):

| Instrument | Ticks/7d |
|-----------|---------|
| `M:bm_MERV_AL30_24hs` | 130,180 |
| `M:bm_MERV_PESOS_1D` | 129,743 |
| `M:bm_MERV_AL30D_24hs` | 121,274 |
| `M:rx_DDF_DLR_ABR26` | 55,945 |
| `M:bm_MERV_GGAL_24hs` | 52,820 |
| `M:bm_MERV_GFGC69029A_24hs` | 51,839 |

Instrument prefix key:
- `M:bm_MERV_*` — BYMA equities, options, bonds (settlement `24hs` or `48hs`)
- `M:rx_DDF_DLR_*` — DLR (dollar futures) from MAE, e.g. `DLR_ABR26`

#### `orders`

Source: ByMA REST polling (order book snapshots). Each row is one side of the LOB.

```
time        timestamptz  NOT NULL
price       numeric
volume      bigint
side        char(1)      -- 'B' (bid) or 'S' (ask)
instrument  varchar
```

#### `binance_ticks`

Source: Binance WebSocket 1-minute OHLCV. Active symbols:

`BNBUSDT`, `BTCARS`, `BTCUSDT`, `ETHARS`, `ETHUSDC`, `ETHUSDT`, `SOLUSDT`, `USDCUSDT`, `USDTARS`

```
symbol     varchar      NOT NULL
timestamp  timestamptz  NOT NULL   -- partition key
open/high/low/close  numeric
volume     numeric
```

Sample latest prices (2026-04-09):

| Symbol | Close |
|--------|-------|
| BTCUSDT | 72,261.94 |
| BTCARS | 106,484,651 |
| ETHUSDT | 2,209.89 |
| ETHARS | 3,263,320 |
| USDTARS | 1,473.30 |
| SOLUSDT | 84.32 |

#### `binance_trades`

Source: Binance individual trade stream (tick-by-tick, not OHLCV). Largest table at 2.4 GB.

```
time           timestamptz  NOT NULL
symbol         text         NOT NULL
price          numeric
qty            numeric
is_buyer_maker boolean
trade_id       bigint
```

#### `solana_dex_trades`

Source: Solana DEX aggregator (Orca, Raydium, Meteora). Symbols: `SOL/USDC`, `SOL/USDT`.

```
time         timestamptz  NOT NULL
symbol       text
price        numeric
qty          numeric
is_buyer_maker boolean
source_dex   text         -- 'orca' | 'raydium' | 'meteora'
trade_id     bigint
pair_address text
```

#### `us_futures_ticks`

Source: Yahoo Finance polling. 26 distinct instruments across 4 regions.

```
time         timestamptz  NOT NULL
symbol       text
last_price   numeric
last_volume  bigint
region       text         -- 'usa' | 'europe' | 'asia' | 'brazil' | 'argentina'
asset_class  text         -- 'futures' | 'indices' | 'fx'
```

Symbols by class:

| asset_class | Symbols |
|------------|---------|
| futures | ES=F, NQ=F, YM=F, CL=F, GC=F, SI=F, ZB=F |
| indices | ^GSPC, ^NDX, ^DJI, ^FTSE, ^GDAXI, ^BVSP, ^MERV, ^HSI, ^N225, ^STOXX50E, 000001.SS |
| fx | EURUSD=X, GBPUSD=X, USDJPY=X, USDCNH=X, EURJPY=X, EURGBP=X, ARS=X, BRL=X |

Note: some rows have `NULL` region/asset_class — these are early records before the classification columns were added.

#### `us_futures_ohlcv`

Daily OHLCV for the same symbols as `us_futures_ticks`. Date range 2026-04-02 → now.

```
time        timestamptz  -- partition key
symbol      text
open/high/low/close  numeric
volume      bigint
region      text
asset_class text
```

---

### Regular Tables (non-hypertable)

| Table | Rows | Size | Purpose |
|-------|------|------|---------|
| `ml_training_episodes` | 182,271 | 38 MB | RL/supervised training metrics per episode |
| `bt_strategy_runs` | 16,921 | 3.1 MB | Backtest results per strategy × instrument × date |
| `coto_products` | 6,569 | 1.4 MB | Coto supermarket price scrape |
| `ppi_options_chain` | 2,014 | 920 kB | PPI options OHLCV (GGAL options, historical) |
| `ppi_ohlcv` | 2,160 | 568 kB | PPI equity OHLCV (GGAL etc.) |
| `carrefour_products` | 1,805 | 384 kB | Carrefour supermarket price scrape |
| `signal_stats` | 24 | 24 kB | Signal filter stats per backtest run |
| `bt_param_search` | 93 | 64 kB | Hyperparameter search results |
| `trade_snapshots` | 6 | 24 kB | RL trade snapshots per observation |
| `trade_metrics` | 3 | 24 kB | Aggregate trade metrics per run |
| `backtest_runs` | 3 | 32 kB | Top-level backtest run metadata |
| `cookies` | 3 | 32 kB | Matriz.eco session cookies |
| `signal_reasons` | 0 | 16 kB | (empty — signal reason detail log) |

#### `ml_training_episodes`

Logs from supervised/RL training runs. Latest activity: 2026-04-03 on `GGAL_OPTIONS`.

```
id, ts, instrument, run_date, stage, episode, reward, steps, loss, accuracy, regimes_covered
```

#### `bt_strategy_runs`

15,376 rows covering multiple instruments × strategies. Returns Sharpe, max drawdown, win rate, profit factor. Instruments include: GGAL, AL30, AL30D, AAPL, BTCUSDT_MARGIN_5X, and ~40 others. Strategies: `bollinger`, `macd`, `mean_rev`, `momentum`, `rsi_reversion`, `stochastic`, `atr_breakout`, `ma_crossover`, `ppo_live_*`.

Most recent `ppo_live_*` runs are for `BTCUSDT_MARGIN_5X` (live PPO reinforcement learning agent, last seen 2026-03-30).

#### `ppi_ohlcv` / `ppi_options_chain`

Historical daily OHLCV from Portfolio Personal Inversiones (PPI) API.
- `ppi_ohlcv`: equities (type = `ACCIONES`). Sample: GGAL from 2025-12-22.
- `ppi_options_chain`: GGAL options with strike, expiry, type (C/P), daily OHLCV. Sample: `GFGV4600JU` (put, strike 4600, expiry 2026-06-19).

#### `carrefour_products` / `coto_products`

Argentine supermarket price scrapes. Single snapshot from 2026-03-31. Columns: `product_id`, `sku_id`, `name`, `brand`, `category`, `price`, `list_price`, (`promo` in coto), `available`.

---

## MySQL — `100.112.16.115:3306` / `investments`

Connection is **restricted** — only the scraper server host is allowed to connect. This machine (`haraidasan-thinkpad-e560`) gets `Host not allowed` error. Contents are documented in `DATA_SPEC.md` as historical OHLCV data.

---

## Summary

| Store | Status | Live data? |
|-------|--------|------------|
| Redis | Online, 0 keys | No (scrapers not running) |
| PostgreSQL `ticks` | Online, 14.3M rows | Yes (scrapers active) |
| PostgreSQL `orders` | Online, 573K rows | Yes |
| PostgreSQL `binance_trades` | Online, 2.4 GB | Yes |
| PostgreSQL `binance_ticks` | Online, active | Yes |
| PostgreSQL `solana_dex_trades` | Online, active | Yes |
| PostgreSQL `us_futures_*` | Online, active | Yes |
| MySQL `investments` | Online, inaccessible from this host | Unknown |
