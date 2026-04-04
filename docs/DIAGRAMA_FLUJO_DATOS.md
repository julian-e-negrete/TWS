# DIAGRAMA DE FLUJO DE DATOS - AlgoTrading

## FLUJO COMPLETO DEL SISTEMA

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           FUENTES DE DATOS EXTERNAS                         │
└─────────────────────────────────────────────────────────────────────────────┘
         │                    │                    │                    │
         │                    │                    │                    │
    ┌────▼────┐          ┌───▼────┐          ┌───▼────┐          ┌───▼────┐
    │ Binance │          │  PPI   │          │  BYMA  │          │   A3   │
    │   API   │          │  API   │          │  Web   │          │  Web   │
    └────┬────┘          └───┬────┘          └───┬────┘          └───┬────┘
         │                    │                    │                    │
         │ WebSocket          │ REST API           │ Scraping           │ Scraping
         │                    │                    │                    │
┌────────▼────────────────────▼────────────────────▼────────────────────▼─────┐
│                        CAPA DE ADQUISICIÓN DE DATOS                         │
│                                                                              │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐          │
│  │ BINANCE/monitor/ │  │  PPI/classes/    │  │ web_scraping/    │          │
│  │ - data_stream.py │  │ - market_ppi.py  │  │ - A3/dolar.py    │          │
│  │ - indicators.py  │  │ - account_ppi.py │  │ - BYMA/*.py      │          │
│  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘          │
│           │                     │                      │                     │
│           └─────────────────────┼──────────────────────┘                     │
│                                 │                                            │
└─────────────────────────────────┼────────────────────────────────────────────┘
                                  │
                                  │ Raw Data (JSON, DataFrame)
                                  │
┌─────────────────────────────────▼────────────────────────────────────────────┐
│                         CAPA DE NORMALIZACIÓN                                │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────┐           │
│  │ HFT/backtest/formatData/                                     │           │
│  │ - fetch.py          → Obtiene datos históricos              │           │
│  │ - LOB.py            → Procesa order book                    │           │
│  │ - minutes_ticker.py → Agrega datos por minuto               │           │
│  │ - analyzer.py       → Calcula métricas                      │           │
│  └────────────────────────────┬─────────────────────────────────┘           │
│                               │                                              │
└───────────────────────────────┼──────────────────────────────────────────────┘
                                │
                                │ Normalized Data (pandas.DataFrame)
                                │
┌───────────────────────────────▼──────────────────────────────────────────────┐
│                        CAPA DE PERSISTENCIA                                  │
│                                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │    MySQL     │  │  PostgreSQL  │  │    SQLite    │  │    Redis     │   │
│  │              │  │              │  │              │  │   (Cache)    │   │
│  │ - market_data│  │ - hft_data   │  │ - django_db  │  │              │   │
│  │ - trades     │  │ - backtest   │  │              │  │              │   │
│  │ - orderbook  │  │ - results    │  │              │  │              │   │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘   │
│         │                  │                  │                  │           │
│         └──────────────────┼──────────────────┼──────────────────┘           │
│                            │                  │                              │
└────────────────────────────┼──────────────────┼──────────────────────────────┘
                             │                  │
                             │ SQL Queries      │ ORM Queries
                             │                  │
┌────────────────────────────▼──────────────────▼──────────────────────────────┐
│                      CAPA DE PROCESAMIENTO Y ANÁLISIS                        │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │ HFT/backtest/main.py                                            │        │
│  │ ┌─────────────────────────────────────────────────────────────┐ │        │
│  │ │ class MarketDataBacktester:                                 │ │        │
│  │ │   - load_market_data()      → Carga datos                  │ │        │
│  │ │   - run_backtest()          → Ejecuta simulación           │ │        │
│  │ │   - calculate_metrics()     → Calcula métricas             │ │        │
│  │ │   - generate_report()       → Genera reporte               │ │        │
│  │ └─────────────────────────────────────────────────────────────┘ │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │ PPI/OPCIONES/                                                   │        │
│  │ - call_options_pricing.py   → Black-Scholes                    │        │
│  │ - calculo_volatilidad.py    → Volatilidad implícita            │        │
│  │ - pricing_opcion.py         → Pricing completo                 │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │ MISC/                                                           │        │
│  │ - sharpeRatio.py            → Sharpe Ratio                     │        │
│  │ - day_volatility.py         → Volatilidad                      │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │ VaR/                                                            │        │
│  │ - 1H.py, 5m.py              → Value at Risk                    │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────┐        │
│  │ monteCarlo/                                                     │        │
│  │ - martingale.py             → Simulaciones Monte Carlo         │        │
│  │ - survivalRate.py           → Análisis de supervivencia        │        │
│  └─────────────────────────────────────────────────────────────────┘        │
│                                                                              │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                                   │ Processed Data, Metrics, Signals
                                   │
┌──────────────────────────────────▼───────────────────────────────────────────┐
│                        CAPA DE VISUALIZACIÓN                                 │
│                                                                              │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐          │
│  │  Dash Dashboard  │  │  Django Web App  │  │     Streamlit    │          │
│  ├──────────────────┤  ├──────────────────┤  ├──────────────────┤          │
│  │ dashboard/       │  │ dashboard_project│  │ streamlit/       │          │
│  │ - main.py        │  │ - views.py       │  │ - main.py        │          │
│  │ - classes/       │  │ - urls.py        │  │ - fetcher.py     │          │
│  │                  │  │ - templates/     │  │                  │          │
│  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘          │
│           │                     │                      │                     │
│           └─────────────────────┼──────────────────────┘                     │
│                                 │                                            │
└─────────────────────────────────┼────────────────────────────────────────────┘
                                  │
                                  │ HTTP/WebSocket
                                  │
                            ┌─────▼─────┐
                            │  Browser  │
                            │   (User)  │
                            └───────────┘
```

---

## FLUJO DETALLADO: BACKTESTING

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         INICIO: Backtesting HFT                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ python HFT/backtest/main.py  │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ MarketDataBacktester.__init__│
                    │ - initial_capital = 2M       │
                    │ - position = {}              │
                    │ - strategy_trades = []       │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ db.load_data.load_tick_data()│
                    │ db.load_data.load_order_data()│
                    └──────────────┬───────────────┘
                                   │
                                   ▼ DataFrame
                    ┌──────────────────────────────┐
                    │ formatData.LOB.process_data()│
                    │ - Normaliza order book       │
                    │ - Calcula bid/ask spread     │
                    └──────────────┬───────────────┘
                                   │
                                   ▼ Normalized DataFrame
                    ┌──────────────────────────────┐
                    │ load_market_data()           │
                    │ - Crea MarketTrade objects   │
                    │ - Crea OrderBookSnapshot     │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ run_backtest()               │
                    │ ┌──────────────────────────┐ │
                    │ │ for each timestamp:      │ │
                    │ │   - update_order_book()  │ │
                    │ │   - process_trade()      │ │
                    │ │   - check_signals()      │ │
                    │ │   - execute_strategy()   │ │
                    │ │   - update_positions()   │ │
                    │ │   - calculate_pnl()      │ │
                    │ └──────────────────────────┘ │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ calculate_metrics()          │
                    │ - Total PnL                  │
                    │ - Sharpe Ratio               │
                    │ - Max Drawdown               │
                    │ - Win Rate                   │
                    │ - Avg Trade Duration         │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ print_report()               │
                    │ - Console output             │
                    │ - matplotlib charts          │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ db.insert_data.insert_data() │
                    │ - Guarda resultados en DB    │
                    └──────────────────────────────┘
```

---

## FLUJO DETALLADO: MONITOREO EN TIEMPO REAL (BINANCE)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    INICIO: Monitor de Binance                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ python BINANCE/monitor/main.py│
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ BinanceMonitor.__init__()    │
                    │ - symbols = [BTCUSDT, ...]   │
                    │ - data_map = {}              │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ ThreadedWebsocketManager     │
                    │ - start()                    │
                    │ - start_kline_socket()       │
                    └──────────────┬───────────────┘
                                   │
                                   ▼ WebSocket Stream
                    ┌──────────────────────────────┐
                    │ process_message(msg)         │
                    │ ┌──────────────────────────┐ │
                    │ │ Extrae kline data:       │ │
                    │ │ - timestamp              │ │
                    │ │ - open, high, low, close │ │
                    │ │ - volume                 │ │
                    │ └──────────────────────────┘ │
                    └──────────────┬───────────────┘
                                   │
                                   ▼ DataFrame
                    ┌──────────────────────────────┐
                    │ indicators.compute_rsi()     │
                    │ - Calcula RSI(14)            │
                    └──────────────┬───────────────┘
                                   │
                                   ▼ DataFrame + RSI
                    ┌──────────────────────────────┐
                    │ alerting.evaluate_alerts()   │
                    │ ┌──────────────────────────┐ │
                    │ │ if RSI > 70:             │ │
                    │ │   → OVERBOUGHT alert     │ │
                    │ │ if RSI < 30:             │ │
                    │ │   → OVERSOLD alert       │ │
                    │ └──────────────────────────┘ │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ graphing.update_graph()      │
                    │ - Actualiza gráfico en vivo  │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ MySQL.insert()               │
                    │ - Persiste datos             │
                    └──────────────────────────────┘
                                   │
                                   │ Loop infinito
                                   └──────────┐
                                              │
                                              ▼
                                   ┌──────────────────┐
                                   │ Espera siguiente │
                                   │ mensaje WebSocket│
                                   └──────────────────┘
```

---

## FLUJO DETALLADO: WEB SCRAPING → DASHBOARD

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    INICIO: Web Scraping + Dashboard                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ python web_scraping/A3/dolar.py│
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ aiohttp.ClientSession()      │
                    │ - GET api.marketdata.mae.com │
                    └──────────────┬───────────────┘
                                   │
                                   ▼ JSON Response
                    ┌──────────────────────────────┐
                    │ pd.DataFrame(data)           │
                    │ - ticker, segmento, ultimo   │
                    │ - minimo, maximo, variacion  │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ Filter: ticker == 'USMEP'    │
                    │ Filter: segmento == 'Minorista'│
                    └──────────────┬───────────────┘
                                   │
                                   ▼ Filtered DataFrame
                    ┌──────────────────────────────┐
                    │ SQLAlchemy.engine.connect()  │
                    │ df.to_sql('market_data')     │
                    └──────────────┬───────────────┘
                                   │
                                   ▼ Stored in MySQL
┌──────────────────────────────────┴───────────────────────────────────────────┐
│                         DASHBOARD RENDERING                                  │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ python dashboard/main.py     │
                    │ (Dash app)                   │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ @app.callback()              │
                    │ def update_graph():          │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ Market_data.get_instruments()│
                    │ - Consulta PPI API           │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ SQLAlchemy.query()           │
                    │ SELECT * FROM market_data    │
                    │ WHERE ticker = 'GGAL'        │
                    │ ORDER BY timestamp DESC      │
                    │ LIMIT 100                    │
                    └──────────────┬───────────────┘
                                   │
                                   ▼ DataFrame
                    ┌──────────────────────────────┐
                    │ plotly.graph_objs.Candlestick│
                    │ - x = timestamp              │
                    │ - open, high, low, close     │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ dcc.Graph(figure=fig)        │
                    │ - Renderiza en browser       │
                    └──────────────────────────────┘
```

---

## DEPENDENCIAS ENTRE MÓDULOS

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         GRAFO DE DEPENDENCIAS                               │
└─────────────────────────────────────────────────────────────────────────────┘

HFT/backtest/main.py
    ├─→ db.load_data
    │   └─→ mysql-connector-python
    ├─→ db.insert_data
    ├─→ formatData.fetch
    │   ├─→ ppi_client
    │   └─→ QuantLib
    ├─→ formatData.LOB
    └─→ formatData.minutes_ticker

BINANCE/monitor/data_stream.py
    ├─→ python-binance
    ├─→ indicators
    │   └─→ ta
    ├─→ alerting
    └─→ graphing
        └─→ matplotlib

dashboard/classes/market_ppi.py
    ├─→ ppi_client
    └─→ pandas

dashboard/classes/Opciones_class.py
    ├─→ ppi_client
    ├─→ QuantLib
    ├─→ scipy
    └─→ arch

web_scraping/A3/dolar.py
    ├─→ aiohttp
    └─→ pandas

PPI/account_ppi.py
    └─→ ppi_client

VaR/1H.py
    ├─→ pandas
    └─→ numpy

monteCarlo/martingale.py
    ├─→ numpy
    └─→ matplotlib
```

---

## PUNTOS DE INTEGRACIÓN CRÍTICOS

### 1. Base de Datos
**Ubicación:** `finance/db/config.py`  
**Usado por:** HFT, BINANCE, dashboard, web_scraping  
**Tipo:** MySQL/PostgreSQL  
**⚠️ Problema:** Configuración duplicada en 4+ archivos

### 2. PPI Client
**Ubicación:** `finance/PPI/classes/`  
**Usado por:** HFT, dashboard, PPI/OPCIONES  
**Tipo:** SDK externo (ppi_client)  
**⚠️ Problema:** Código duplicado en 3 ubicaciones

### 3. WebSocket Managers
**Ubicación:** `BINANCE/monitor/data_stream.py`, `web_scraping/A3/web_socket/`  
**Tipo:** ThreadedWebsocketManager, websockets  
**⚠️ Problema:** Implementaciones diferentes para casos similares

### 4. Dashboards
**Ubicación:** `dashboard/`, `dashboard_project/`, `streamlit/`  
**Tipo:** Dash, Django, Streamlit  
**⚠️ Problema:** 3 frameworks en paralelo sin estandarización

---

**Última actualización:** 2026-03-13
