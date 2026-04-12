# CHANGELOG

## [2026-04-12]
- [feat] `PPI/fetch_ohlcv.py`: add `--type AUTO` mode that tries ACCIONES → BONOS → CEDEARS in order, returning the first type with data — enables fetching stocks, bonds, and CEDEARs without specifying the instrument type
- [refactor] `tws_terminal/src/ui/app.rs`: replace Merval Historical tab's TimescaleDB price-series chart with PPI OHLCV as the sole data source; Enter key now directly fetches PPI OHLCV instead of the old DB query
- [refactor] `tws_terminal/src/ui/app.rs`: remove `MervalTimeRange` enum, `trigger_merval_price_series`, `merval_price_series`, `merval_price_labels`, `merval_show_ohlcv`, `merval_chart_error` and the `[o]`/`[t]` key handlers tied to them
- [refactor] `tws_terminal/src/ui/app.rs`: remove `InputMode::EditingOrder`, `order_input` field, `[o]` new-order key binding, and all associated status-bar rendering

## [2026-04-11]
- [fix] `finance/HFT/backtest/formatData/fetch.py`: converted 6 bare module imports (`formatData.*`, `PPI.*`, `opciones.*`, `signals`) to absolute `finance.*` paths; replaced top-level `matplotlib.use('TkAgg')` with `Agg` backend for headless safety
- [fix] `finance/HFT/backtest/livedata/order_book.py`: converted 3 bare module imports (`PPI.opciones.get_maturity`, `opciones.blackscholes`) to absolute `finance.*` paths
- [fix] `finance/HFT/backtest/normalize.py`: replaced top-level `matplotlib.use('TkAgg')` with `Agg` backend for headless import safety
- [chore] `requirements.txt`: added 20 missing packages — `loguru`, `seaborn`, `babel`, `pika`, `prometheus_client`, `sortedcontainers`, `ppi-client`, `lightgbm`, `gymnasium`, `stable-baselines3`, `torch` (CPU), and transitive deps
- [chore] Modified `.claude/settings.json`
- [chore] Modified `CLAUDE.md`
- [chore] Modified `.claude/agents/hft-backtest.md`
- [chore] Modified `ClaudeConversation.txt`
- [chore] Modified `finance/BINANCE/db_config.py`
- [chore] Modified `finance/BINANCE/monitor/alerting.py`
- [chore] Modified `finance/BINANCE/monitor/config.py`
- [chore] Modified `finance/BINANCE/monitor/data_stream.py`
- [chore] Modified `finance/BINANCE/monitor/data_stream_async.py`
- [chore] Modified `finance/BINANCE/monitor/graphing.py`

## 2026-04-07

- [feat] Add 7 TUI tabs: Binance, MERVAL, Options, Futures, News, Markets, US Futures
- [feat] Historical data viewer for Binance and MERVAL with filter + autocomplete dropdowns
- [feat] MERVAL historical instrument browser with price chart (6 time ranges) and order history
- [feat] GGAL options chain (GFGC/GFGV) with IV (bisection) and Greeks (Black-Scholes, pure Rust)
- [feat] BS calculator panel — enter IV manually, auto-fills S/K/T from selected row
- [feat] DLR futures term structure curve (MAR/ABR/MAY, sorted by expiry, mayorist excluded)
- [feat] News tab — ByMA relevant facts + NewsAPI + Yahoo Finance (Global/Argentina/Stocks) in parallel
- [feat] World map tab showing open/closed status for 11 global exchanges in real time
- [feat] US Futures tab — live ES/NQ/YM/CL/GC/SI/ZB via Redis + historical OHLCV chart
- [feat] Subscribe to `matriz:ticks` and `matriz:orders` Redis channels for MERVAL live data
- [feat] Seed Binance price history from DB (3h lookback) on first tick per symbol
- [feat] Replace Sparkline with Chart widget (Braille line, proper axes) for Binance and Futures
- [feat] Parallel DB queries for options chain (2 queries instead of N+1)
- [feat] Anchor price series queries to last data point (not NOW()) for weekend/holiday correctness
- [docs] Add ARCHITECTURE.md, SPEC.md, ROADMAP.md, README.md
