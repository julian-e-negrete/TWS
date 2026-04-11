"""
[BT-08] PPI Historical Data Ingester
Descarga OHLCV diario de los últimos 3 meses via ppi_client y persiste en PostgreSQL.

Uso:
    PYTHONPATH=. python3 -m finance.HFT.backtest.ppi_historical_ingest
    PYTHONPATH=. python3 -m finance.HFT.backtest.ppi_historical_ingest --days 90
    PYTHONPATH=. python3 -m finance.HFT.backtest.ppi_historical_ingest --ticker GGAL
"""
import argparse
from datetime import datetime, timedelta

import pandas as pd
from ppi_client.ppi import PPI
from sqlalchemy import text

from finance.config import settings
from finance.utils.db_pool import get_pg_engine
from finance.utils.logger import logger

# ---------------------------------------------------------------------------
# Tickers a descargar — agrupados por tipo PPI
# ---------------------------------------------------------------------------
TICKERS = {
    "ACCIONES": [
        "GGAL", "YPFD", "BMA", "PAMP", "TXAR", "ALUA", "BBAR", "CRES",
        "SUPV", "TECO2", "TGNO4", "TGSU2", "VALO", "MIRG", "LOMA",
    ],
    "BONOS": [
        "AL30", "AL30D", "GD30", "GD30D", "AL35", "GD35", "AE38",
        "GD41", "GD46", "AL29", "GD29",
    ],
    "CEDEARS": [
        "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META",
        "PBR", "MELI", "GLOB",
    ],
}

# Settlement a usar por tipo
SETTLEMENT = {
    "ACCIONES": "A-48HS",
    "BONOS": "A-48HS",
    "CEDEARS": "A-48HS",
}


def _ensure_table():
    """Create ppi_ohlcv table if not exists."""
    with get_pg_engine().begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ppi_ohlcv (
                id          SERIAL PRIMARY KEY,
                ticker      TEXT NOT NULL,
                type        TEXT NOT NULL,
                date        DATE NOT NULL,
                open        FLOAT,
                high        FLOAT,
                low         FLOAT,
                close       FLOAT,
                volume      FLOAT,
                UNIQUE (ticker, type, date)
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_ppi_ohlcv_ticker_date ON ppi_ohlcv (ticker, date)"
        ))


def _login() -> PPI:
    ppi = PPI(sandbox=False)
    ppi.account.login_api(settings.ppi.public_key, settings.ppi.private_key)
    return ppi


def _fetch(ppi: PPI, ticker: str, type_: str, settlement: str,
           start: datetime, end: datetime) -> pd.DataFrame:
    """Fetch historical OHLCV from PPI API."""
    try:
        data = ppi.marketdata.search(ticker, type_, settlement, start, end)
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        # Normalize column names (PPI returns camelCase)
        col_map = {
            "date": "date", "price": "close", "openingPrice": "open",
            "max": "high", "min": "low", "volume": "volume",
            # alternate names
            "closePrice": "close", "openPrice": "open",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        df["date"] = pd.to_datetime(df["date"]).dt.date
        for col in ["open", "high", "low", "close", "volume"]:
            if col not in df.columns:
                df[col] = None
        return df[["date", "open", "high", "low", "close", "volume"]]
    except Exception as e:
        logger.warning("PPI fetch failed {ticker}/{type_}: {e}", ticker=ticker, type_=type_, e=e)
        return pd.DataFrame()


def _save(ticker: str, type_: str, df: pd.DataFrame) -> int:
    """Upsert rows into ppi_ohlcv. Returns rows inserted."""
    if df.empty:
        return 0
    rows = df.to_dict("records")
    inserted = 0
    with get_pg_engine().begin() as conn:
        for row in rows:
            result = conn.execute(text("""
                INSERT INTO ppi_ohlcv (ticker, type, date, open, high, low, close, volume)
                VALUES (:ticker, :type, :date, :open, :high, :low, :close, :volume)
                ON CONFLICT (ticker, type, date) DO UPDATE SET
                    open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                    close=EXCLUDED.close, volume=EXCLUDED.volume
            """), {"ticker": ticker, "type": type_, **row})
            inserted += result.rowcount
    return inserted


def run(days: int = 90, ticker_filter: str = None):
    _ensure_table()
    ppi = _login()

    end = datetime.today()
    start = end - timedelta(days=days)

    total_rows = 0
    results = []

    for type_, tickers in TICKERS.items():
        settlement = SETTLEMENT[type_]
        for ticker in tickers:
            if ticker_filter and ticker.upper() != ticker_filter.upper():
                continue
            df = _fetch(ppi, ticker, type_, settlement, start, end)
            n = _save(ticker, type_, df)
            total_rows += n
            status = f"{n} rows" if n > 0 else "no data"
            logger.info("{ticker} ({type_}): {status}", ticker=ticker, type_=type_, status=status)
            if not df.empty:
                results.append({
                    "ticker": ticker, "type": type_,
                    "rows": n, "from": df["date"].min(), "to": df["date"].max(),
                    "last_close": df["close"].iloc[-1] if "close" in df.columns else None,
                })

    logger.info("Done — {total} rows persisted to ppi_ohlcv", total=total_rows)

    if results:
        summary = pd.DataFrame(results)
        print("\n" + "="*70)
        print(f"PPI HISTORICAL INGEST — {total_rows} rows across {len(results)} tickers")
        print("="*70)
        print(summary.to_string(index=False))

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--ticker", default=None)
    args = parser.parse_args()
    run(days=args.days, ticker_filter=args.ticker)
