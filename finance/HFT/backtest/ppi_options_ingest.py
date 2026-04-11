"""
[BT-09] GGAL Options Chain Ingester
Descarga todos los tickers de opciones GGAL (GFGC* calls, GFGV* puts) y su OHLCV histórico.

Uso:
    PYTHONPATH=. python3 -m finance.HFT.backtest.ppi_options_ingest
    PYTHONPATH=. python3 -m finance.HFT.backtest.ppi_options_ingest --days 90
    PYTHONPATH=. python3 -m finance.HFT.backtest.ppi_options_ingest --underlying GGAL
"""
import argparse
import re
from datetime import datetime, timedelta

import pandas as pd
from ppi_client.ppi import PPI
from sqlalchemy import text

from finance.config import settings
from finance.utils.db_pool import get_pg_engine
from finance.utils.logger import logger

UNDERLYING = "GGAL"
_SEARCH_PREFIX = "GFG"   # PPI search key for GGAL options
# Matches: "AR$ 10151.00 Vto. 17/04/2026" or "AR$ 6.500,00 Vto. ..."
_PATTERN = re.compile(r"AR\$\s*([\d.,]+)\s*Vto\.\s*(\d{2}/\d{2}/\d{4})")


def _ensure_table():
    with get_pg_engine().begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ppi_options_chain (
                id          SERIAL PRIMARY KEY,
                underlying  TEXT NOT NULL,
                ticker      TEXT NOT NULL,
                option_type TEXT NOT NULL,   -- 'C' call / 'P' put
                strike      FLOAT,
                expiry      DATE,
                date        DATE NOT NULL,
                open        FLOAT,
                high        FLOAT,
                low         FLOAT,
                close       FLOAT,
                volume      FLOAT,
                UNIQUE (ticker, date)
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_ppi_opt_underlying ON ppi_options_chain (underlying, expiry)"
        ))


def _login() -> PPI:
    ppi = PPI(sandbox=False)
    ppi.account.login_api(settings.ppi.public_key, settings.ppi.private_key)
    return ppi


def _parse_strike_expiry(description: str, ticker: str = ""):
    """Extract (strike, expiry) from PPI description or ticker."""
    m = _PATTERN.search(description)
    if m:
        strike_str = m.group(1).replace(".", "").replace(",", ".")
        try:
            return float(strike_str), datetime.strptime(m.group(2), "%d/%m/%Y").date()
        except ValueError:
            pass
    # Fallback: parse from ticker e.g. GFGC10151A → strike=10151, month=A(Apr)
    _MONTH_MAP = {"A": 4, "J": 6, "O": 10, "D": 12, "F": 2, "M": 3, "N": 11}
    m2 = re.match(r"GFG[CV](\d+)([A-Z])$", ticker.upper())
    if m2:
        try:
            strike = float(m2.group(1))
            month = _MONTH_MAP.get(m2.group(2))
            if month:
                year = datetime.today().year if month >= datetime.today().month else datetime.today().year + 1
                from calendar import monthcalendar
                fridays = [w[4] for w in monthcalendar(year, month) if w[4]]
                expiry = datetime(year, month, fridays[2]).date()
                return strike, expiry
        except Exception:
            pass
    return None, None


def _fetch_chain(ppi: PPI, underlying: str) -> list[dict]:
    """Get all option tickers for the underlying (GGAL → search 'GFG')."""
    raw = ppi.marketdata.search_instrument(_SEARCH_PREFIX, "", "BYMA", "OPCIONES")
    options = []
    for item in raw:
        ticker = item.get("ticker", "").strip()
        if not ticker:
            continue
        option_type = "C" if ticker.upper().startswith("GFGC") else "P" if ticker.upper().startswith("GFGV") else None
        if option_type is None:
            continue
        strike, expiry = _parse_strike_expiry(item.get("description", ""), ticker)
        options.append({
            "ticker": ticker,
            "option_type": option_type,
            "strike": strike,
            "expiry": expiry,
            "description": item.get("description", ""),
        })
    logger.info("Found {n} option tickers for {u}", n=len(options), u=underlying)
    return options


def _fetch_ohlcv(ppi: PPI, ticker: str, start: datetime, end: datetime) -> pd.DataFrame:
    try:
        data = ppi.marketdata.search(ticker, "OPCIONES", "A-24HS", start, end)
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        col_map = {
            "date": "date", "price": "close", "openingPrice": "open",
            "max": "high", "min": "low", "volume": "volume",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        df["date"] = pd.to_datetime(df["date"]).dt.date
        for col in ["open", "high", "low", "close", "volume"]:
            if col not in df.columns:
                df[col] = None
        return df[["date", "open", "high", "low", "close", "volume"]]
    except Exception as e:
        logger.debug("No data for {ticker}: {e}", ticker=ticker, e=e)
        return pd.DataFrame()


def _save(underlying: str, opt: dict, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    rows = df.to_dict("records")
    inserted = 0
    with get_pg_engine().begin() as conn:
        for row in rows:
            r = conn.execute(text("""
                INSERT INTO ppi_options_chain
                    (underlying, ticker, option_type, strike, expiry,
                     date, open, high, low, close, volume)
                VALUES
                    (:underlying, :ticker, :option_type, :strike, :expiry,
                     :date, :open, :high, :low, :close, :volume)
                ON CONFLICT (ticker, date) DO UPDATE SET
                    open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                    close=EXCLUDED.close, volume=EXCLUDED.volume
            """), {
                "underlying": underlying,
                "ticker": opt["ticker"],
                "option_type": opt["option_type"],
                "strike": opt["strike"],
                "expiry": opt["expiry"],
                **row,
            })
            inserted += r.rowcount
    return inserted


def run(underlying: str = UNDERLYING, days: int = 90):
    _ensure_table()
    ppi = _login()

    end = datetime.today()
    start = end - timedelta(days=days)

    options = _fetch_chain(ppi, underlying)
    if not options:
        logger.warning("No options found for {u}", u=underlying)
        return

    # Print chain summary first
    df_chain = pd.DataFrame(options)[["ticker", "option_type", "strike", "expiry", "description"]]
    print(f"\n{'='*70}")
    print(f"OPTIONS CHAIN — {underlying} ({len(options)} tickers)")
    print(f"{'='*70}")
    print(df_chain.sort_values(["expiry", "option_type", "strike"]).to_string(index=False))

    # Fetch OHLCV for each option
    total_rows = 0
    results = []
    for opt in options:
        df = _fetch_ohlcv(ppi, opt["ticker"], start, end)
        n = _save(underlying, opt, df)
        total_rows += n
        if n > 0:
            results.append({
                "ticker": opt["ticker"],
                "type": opt["option_type"],
                "strike": opt["strike"],
                "expiry": opt["expiry"],
                "rows": n,
                "last_close": df["close"].iloc[-1] if not df.empty else None,
            })
            logger.info("{ticker} ({type}): {n} rows, last_close={lc}",
                        ticker=opt["ticker"], type=opt["option_type"],
                        n=n, lc=results[-1]["last_close"])
        else:
            logger.debug("{ticker}: no historical data", ticker=opt["ticker"])

    logger.info("Done — {total} rows for {n} options with data",
                total=total_rows, n=len(results))

    if results:
        print(f"\n{'='*70}")
        print(f"OPTIONS WITH DATA — {len(results)} tickers, {total_rows} rows")
        print(f"{'='*70}")
        print(pd.DataFrame(results).sort_values(["expiry", "type", "strike"]).to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--underlying", default=UNDERLYING)
    parser.add_argument("--days", type=int, default=90)
    args = parser.parse_args()
    run(underlying=args.underlying, days=args.days)
