# CHECKLIST DE BACKTESTING — AlgoTrading HFT

**Fecha de Inicio:** 2026-03-21
**Objetivo:** Evaluar todas las estrategias disponibles sobre todos los instrumentos, optimizar parámetros y establecer un sistema de logging continuo.

**Tickets GLPI:** #44–#50, #52–#53, #57–#58 (prefijo [BT-XX] — distintos de los tickets de refactoring #28–#43)

---

## BT-01: Inventario de Datos (#44)

- [x] **Tarea BT-01.1: Auditar tabla `ticks`**
  - [x] Listar todos los instrumentos con rango de fechas y cantidad de ticks
  - [x] Calcular spread promedio por instrumento
  - [x] Identificar instrumentos con datos suficientes (>10 días)

- [x] **Tarea BT-01.2: Auditar tabla `orders`**
  - [x] Listar instrumentos con órdenes ejecutadas
  - [x] Calcular volumen total y precio promedio por instrumento
  - [x] Identificar días con datos completos (ticks + orders)

- [x] **Tarea BT-01.3: Auditar tabla `binance_ticks`**
  - [x] Confirmar símbolos disponibles (BTCUSDT, USDTARS)
  - [x] Verificar rango de fechas y calidad de datos

- [ ] **Tarea BT-01.4: Auditar MySQL `market_data`**
  - [ ] Listar tickers disponibles (requiere acceso MySQL desde servidor)
  - [ ] Documentar rango de fechas por ticker

- [x] **Tarea BT-01.5: Ingesta histórica PPI — últimos 3 meses [BT-08 / #52]**
  - [x] Crear tabla `ppi_ohlcv` en PostgreSQL (ticker, type, date, OHLCV, UNIQUE)
  - [x] Script `finance/HFT/backtest/ppi_historical_ingest.py`
  - [x] Descargar 36 tickers × 60 días = 2,160 filas
    - [x] ACCIONES (15): GGAL, YPFD, BMA, PAMP, TXAR, ALUA, BBAR, CRES, SUPV, TECO2, TGNO4, TGSU2, VALO, MIRG, LOMA
    - [x] BONOS (11): AL30, AL30D, GD30, GD30D, AL35, GD35, AE38, GD41, GD46, AL29, GD29
    - [x] CEDEARS (10): AAPL, MSFT, GOOGL, AMZN, TSLA, NVDA, META, PBR, MELI, GLOB
  - [x] Rango: 2025-12-22 → 2026-03-20 (60 días hábiles)

**Resultado BT-01:** Ver `docs/BT_DATA_INVENTORY.md`

---

## BT-08: Ingesta histórica PPI — últimos 3 meses (#52) ✅

- [x] Tabla `ppi_ohlcv` creada en PostgreSQL
- [x] Script `finance/HFT/backtest/ppi_historical_ingest.py`
- [x] 36 tickers × 60 días = 2,160 filas (ACCIONES, BONOS, CEDEARS)

---

## BT-09: Opciones GGAL — cadena completa + histórico (#53)

- [x] **Tarea BT-09.1: Obtener cadena de opciones GGAL**
  - [x] Buscar todos los tickers GFGC* (calls) y GFGV* (puts) via `search_instrument("GFG", "BYMA", "OPCIONES")`
  - [x] 368 tickers encontrados (192 calls + 176 puts)
  - [x] Parsear strike y vencimiento desde descripción y ticker

- [x] **Tarea BT-09.2: Crear tabla `ppi_options_chain`**
  - [x] Columnas: underlying, ticker, option_type (C/P), strike, expiry, date, OHLCV
  - [x] UNIQUE (ticker, date), índice en (underlying, expiry)

- [x] **Tarea BT-09.3: Descargar OHLCV histórico**
  - [x] 81 opciones con datos en los últimos 90 días
  - [x] 2,014 filas totales
  - [x] Vencimientos activos: 17/04/2026 (49 opciones) y 19/06/2026 (32 opciones)
  - [x] Rango de strikes: 10,126 – 96,801 ARS (calls abr), 43,747 – 96,801 ARS (puts abr)

- [ ] **Tarea BT-09.4: Usar datos en backtesting de opciones**
  - [x] Script `finance/HFT/backtest/options_backtest.py` creado
  - [x] Calcula IV diaria por ticker usando `brentq` (put-call parity para puts)
  - [x] Usa IV del día anterior como sigma (sin look-ahead bias)
  - [x] Filtra strikes fuera de rango S×0.3 – S×3.0
  - [x] Estrategia `options_bs_arb`: BUY si market < BS×0.95, SELL si market > BS×1.05
  - [x] Resultados persistidos en `bt_strategy_runs` (strategy='options_bs_arb')
  - [ ] Análisis de Greeks con `quantlib_option_price()` (BT-11.4)

---

## BT-10: Estrategias sobre PPI OHLCV — Equities/Bonos/CEDEARs (#57)

**Datos:** `ppi_ohlcv` — 36 tickers × 60 días (ACCIONES, BONOS, CEDEARS)
**Nota:** Datos diarios — estrategias de swing/posicional, no HFT. Multiplicador = 1.

- [ ] **Tarea BT-10.1: Crear loader `load_ppi_ohlcv(ticker, from_date, to_date)`**
  - [ ] Leer de `ppi_ohlcv` en PostgreSQL
  - [ ] Retornar DataFrame con columnas: date, open, high, low, close, volume

- [ ] **Tarea BT-10.2: Implementar estrategias sobre OHLCV diario**
  - [ ] MA crossover (MA20 / MA50) — señal de tendencia
  - [ ] RSI mean reversion (RSI < 30 → buy, RSI > 70 → sell)
  - [ ] Bollinger Bands diario (mismo que mean_reversion pero en timeframe diario)

- [ ] **Tarea BT-10.3: Correr backtests sobre todos los tickers**
  - [ ] ACCIONES (15 tickers): GGAL, YPFD, BMA, PAMP, TXAR, ALUA, BBAR, CRES, SUPV, TECO2, TGNO4, TGSU2, VALO, MIRG, LOMA
  - [ ] BONOS (11 tickers): AL30, AL30D, GD30, GD30D, AL35, GD35, AE38, GD41, GD46, AL29, GD29
  - [ ] CEDEARS (10 tickers): AAPL, MSFT, GOOGL, AMZN, TSLA, NVDA, META, PBR, MELI, GLOB
  - [ ] Persistir resultados en `bt_strategy_runs`

- [ ] **Tarea BT-10.4: Tabla comparativa por categoría**
  - [ ] Mejor ticker por categoría (ACCIONES / BONOS / CEDEARS)
  - [ ] Estrategia dominante por categoría

---

## BT-11: Backtesting de Opciones GGAL con Black-Scholes (#58)

**Datos:** `ppi_options_chain` — 81 opciones, vto. 17/04/2026 y 19/06/2026
**Módulo BS:** `finance.PPI.classes.Opciones_class` — `black_scholes_model()`, `black_scholes_put()`, `implied_volatility_call()`
**Script:** `finance/HFT/backtest/options_backtest.py`

- [ ] **Tarea BT-11.1: Calcular volatilidad implícita histórica**
  - [ ] Para cada opción con datos: calcular IV diaria usando `implied_volatility_call()` (calls) y put-call parity (puts)
  - [ ] Subyacente S = precio GGAL de `ppi_ohlcv` en la misma fecha
  - [ ] Tasa libre de riesgo r = 0.40 (tasa BCRA referencia ARS)
  - [ ] Persistir IV en nueva columna o tabla auxiliar

- [ ] **Tarea BT-11.2: Calcular precio teórico BS vs precio de mercado**
  - [ ] Para cada fila de `ppi_options_chain`: calcular BS price con IV histórica
  - [ ] Identificar opciones con mayor mispricing (|BS_price - market_price| / BS_price)
  - [ ] Generar tabla: ticker, strike, expiry, date, market_close, bs_price, iv, mispricing_pct

- [ ] **Tarea BT-11.3: Estrategia de arbitraje de volatilidad**
  - [ ] BUY opción cuando market_price < BS_price × 0.95 (subvaluada)
  - [ ] SELL opción cuando market_price > BS_price × 1.05 (sobrevaluada)
  - [ ] Simular P&L con comisión 0.5% por lado
  - [ ] Persistir resultados en `bt_strategy_runs` con strategy='options_bs_arb'

- [ ] **Tarea BT-11.4: Análisis de Greeks**
  - [ ] Calcular delta, gamma, vega, theta para cada opción usando `quantlib_option_price()`
  - [ ] Identificar opciones con mayor vega (más sensibles a cambios de IV)
  - [ ] Documentar perfil de riesgo de la cadena GGAL

---

## BT-02: Estrategias sobre DLR Futuros (#45) ✅

**Instrumentos:** rx_DDF_DLR_OCT25, SEP25, NOV25
**Capital inicial:** ARS 2,000,000 | **Comisión:** 0.5% por lado

- [x] **Tarea BT-02.1: Correr estrategia `debug` (MA50)** — omitida (baseline sin valor comparativo)
- [x] **Tarea BT-02.2: Correr estrategia `ofi`** — OCT25 (19d), SEP25 (19d), NOV25 (14d)
- [x] **Tarea BT-02.3: Correr estrategia `mean_reversion`** — OCT25 (19d), SEP25 (19d), NOV25 (13d)
- [x] **Tarea BT-02.4: Correr estrategia `vwap`** — OCT25 (19d), SEP25 (18d), NOV25 (13d)
- [x] **Tarea BT-02.5: Tabla comparativa**

| Estrategia | Contrato | Días | Avg Return | Avg Sharpe | Avg Drawdown | Avg Win Rate | Avg PF |
|---|---|---|---|---|---|---|---|
| vwap | NOV25 | 13 | -7.24% | 2.30 | 84.2% | 35.8% | 1.60 |
| vwap | SEP25 | 18 | -7.03% | 2.04 | 85.1% | 24.4% | 0.68 |
| mean_reversion | NOV25 | 13 | -9.94% | 1.85 | 87.7% | 20.5% | 0.19 |
| mean_reversion | SEP25 | 19 | -9.61% | 2.08 | 85.2% | 22.4% | 0.38 |
| ofi | NOV25 | 14 | -13.93% | 2.11 | 85.2% | 31.2% | 0.47 |
| vwap | OCT25 | 19 | -12.64% | 2.15 | 90.6% | 22.6% | 0.49 |
| mean_reversion | OCT25 | 19 | -15.15% | 1.88 | 91.6% | 29.0% | 0.23 |
| ofi | SEP25 | 19 | -15.42% | 2.24 | 91.1% | 22.5% | 0.27 |
| ofi | OCT25 | 19 | -16.97% | 1.33 | 88.6% | 25.2% | 0.45 |

**Conclusiones:**
- **VWAP es la estrategia dominante** en todos los contratos (menor pérdida, mayor Sharpe, único PF > 1 en NOV25)
- Todas las estrategias pierden dinero — la comisión 1% round-trip destruye el P&L en movimientos de 0.1–0.3%
- NOV25 es el contrato más favorable (menor drawdown, mejor PF para VWAP)
- **Próximo paso crítico:** BT-05 optimización de parámetros — reducir frecuencia de trades para capturar movimientos > 1%

---

## BT-03: Estrategias sobre BYMA Equities (#46) ✅

**Instrumentos:** AL30_24hs, GGALD_24hs, PBRD_24hs | **Multiplicador:** 1 | **Comisión:** 0.5%

- [x] **Tarea BT-03.1:** Loader `load_byma_data()` — sintetiza trades desde cambios de mid-price en ticks
- [x] **Tarea BT-03.2:** Estrategias adaptadas con spread_threshold=1.5% (vs 0.3% DLR)
- [x] **Tarea BT-03.3:** Backtests corridos — 10 días por instrumento

| Estrategia | Instrumento | Días | Avg Return | Avg Sharpe | Avg Trades/día |
|---|---|---|---|---|---|
| mean_reversion | AL30_24hs | 9 | -7.95% | -1.46 | 89 |
| mean_reversion | GGALD_24hs | 10 | ~0.00% | -0.78 | 6.5 |
| vwap | AL30_24hs | 1 | -0.13% | -0.08 | 1 |
| vwap | GGALD_24hs | 8 | ~0.00% | -0.13 | 1.8 |

**Conclusiones:** BYMA con datos de ticks sintéticos no es útil para HFT intradiario. AL30 genera señales pero pierde por comisión. GGALD tiene muy pocas señales (spread ~0.5% bloquea la mayoría). El análisis real de BYMA debe hacerse con `ppi_ohlcv` (BT-10).

---

## BT-04: Estrategias sobre Binance (#47) ✅

**Instrumentos:** BTCUSDT, USDTARS | **Multiplicador:** 1 | **Comisión:** 0.1% (Binance)

- [x] **Tarea BT-04.1:** Loader `load_binance_data()` — OHLCV 1min → trades sintéticos (open+close por barra)
- [x] **Tarea BT-04.2:** Estrategias adaptadas con BUFFER=0.2% (crypto) y std=1.5 (mean reversion)
- [x] **Tarea BT-04.3:** Backtests corridos — 7 días por instrumento

| Estrategia | Instrumento | Días | Avg Return | Avg Sharpe | Avg Trades/día |
|---|---|---|---|---|---|
| mean_reversion | BTCUSDT | 7 | -3.92% | -2.78 | 47 |
| mean_reversion | USDTARS | 7 | -0.04% | -2.47 | 30 |
| vwap | BTCUSDT | 4 | -0.05% | -0.09 | 1.5 |
| vwap | USDTARS | 7 | 0 trades | — | 0 |

**Conclusiones:** BTCUSDT con mean_reversion pierde ~4%/día — movimientos de 1-min son demasiado pequeños para cubrir comisión. USDTARS es muy estable (rango diario <1%) — sin señal para mean reversion. VWAP genera muy pocas señales en datos 1-min sintéticos. Binance requiere estrategias de mayor timeframe (15min/1h) para ser viable.

---

## BT-05: Optimización de Parámetros (#48)

**Metodología:** Training set = OCT25, Validation set = NOV25

- [ ] **Tarea BT-05.1: Grid search estrategia OFI**
  - [ ] `OFI_THRESHOLD`: [0.1, 0.2, 0.3, 0.4, 0.5]
  - [ ] `spread_threshold`: [0.001, 0.002, 0.003, 0.005]
  - [ ] `min_trades_required`: [10, 20, 30]
  - [ ] Métrica objetivo: Sharpe ratio en training set

- [ ] **Tarea BT-05.2: Grid search estrategia Mean Reversion**
  - [ ] `window`: [20, 30, 50]
  - [ ] `std_devs`: [1.5, 2.0, 2.5]
  - [ ] `spread_threshold`: [0.001, 0.002, 0.003]

- [ ] **Tarea BT-05.3: Grid search estrategia VWAP**
  - [ ] `BUFFER`: [0.0002, 0.0005, 0.001, 0.002]
  - [ ] `vol_surge_multiplier`: [1.2, 1.5, 2.0]
  - [ ] `min_trades_required`: [10, 15, 20]

- [ ] **Tarea BT-05.4: Validación out-of-sample**
  - [ ] Aplicar mejores parámetros de training a NOV25
  - [ ] Verificar que no hay overfitting (degradación < 30%)
  - [ ] Documentar parámetros óptimos en `.kiro/steering/backtesting.md`

---

## BT-06: Sistema de Logging, Reporte y Monitoreo (#49, #91) ✅ (parcial)

### MON-01: Fix Prometheus + RabbitMQ + Backtest Metrics (#91) ✅

- [x] **MON-01.1:** `monitoring/prometheus.yml` — agregar targets: `algotrading-ingestion:8001`, `rabbitmq-exporter:9419`, `algotrading-backtest:8002`
- [x] **MON-01.2:** `docker-compose.yml` — agregar servicio `rabbitmq-exporter` (kbudde/rabbitmq-exporter:9419)
- [x] **MON-01.3:** `finance/monitoring/metrics.py` — agregar Gauges: `BACKTEST_RETURN`, `BACKTEST_SHARPE`, `BACKTEST_WIN_RATE`, `BACKTEST_PROFIT_FACTOR`
- [x] **MON-01.4:** `run_strategies.py` — `_save_result()` pushea métricas a Prometheus tras cada run
- [x] **MON-01.5:** `monitoring/apply_prometheus_config.sh` — script para aplicar config al snap Prometheus en 100.112.16.115
- [ ] **MON-01.6 (manual):** Ejecutar `apply_prometheus_config.sh` en 100.112.16.115 para activar los nuevos targets
- [ ] **MON-01.7 (manual):** `docker compose up -d rabbitmq rabbitmq-exporter ingestion` para levantar los servicios

**Diagnóstico:** Prometheus en 100.112.16.115 corre como snap (`/var/snap/prometheus/`). El `prometheus.yml` del repo no se aplica automáticamente — hay que copiarlo manualmente o via CI. El target `algotrading-ingestion` estaba DOWN porque el servicio `ingestion` no estaba corriendo.

**PromQL útiles para backtest:**
```
algotrading_backtest_total_return{strategy="vwap"}
algotrading_backtest_sharpe{instrument="rx_DDF_DLR_NOV25"}
algotrading_backtest_win_rate
algotrading_backtest_runs_total
```

**RabbitMQ metrics disponibles tras levantar exporter:**
```
rabbitmq_queue_messages_ready
rabbitmq_connections
rabbitmq_channels
```

---

### BT-06.1–06.3: Reporte y Grafana (#49)

- [ ] **Tarea BT-06.1: Script de reporte `bt_report.py`**
  - [ ] Leer `bt_strategy_runs` y mostrar tabla comparativa
  - [ ] Filtros: `--strategy`, `--instrument`, `--from-date`, `--to-date`

- [ ] **Tarea BT-06.2: Reporte de mejor estrategia por instrumento**
  - [ ] Para cada instrumento, mostrar qué estrategia tuvo mejor Sharpe

- [ ] **Tarea BT-06.3: Dashboard Grafana "Backtest Results"**
  - [ ] Panel: return por estrategia (bar chart)
  - [ ] Panel: win rate por instrumento
  - [ ] Panel: evolución temporal de Sharpe

---

## BT-07: Steering y Documentación (#50)

- [x] **Tarea BT-07.1: Crear `.kiro/steering/backtesting.md`**
  - [x] Reglas invariantes del backtester
  - [x] Firma estándar de estrategia
  - [x] Cómo agregar estrategias nuevas
  - [x] Checklist de validación pre-producción

- [x] **Tarea BT-07.2: Crear `docs/CHECKLIST_BACKTESTING.md`**
  - [x] Este archivo

- [ ] **Tarea BT-07.3: Actualizar `docs/HFT_BACKTEST_GUIDE.md`**
  - [ ] Agregar resultados de backtests corridos
  - [ ] Documentar parámetros óptimos encontrados
  - [ ] Agregar sección "Estrategias descartadas y por qué"

---

## 📊 MÉTRICAS DE ÉXITO

| Métrica | Objetivo | Estado |
|---|---|---|
| Estrategias evaluadas | ≥ 4 | 4 implementadas ✅ |
| Instrumentos evaluados | ≥ 5 | Pendiente |
| Win rate mínimo | > 40% | Pendiente |
| Profit factor mínimo | > 1.5 | Pendiente |
| Max drawdown máximo | < 20% | Pendiente |
| Sharpe ratio mínimo | > 1.0 | Pendiente |
| Resultados en backtest_runs | Todos | Parcial |

---

## 📝 RESULTADOS REGISTRADOS

| Estrategia | Instrumento | Fecha | Return | Sharpe | Win Rate | Profit Factor |
|---|---|---|---|---|---|---|
| ofi | rx_DDF_DLR_OCT25 | 2025-10-16 | -29.5% | 0.79 | 16.7% | 0.31 |
| mean_reversion | rx_DDF_DLR_OCT25 | 2025-10-16 | -18.9% | 2.14 | 13.0% | 0.08 |

**Observación:** Ambas estrategias pierden en este día. La comisión de 1% round-trip es muy alta para movimientos de 0.1-0.3%. Necesita optimización de parámetros (BT-05) o estrategias con mayor captura de movimiento.

---

**Última actualización:** 2026-03-21
