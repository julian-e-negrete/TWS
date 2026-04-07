# CHANGELOG

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
