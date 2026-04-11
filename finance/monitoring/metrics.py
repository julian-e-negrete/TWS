"""
Prometheus metrics for AlgoTrading — Tarea 12.1
Exposes /metrics endpoint on port 8001.
Instruments: ingestion requests, DB pool, tick latency, backtest runs.
"""
from prometheus_client import Counter, Histogram, Gauge, start_http_server
from finance.utils.logger import logger

# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

TICKS_INGESTED = Counter(
    "algotrading_ticks_ingested_total",
    "Total ticks ingested",
    ["instrument"],
)

OHLCV_INGESTED = Counter(
    "algotrading_ohlcv_ingested_total",
    "Total OHLCV bars ingested",
    ["ticker"],
)

INGEST_ERRORS = Counter(
    "algotrading_ingest_errors_total",
    "Total ingestion errors",
    ["endpoint"],
)

INGEST_LATENCY = Histogram(
    "algotrading_ingest_latency_seconds",
    "Ingestion endpoint latency",
    ["endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)

DB_POOL_CONNECTIONS = Gauge(
    "algotrading_db_pool_connections",
    "Active DB pool connections",
    ["db"],
)

BACKTEST_RUNS = Counter(
    "algotrading_backtest_runs_total",
    "Total backtest runs",
    ["strategy"],
)

BACKTEST_RETURN = Gauge(
    "algotrading_backtest_total_return",
    "Last backtest total return (decimal)",
    ["strategy", "instrument"],
)

BACKTEST_SHARPE = Gauge(
    "algotrading_backtest_sharpe",
    "Last backtest Sharpe ratio",
    ["strategy", "instrument"],
)

BACKTEST_WIN_RATE = Gauge(
    "algotrading_backtest_win_rate",
    "Last backtest win rate (0-1)",
    ["strategy", "instrument"],
)

BACKTEST_PROFIT_FACTOR = Gauge(
    "algotrading_backtest_profit_factor",
    "Last backtest profit factor",
    ["strategy", "instrument"],
)

WS_CLIENTS = Gauge(
    "algotrading_ws_clients_connected",
    "WebSocket clients currently connected",
)

BINANCE_TICKS = Counter(
    "algotrading_binance_ticks_total",
    "Binance ticks received",
    ["symbol"],
)

BINANCE_PRICE = Gauge(
    "algotrading_binance_close_price",
    "Latest Binance kline close price",
    ["symbol"],
)

BINANCE_RSI = Gauge(
    "algotrading_binance_rsi",
    "Latest Binance RSI(14)",
    ["symbol"],
)

BINANCE_VOLUME = Gauge(
    "algotrading_binance_volume",
    "Latest Binance kline volume",
    ["symbol"],
)


def start_metrics_server(port: int = 8001):
    """Start Prometheus metrics HTTP server."""
    start_http_server(port)
    logger.info("Prometheus metrics server started on :{port}", port=port)


def start_backtest_metrics_server(port: int = 8002):
    """Start dedicated Prometheus metrics server for backtest results."""
    start_http_server(port)
    logger.info("Backtest metrics server started on :{port}", port=port)
