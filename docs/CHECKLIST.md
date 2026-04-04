# AlgoTrading — Next Steps Checklist

_Updated: 2026-03-22_

---

## OPS-01 — Fix GitHub Actions CI (#103) ✅
- [x] `test_cache_set_and_get` and `test_cache_decorator` skip when Redis unreachable
- [x] CI passes with 30% coverage gate

---

## BT-13 — Binance Monitor → Prometheus (#100) ✅
- [x] Add `BINANCE_PRICE`, `BINANCE_RSI`, `BINANCE_VOLUME` gauges to `metrics.py`
- [x] Wire gauges into `AsyncBinanceMonitor._process()`
- [x] Expose metrics HTTP server on `:8003` from `monitor/main.py`
- [x] Add `binance-monitor` port `8003` to `docker-compose.yml`
- [x] Add `algotrading-binance` scrape job to `prometheus.yml`
- [ ] Add Grafana panel for Binance live price + RSI

---

## BT-14 — Binance Live Strategy Testbed (#101)
- [ ] Create `finance/HFT/backtest/binance_live_strategy.py`
  - RSI mean-reversion on BTCUSDT (buy RSI<30, sell RSI>70)
  - Runs as async loop consuming from `AsyncBinanceMonitor.data_map`
  - Pushes simulated trade signals + running P&L to Pushgateway
- [ ] Add Grafana panel: live strategy equity curve

---

## BT-15 — RabbitMQ Market Data Event Bus (#102)
- [ ] Publish kline ticks from `AsyncBinanceMonitor._process()` to exchange `market.ticks`
  - Routing key: `binance.<symbol>`
  - Use `pika` with connection pooling
- [ ] Add consumer in ingestion service that persists messages to `binance_ticks`
- [ ] Document exchange/queue topology in SPEC.md

---

## Grafana Dashboards
- [ ] Add "Binance Live" dashboard
  - BTCUSDT close price (time series)
  - USDTARS close price (time series)
  - RSI gauges per symbol (stat panels)
  - Tick rate (counter rate)
- [ ] Add "Live Strategy" panel (BT-14 signals + P&L)

---

## Backlog
- [ ] Redis cache for market data (TTL 5s) — Phase 2
- [ ] DB indexes on `(instrument, timestamp)` — Phase 2
- [ ] Test coverage → 60% — Phase 2
- [ ] Migrate Binance WebSocket to asyncio fully (already done) ✅
