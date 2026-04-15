# Changelog

## [2026-04-15]
- [chore] Modified `tws_terminal/src/network/mod.rs`

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
