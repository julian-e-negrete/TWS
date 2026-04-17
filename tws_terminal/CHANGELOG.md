# Changelog

## [2026-04-17]
- [feat] Binance Historical tab: instrument list (↑↓) + Enter loads 1-min OHLCV chart for selected symbol
- [fix] Binance real-time chart slope: `BinanceSymbolData::update()` now accepts `bar_ts`; appends a new price point only when the candle timestamp advances, overwriting the last point in-place within the same candle — keeps x-axis density uniform with historical bars

- [feat] Markets tab auto-refreshes every 60 seconds via `poll_markets` background task (same pattern as US futures 15s poll)
- [feat] Markets tab migrated to yfinance — new `markets` mode in `us_futures/snapshot.py` fetches 29 symbols (indices, futures, FX, LatAm) with last_price and daily change%; removed `fetch_markets_live` DB function; `MarketRow` now derives `serde::Deserialize`

## [2026-04-16]
- [feat] US Futures live data migrated from Redis pub/sub to direct yfinance polling — new `us_futures/snapshot.py` module with `snapshot` and `ohlcv` modes; Rust polls every 15s via subprocess, OHLCV also fetched via yfinance instead of DB
- [refactor] Removed `us_futures:ticks` Redis subscription from `websocket.rs`; removed `fetch_us_futures_ohlcv` and `fetch_us_futures_last_prices` DB functions
- [chore] Added `serde` feature to chrono; added `#[derive(serde::Deserialize)]` to `UsFuturesOhlcv`

## [2026-04-15]
- [fix] Removed `NOT LIKE '%GFG%'` filter from recursive CTE instrument queries so options (GFGC/GFGV) appear in the Options sub-tab of Merval Historical
- [fix] PPI OHLCV chart x-axis bounds corrected from `n` to `n-1` to prevent right-side clipping; date labels now show MM-DD instead of full YYYY-MM-DD
- [fix] `tws_terminal/src/network/mod.rs`: corrected high/low field swap in `MatrizTick` deserialization

## [2026-04-12]
- [feat] PPI OHLCV now auto-detects instrument type (ACCIONES/BONOS/CEDEARS) via `--type AUTO`; bonds like AL30 and CEDEARs now load correctly alongside stocks
- [refactor] Merval Historical tab simplified: removed TimescaleDB price-series query, `MervalTimeRange`, orders panel and `[o]`/`[t]` keybindings — PPI OHLCV chart is now the sole view, triggered directly on Enter
- [refactor] Removed `InputMode::EditingOrder` and `order_input`; `[o]` key binding and new-order workflow fully removed as the app is read-only

## [2026-04-11]
- [chore] Modified `.claude/settings.json`
- [chore] Modified `CLAUDE.md`
- [chore] Modified `finance/HFT/backtest/backtest_results.png`
- [chore] Modified `finance/HFT/backtest/bt12_extended.py`
- [chore] Modified `finance/HFT/backtest/bt_report.py`
- [chore] Modified `finance/HFT/backtest/db/__init__.py`
- [chore] Modified `finance/HFT/backtest/db/cache.py`
- [chore] Modified `finance/HFT/backtest/db/config.py`
- [chore] Modified `finance/HFT/backtest/db/get_cookies.py`
- [chore] Modified `finance/HFT/backtest/db/insert_data.py`
