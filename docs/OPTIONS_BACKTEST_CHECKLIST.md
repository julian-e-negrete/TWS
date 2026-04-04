# Options Backtest — Strategy Verification Checklist

## 1. Data Quality

- [ ] **No stale prices** — filter out rows where `volume == 0` (price not updated, illiquid)
- [ ] **Minimum liquidity** — require `volume > 0` on both entry AND exit day
- [ ] **Strike sanity** — only trade options with `0.5 * S <= strike <= 2.0 * S` (deep OTM are unreliable)
- [ ] **Minimum T** — skip options with `T < 7 days` to expiry (gamma risk, wide spreads)
- [ ] **Spot coverage** — every option date must have a corresponding spot price in `ppi_ohlcv`

## 2. Look-Ahead Bias

- [ ] **IV must use only past data** — `sigma` computed from `date < current_date` only ✅ (already done)
- [ ] **Exit price must be next-day market close** — NOT the BS theoretical price
  - Bug: current code uses `exit_p = bs` (theoretical) → inflates win rate artificially
  - Fix: join with next-day `close` from `ppi_options_chain` and use that as exit
- [ ] **Entry price is today's close** — no intraday fill assumption ✅
- [ ] **No future spot used** — `spot_map[date]` is today's spot, not tomorrow's ✅

## 3. Signal Logic

- [ ] **BUY signal**: `market < BS * threshold` — option is underpriced vs model
- [ ] **SELL signal**: `market > BS * threshold` — option is overpriced vs model
- [ ] **Threshold calibration** — 5% band (0.95/1.05) should be validated against bid-ask spread
  - PPI options spreads can be 10-20% → a 5% threshold may fire on noise
  - Consider tightening to 10% band or requiring `volume > median_volume`
- [ ] **No double-entry** — one position per ticker per day max

## 4. P&L Calculation

- [ ] **Commission applied correctly** — 0.5% on entry price + 0.5% on exit price (not on sum)
  - Current: `(entry + exit_p) * COMMISSION` ✅ correct
- [ ] **Multiplier** — GGAL options contract = 100 shares; P&L per contract = `net_pnl * 100`
  - Current code reports per-unit P&L, not per-contract — label clearly
- [ ] **Short P&L sign** — SELL: profit = `entry - exit`; loss = `exit - entry` ✅
- [ ] **No partial fills** — assume full fill at close price (acceptable for daily backtest)

## 5. Win Rate Sanity

- [ ] **Win rate should be < 70%** for a mean-reversion strategy on options
  - If win rate > 80%, suspect look-ahead bias or exit-at-BS-price bug
- [ ] **Check win rate by ticker** — if one ticker drives all wins, investigate data quality
- [ ] **Check win rate by month** — should be consistent, not 100% in one month
- [ ] **Profit factor > 1.0** required for strategy to be viable
- [ ] **Expectancy > 0** required (positive average trade)

## 6. Out-of-Sample Validation

- [ ] **Split data**: train on first 40 days, validate on last 20 days
- [ ] **Metrics must hold in both periods** — win rate and sharpe should not collapse OOS
- [ ] **No parameter fitting on full dataset** — thresholds (0.95/1.05) must be fixed before OOS

## 7. Execution Realism

- [ ] **Slippage** — options have wide spreads; add 1% slippage on top of commission
- [ ] **Liquidity filter** — only trade if `volume > 0` on entry day (already flagged above)
- [ ] **Max positions** — cap at N concurrent open positions to avoid concentration risk
- [ ] **No trading on expiry day** — `T == 0` positions are undefined

## 8. Known Bugs to Fix

| # | Bug | Impact | Fix |
|---|-----|--------|-----|
| 1 | Exit at `bs` (theoretical) instead of next-day market close | **Win rate inflated** | Use `next_close` from options chain |
| 2 | `volume == 0` rows included | Trades on stale/illiquid prices | Filter `volume > 0` on entry |
| 3 | No minimum T filter | Trades near expiry with extreme gamma | Skip `T < 7/365` |
| 4 | 5% threshold may be inside bid-ask spread | False signals | Raise to 10% or add volume filter |
| 5 | P&L reported per unit, not per contract | Misleading totals | Multiply by 100 or document clearly |
