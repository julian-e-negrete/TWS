# HFT Backtester — Arquitectura, Datos y Estrategias

**Última actualización:** 2026-03-21

---

## Datos Disponibles en PostgreSQL

### Tabla `ticks` (order book snapshots)

| Instrumento | Desde | Hasta | Ticks |
|---|---|---|---|
| M:bm_MERV_AL30_24hs | 2025-08-19 | 2026-03-20 | 3.7M |
| M:bm_MERV_AL30D_24hs | 2025-08-19 | 2026-03-20 | 3.5M |
| M:bm_MERV_PESOS_1D | 2025-08-19 | 2026-03-19 | 2.2M |
| M:bm_MERV_GGALD_24hs | 2025-08-19 | 2026-03-20 | 744K |
| M:rx_DDF_DLR_SEP25 | 2025-09-03 | 2025-09-30 | 140K |
| M:rx_DDF_DLR_OCT25 | 2025-10-01 | 2025-10-31 | 125K |
| M:rx_DDF_DLR_AGO25 | 2025-08-05 | 2025-08-29 | 104K |
| M:rx_DDF_DLR_NOV25 | 2025-11-03 | 2025-11-28 | 65K |

**Columnas:** `time` (UTC), `instrument`, `bid_price`, `ask_price`, `last_price`, `total_volume` (acumulado diario)

**Volumen del período:** `MAX(total_volume) - MIN(total_volume)` — NUNCA usar el valor directo.

### Tabla `orders` (trades ejecutados)

| Instrumento | Desde | Hasta | Órdenes |
|---|---|---|---|
| rx_DDF_DLR_OCT25 | 2025-10-02 | 2025-10-31 | 39K |
| rx_DDF_DLR_SEP25 | 2025-09-03 | 2025-09-30 | 24K |
| rx_DDF_DLR_NOV25 | 2025-11-03 | 2025-11-28 | 18K |
| rx_DDF_DLR_AGO25 | 2025-08-12 | 2025-08-29 | 17K |

**Columnas:** `time` (UTC), `price`, `volume`, `side` (B=buy, S=sell), `instrument`

**Nota:** En `orders`, el instrumento NO tiene prefijo `M:` (ej: `rx_DDF_DLR_OCT25`).
En `ticks`, SÍ tiene prefijo `M:` (ej: `M:rx_DDF_DLR_OCT25`).
`load_market_data()` normaliza esto automáticamente con `.str.replace('M:', '')`.

---

## Arquitectura del Backtester

```
MarketDataBacktester (main.py)          ← Orquestador / API pública
├── load_market_data(trades_df, ob_df)  ← Punto de entrada obligatorio
├── run_backtest(strategy_func)         ← Ejecuta la estrategia
├── generate_report()                   ← Métricas + gráficos
│
├── PositionManager (engine/)           ← Posiciones, entry price, cooldowns
├── OrderExecutor (engine/)             ← Ejecución, comisión 0.5%, límite 2 contratos
├── MetricsCalculator (metrics/)        ← Sharpe, drawdown, win_rate, profit_factor
└── Reporter (metrics/)                 ← Equity curve, gráficos matplotlib
```

### Multiplicadores por instrumento

| Instrumento | Multiplicador | Significado |
|---|---|---|
| `rx_DDF_DLR_*` | 1000 | 1 contrato = 1000 USD nominales |
| `bm_MERV_GFGC*` | 100 | 1 contrato = 100 acciones |

### Firma de una estrategia

```python
def mi_estrategia(
    current_market: OrderBookSnapshot | None,  # snapshot actual del order book
    recent_trades: list[MarketTrade],           # trades recientes (ventana 10min)
    current_position: dict,                     # {instrument: int} posición actual
    current_cash: float                         # efectivo disponible
) -> list[dict]:                                # lista de señales
    ...
    return [{
        'direction': Direction.BUY,   # o Direction.SELL
        'volume': 1,                  # contratos (max 2 para futuros DLR)
        'order_type': OrderType.MARKET,  # o OrderType.LIMIT
        'instrument': 'rx_DDF_DLR_OCT25',
        'price': None,               # solo para LIMIT orders
    }]
```

### Flujo de ejecución de run_backtest()

```
Timeline combinado (ticks + orders, ordenado por timestamp)
  │
  ├── evento tipo 'trade'    → _process_market_trade() → actualiza PnL
  └── evento tipo 'orderbook' → llama strategy_func() → _execute_strategy_order()
                                                       → OrderExecutor.execute()
                                                       → PositionManager.update()
```

---

## Estrategias Implementadas

### 1. `debug_strategy` (baseline — ya en main.py)

**Tipo:** Momentum / trend-following con MA50

**Lógica:**
- Calcula MA50 de los últimos 50 trades
- BUY si `last_price > MA50` AND `volume > 50` AND `desviación > 0.1%`
- SELL si `last_price < MA50` AND `volume > 50` AND `desviación > 0.1%`
- Exit: stop-loss dinámico (vol-adjusted), take-profit 2x, o timeout 5min
- Cooldown: 30s entre trades (futuros DLR)

**Parámetros:**
- `max_risk`: 68% del capital para futuros DLR
- `spread_threshold`: 0.3% máximo spread permitido
- `cooldown`: 30s (DLR), 3min (acciones)

---

## Cómo Correr un Backtest

```bash
cd /home/julian/gitRepositories/AlgoTrading
source venv/bin/activate
PYTHONPATH=. python finance/HFT/backtest/main.py
```

O desde Python:

```python
from finance.HFT.backtest.main import MarketDataBacktester, print_report
from finance.HFT.backtest.db.load_data import load_order_data, load_tick_data

bt = MarketDataBacktester(initial_capital=2_000_000)
trades = load_order_data("2025-10-15")   # fecha con datos OCT25
ticks  = load_tick_data("2025-10-15")
bt.load_market_data(trades, ticks)
bt.run_backtest(bt.debug_strategy)
print_report(bt.generate_report())
```

## Cómo Agregar una Estrategia Nueva

1. Crear `finance/HFT/backtest/strategies/mi_estrategia.py`
2. Implementar la función con la firma estándar (ver arriba)
3. Correr con `bt.run_backtest(mi_estrategia)`
4. El resultado se persiste automáticamente en `backtest_runs`

---

## Métricas de Output

| Métrica | Descripción |
|---|---|
| `total_return_pct` | Retorno total % |
| `annualized_return_pct` | Retorno anualizado % |
| `max_drawdown_pct` | Máximo drawdown % |
| `sharpe_ratio` | Sharpe ratio (anualizado) |
| `win_rate_pct` | % de trades ganadores |
| `profit_factor` | Ganancia bruta / pérdida bruta |
| `expectancy` | Ganancia esperada por trade |
| `num_trades` | Trades cerrados |
| `skipped_trades` | Trades rechazados (capital/límites) |
| `signal_stats` | Desglose de por qué no se generaron señales |
