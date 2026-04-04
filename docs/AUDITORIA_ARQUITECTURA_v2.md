# AUDITORÍA DE ARQUITECTURA v3 — AlgoTrading
**Fecha:** 2026-03-23  
**Estado:** Post-sesión BT-10 → BT-19, OPS-01 → OPS-04

---

## 1. MAPA DE MÓDULOS ACTUALES

```
finance/
├── config/
│   └── settings.py             ★ Única fuente de config (pydantic-settings)
│
├── utils/
│   ├── logger.py               ★ Logging estructurado (loguru)
│   ├── db_pool.py              ★ Pool SQLAlchemy (PostgreSQL + MySQL)
│   └── cache.py                Redis cache wrapper (skip si no disponible)
│
├── monitoring/
│   ├── metrics.py              ★ Todas las métricas Prometheus definidas aquí
│   └── db_poller.py            ★ NUEVO — polling DB 244 → gauges :8004 (systemd)
│
├── ingestion/
│   └── main.py                 FastAPI :8000 — endpoints /ingest/tick, /ingest/ohlcv
│
├── HFT/
│   ├── backtest/
│   │   ├── main.py             ★ MarketDataBacktester — orquestador core
│   │   ├── engine/
│   │   │   ├── order_executor.py   Ejecución de órdenes + comisión
│   │   │   └── position_manager.py Gestión de posiciones
│   │   ├── metrics/
│   │   │   ├── calculator.py   Cálculo de métricas (return, sharpe, drawdown)
│   │   │   └── reporter.py     Generación de reportes y gráficos
│   │   ├── strategies/
│   │   │   ├── dlr_strategies.py   OFI, mean_reversion, VWAP (futuros DLR)
│   │   │   └── alt_strategies.py   Estrategias alternativas
│   │   ├── db/                 Capa de datos PostgreSQL (load, insert, cache)
│   │   ├── formatData/         Preprocesamiento LOB, señales, minutos
│   │   ├── livedata/           Captura WebSocket Matriz en tiempo real
│   │   ├── opciones/           Black-Scholes pricing
│   │   ├── ppi_ohlcv_backtest.py   ★ BT-10 — MA/RSI/BB en 36 tickers PPI
│   │   ├── options_backtest.py     ★ BT-11 — opciones GGAL (BS long/short call/put)
│   │   ├── bt12_extended.py        ★ BT-12 — MACD/Stoch/ATR/Momentum + crypto
│   │   ├── live_crypto_runner.py   ★ NUEVO BT-16 — runner live (systemd, cada 60s)
│   │   └── bt_report.py        Reporte consolidado BT-06
│   └── dashboard/
│       ├── calcultions.py      ★ OFI, TFI, spread — reusar, no reimplementar
│       └── load_data.py        Carga ticks/órdenes desde PostgreSQL
│
├── BINANCE/
│   ├── monitor/
│   │   ├── main.py             ★ Entry point — inicia monitor + estrategia live
│   │   ├── data_stream_async.py ★ AsyncBinanceMonitor — WebSocket async
│   │   ├── indicators.py       compute_rsi()
│   │   ├── alerting.py         RSI alerts + email USDTARS > 1350
│   │   └── data_stream.py      (legacy — ThreadedWebsocketManager)
│   ├── strategy/
│   │   └── live_rsi.py         ★ NUEVO BT-14 — RSI mean-reversion live
│   └── mq_publisher.py         ★ NUEVO BT-15 — publica ticks a RabbitMQ
│
├── PPI/
│   └── classes/                ★ Única fuente de verdad para clases PPI
│       ├── account_ppi.py      Auth, órdenes, cuenta
│       ├── market_ppi.py       Datos de mercado, WebSocket streaming
│       ├── Instrument_class.py Sharpe, volatilidad, QuantLib
│       └── Opciones_class.py   Black-Scholes, GARCH, Greeks
│
├── web_scraping/
│   ├── A3/                     MAE REST (dólar MEP, futuros FX)
│   ├── BYMA/                   BYMA REST (CEDEARs, acciones, opciones)
│   └── matriz/                 Matriz WebSocket (HFT futuros ticks)
│
├── messaging/
│   └── rabbitmq.py             Wrapper pika para RabbitMQ
│
├── dashboard/                  Dash dashboard (análisis técnico)
├── dashboard_project/          Django web app (candlestick charts)
├── VaR/                        Value at Risk (yfinance)
├── monteCarlo/                 Simulaciones Monte Carlo
└── MAIL/                       Alertas SMTP

monitoring/
├── prometheus.yml              Scrape config (6 jobs)
└── grafana/provisioning/
    ├── dashboards/
    │   ├── backtest_results.json   ★ Posiciones live + P&L + métricas
    │   ├── ingestion.json          ★ Row counts reales desde DB 244
    │   ├── ohlcv.json              ★ NUEVO — candlestick 1h PostgreSQL
    │   └── rabbitmq.json
    └── datasources/
        └── prometheus.yml

systemd/
├── db-poller.service           ★ NUEVO — polling DB → Prometheus :8004
└── live-crypto-runner.service  ★ NUEVO — estrategias crypto cada 60s
```

---

## 2. ARQUITECTURA DE DATOS

### Flujo principal

```
Scraper Server (192.168.1.244)
  ├── binance_monitor.service  → binance_ticks (PostgreSQL)
  ├── wsclient.service         → ticks (PostgreSQL)
  └── crontab order_side.py    → orders (PostgreSQL)
          │
          │  (consulta remota vía SQLAlchemy)
          ▼
  Este servidor (AlgoTrading)
  ├── db_poller.service        → Prometheus gauges :8004
  ├── live_crypto_runner.service → Pushgateway (estrategias live)
  ├── Prometheus :9090         → scrape :8001/:8002/:8004/:9091
  └── Grafana :3000            → dashboards
```

### Bases de datos

| DB | Host | Tablas clave | Acceso |
|----|------|-------------|--------|
| PostgreSQL `marketdata` | `100.112.16.115:5432` | `ticks`, `orders`, `binance_ticks`, `bt_strategy_runs` | `POSTGRES_*` en `.env` |
| MySQL `investments` | `100.112.16.115:3306` | `market_data` (OHLCV) | `DB_*` en `.env` |

---

## 3. MÉTRICAS PROMETHEUS

### Definidas en `finance/monitoring/metrics.py`

| Métrica | Tipo | Labels | Fuente |
|---------|------|--------|--------|
| `algotrading_ticks_ingested_total` | Counter | `instrument` | ingestion :8001 |
| `algotrading_ingest_errors_total` | Counter | `endpoint` | ingestion :8001 |
| `algotrading_ingest_latency_seconds` | Histogram | `endpoint` | ingestion :8001 |
| `algotrading_backtest_total_return` | Gauge | `strategy`, `instrument` | Pushgateway |
| `algotrading_backtest_sharpe` | Gauge | `strategy`, `instrument` | Pushgateway |
| `algotrading_backtest_win_rate` | Gauge | `strategy`, `instrument` | Pushgateway |
| `algotrading_backtest_profit_factor` | Gauge | `strategy`, `instrument` | Pushgateway |
| `algotrading_live_position` | Gauge | `strategy`, `instrument` | Pushgateway |
| `algotrading_live_entry_price` | Gauge | `strategy`, `instrument` | Pushgateway |
| `algotrading_live_unrealized_pnl` | Gauge | `strategy`, `instrument` | Pushgateway |
| `algotrading_binance_close_price` | Gauge | `symbol` | :8003 (local monitor) |
| `algotrading_binance_rsi` | Gauge | `symbol` | :8003 (local monitor) |
| `algotrading_binance_volume` | Gauge | `symbol` | :8003 (local monitor) |

### Definidas en `finance/monitoring/db_poller.py`

| Métrica | Tipo | Labels | Fuente |
|---------|------|--------|--------|
| `algotrading_db_ticks_total` | Gauge | `instrument` | DB poller :8004 |
| `algotrading_db_orders_total` | Gauge | `instrument` | DB poller :8004 |
| `algotrading_db_binance_ticks_total` | Gauge | `symbol` | DB poller :8004 |
| `algotrading_db_ticks_last_5m` | Gauge | `instrument` | DB poller :8004 |
| `algotrading_db_binance_last_5m` | Gauge | `symbol` | DB poller :8004 |
| `algotrading_binance_ohlcv_open/high/low/close/volume` | Gauge | `symbol` | DB poller :8004 |

---

## 4. ESTRATEGIAS IMPLEMENTADAS

### BT-10 — ppi_ohlcv_backtest.py (36 tickers, OHLCV diario)

| Estrategia | Lógica |
|-----------|--------|
| `ma_crossover` | MA50 > MA200 → BUY, MA50 < MA200 → SELL |
| `rsi` | RSI < 30 → BUY, RSI > 70 → SELL |
| `bollinger` | Precio < lower band → BUY, > upper band → SELL |

### BT-11 — options_backtest.py (GGAL opciones)

| Estrategia | Lógica |
|-----------|--------|
| `bs_long_call` | Compra call cuando precio < BS teórico |
| `bs_short_call` | Vende call cuando precio > BS teórico |
| `bs_long_put` | Compra put cuando precio < BS teórico |
| `bs_short_put` | Vende put cuando precio > BS teórico |

### BT-12 — bt12_extended.py

**Part A — ppi_ohlcv (36 tickers):**

| Estrategia | Lógica |
|-----------|--------|
| `macd` | MACD(12,26,9) crossover |
| `stochastic` | Stoch(14,3): <20 BUY, >80 SELL |
| `atr_breakout` | ATR(14): close > prev_high+ATR BUY |
| `momentum` | ROC 10d: >5% BUY, <-5% SELL |
| `mean_rev` | Z-score(20): z<-1.5 BUY, z>1.5 SELL |

**Part B — binance_ticks (BTCUSDT, USDTARS, 1h bars):**

| Estrategia | Lógica | Posición actual |
|-----------|--------|----------------|
| `crypto_rsi` | RSI(14): <30 BUY, >70 SELL | BTCUSDT: LONG |
| `crypto_macd` | MACD(12,26,9) crossover | BTCUSDT: FLAT |
| `crypto_bb` | BB(20,2): below lower BUY | BTCUSDT: FLAT |
| `crypto_momentum` | ROC 6h: >2% BUY, <-2% SELL | BTCUSDT: SHORT |

### BT-14 — live_rsi.py (BTCUSDT, tiempo real)
RSI mean-reversion sobre `data_map` del monitor async. Pushea señales a Pushgateway.

---

## 5. SERVICIOS EN EJECUCIÓN

| Servicio | Tipo | Puerto | Estado |
|---------|------|--------|--------|
| `db-poller` | systemd | :8004 | ✅ activo |
| `live-crypto-runner` | systemd | — | ✅ activo |
| `ingestion` | Docker | :8000/:8001/:8002 | ✅ up |
| `prometheus` | Docker | :9090 | ✅ up |
| `grafana` | Docker | :3000 | ✅ up |
| `pushgateway` | Docker | :9091 | ✅ up |
| `rabbitmq` | Docker | :5672/:15672 | ✅ up |
| `rabbitmq-exporter` | Docker | :9419 | ✅ up |
| `binance-monitor` | Docker | :8003 (no expuesto) | ⚠️ up, no scrapeado |

---

## 6. GRAFANA DATASOURCES

| Nombre | Tipo | UID | Target |
|--------|------|-----|--------|
| Prometheus | prometheus | `PBFA97CFB590B2093` | `localhost:9090` |
| PostgreSQL-marketdata | postgres | `afgtyrtr931mob` | `100.112.16.115:5432/marketdata` |

---

## 7. GRAFANA DASHBOARDS

| Dashboard | UID | Datasource | Paneles clave |
|-----------|-----|------------|--------------|
| Backtest Results | `algotrading-backtest` | Prometheus | Total return, Sharpe, Win rate, Posición live, Unrealized P&L |
| Ingestion | `algotrading-ingestion` | Prometheus | Row counts DB 244, ticks last 5m, binance ticks |
| OHLCV | `algotrading-ohlcv` | PostgreSQL | Candlestick 1h BTCUSDT + USDTARS |
| RabbitMQ | `algotrading-rabbitmq` | Prometheus | Queue metrics |

---

## 8. REGLAS INVARIANTES

1. **No hardcodear credenciales** — siempre `finance.config.settings`
2. **No duplicar clases PPI** — `finance/PPI/classes/` es la única fuente
3. **No reimplementar indicadores** — reusar `finance/HFT/dashboard/calcultions.py`
4. **Datos de backtest** entran via `MarketDataBacktester.load_market_data()`
5. **Resultados de backtest** persisten en `bt_strategy_runs` + Pushgateway
6. **`total_return`** siempre es fracción decimal (no ARS bruto)
7. **`total_volume` en `ticks`** es acumulado diario — volumen por período = `MAX - MIN`
8. **Timestamps** en UTC en DB; convertir con `AT TIME ZONE 'America/Argentina/Buenos_Aires'`
9. **Instrumento activo de futuros** siempre consultado dinámicamente, nunca hardcodeado
10. **Todo ticket GLPI** abierto ANTES de empezar cualquier tarea

---

## 9. ISSUES CONOCIDOS

| Issue | Impacto | Prioridad |
|-------|---------|-----------|
| `algotrading-binance` Prometheus target down | Bajo — datos vienen de DB poller | Baja |
| CHANGELOG tiene headers `[2026-03-22]` duplicados | Cosmético | Baja |
| `finance/PPI/` raíz tiene duplicados legacy (`account_ppi.py`, etc.) | Confusión de imports | Media |
| `finance/UbuntuServer/` — código legacy del servidor 244 en este repo | Confusión | Baja |
| `finance/BINANCE/strategy/live_rsi.py` — duplica lógica de `bt12_extended.py` | Deuda técnica | Media |

---

## 10. PENDIENTE (ROADMAP)

| Tarea | Prioridad | Esfuerzo |
|-------|-----------|---------|
| Redis cache para datos de mercado (TTL 5s) | Alta | 8h |
| Indexes DB en `(instrument, timestamp)` | Media | 2h |
| Test coverage → 60% | Media | 12h |
| Limpiar duplicados legacy en `finance/PPI/` raíz | Media | 2h |
| Unificar `live_rsi.py` con estrategias de `bt12_extended.py` | Media | 4h |
| RabbitMQ consumer en ingestion service (BT-15 completo) | Media | 4h |

---

**Última actualización:** 2026-03-23
