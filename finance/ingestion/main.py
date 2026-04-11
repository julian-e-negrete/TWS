"""
Data Ingestion Microservice — Tarea 10.1
Receives market data via HTTP and persists to PostgreSQL (ticks) and MySQL (market_data).
"""
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from finance.utils.db_pool import get_pg_engine, get_mysql_engine
from finance.utils.logger import logger
from finance.monitoring.metrics import (
    TICKS_INGESTED, OHLCV_INGESTED, INGEST_ERRORS, INGEST_LATENCY,
    start_metrics_server, start_backtest_metrics_server
)
import time

app = FastAPI(title="AlgoTrading Data Ingestion", version="1.0.0")


@app.on_event("startup")
def startup():
    start_metrics_server(port=8001)
    start_backtest_metrics_server(port=8002)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TickIn(BaseModel):
    instrument: str
    time: datetime
    bid_price: float
    ask_price: float
    last_price: float
    bid_volume: int
    ask_volume: int
    total_volume: int
    high: Optional[float] = None
    low: Optional[float] = None
    prev_close: Optional[float] = None


class OHLCVIn(BaseModel):
    ticker: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ingest/tick", status_code=201)
def ingest_tick(tick: TickIn):
    """Insert a single tick into PostgreSQL ticks hypertable."""
    t0 = time.perf_counter()
    try:
        with get_pg_engine().begin() as conn:
            conn.execute(text("""
                INSERT INTO ticks
                    (time, instrument, bid_price, ask_price, last_price,
                     bid_volume, ask_volume, total_volume, high, low, prev_close)
                VALUES
                    (:time, :instrument, :bid_price, :ask_price, :last_price,
                     :bid_volume, :ask_volume, :total_volume, :high, :low, :prev_close)
                ON CONFLICT DO NOTHING
            """), tick.model_dump())
        TICKS_INGESTED.labels(instrument=tick.instrument).inc()
        INGEST_LATENCY.labels(endpoint="/ingest/tick").observe(time.perf_counter() - t0)
        logger.info("Tick ingested: {instrument} @ {time}", instrument=tick.instrument, time=tick.time)
        return {"ingested": 1}
    except Exception as e:
        INGEST_ERRORS.labels(endpoint="/ingest/tick").inc()
        logger.error("Tick ingest failed: {e}", e=e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ingest/ticks/bulk", status_code=201)
def ingest_ticks_bulk(ticks: list[TickIn]):
    """Bulk insert ticks into PostgreSQL (up to 1000 per request)."""
    if len(ticks) > 1000:
        raise HTTPException(status_code=400, detail="Max 1000 ticks per request")
    try:
        rows = [t.model_dump() for t in ticks]
        with get_pg_engine().begin() as conn:
            conn.execute(text("""
                INSERT INTO ticks
                    (time, instrument, bid_price, ask_price, last_price,
                     bid_volume, ask_volume, total_volume, high, low, prev_close)
                VALUES
                    (:time, :instrument, :bid_price, :ask_price, :last_price,
                     :bid_volume, :ask_volume, :total_volume, :high, :low, :prev_close)
                ON CONFLICT DO NOTHING
            """), rows)
        logger.info("Bulk ingested {n} ticks", n=len(rows))
        return {"ingested": len(rows)}
    except Exception as e:
        logger.error("Bulk tick ingest failed: {e}", e=e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ingest/ohlcv", status_code=201)
def ingest_ohlcv(bar: OHLCVIn):
    """Insert OHLCV bar into MySQL market_data table."""
    try:
        with get_mysql_engine().begin() as conn:
            conn.execute(text("""
                INSERT INTO market_data (ticker, timestamp, open, high, low, close)
                VALUES (:ticker, :timestamp, :open, :high, :low, :close)
            """), bar.model_dump(exclude={"volume"}))
        logger.info("OHLCV ingested: {ticker} @ {ts}", ticker=bar.ticker, ts=bar.timestamp)
        return {"ingested": 1}
    except Exception as e:
        logger.error("OHLCV ingest failed: {e}", e=e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ingest/ohlcv/bulk", status_code=201)
def ingest_ohlcv_bulk(bars: list[OHLCVIn]):
    """Bulk insert OHLCV bars into MySQL (up to 5000 per request)."""
    if len(bars) > 5000:
        raise HTTPException(status_code=400, detail="Max 5000 bars per request")
    try:
        rows = [b.model_dump(exclude={"volume"}) for b in bars]
        with get_mysql_engine().begin() as conn:
            conn.execute(text("""
                INSERT INTO market_data (ticker, timestamp, open, high, low, close)
                VALUES (:ticker, :timestamp, :open, :high, :low, :close)
            """), rows)
        logger.info("Bulk ingested {n} OHLCV bars", n=len(rows))
        return {"ingested": len(rows)}
    except Exception as e:
        logger.error("Bulk OHLCV ingest failed: {e}", e=e)
        raise HTTPException(status_code=500, detail=str(e))
