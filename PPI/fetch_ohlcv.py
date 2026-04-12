"""
PPI OHLCV Fetcher & Plotter
============================
Fetches historical OHLCV data for one or more tickers via the PPI broker API
and generates interactive candlestick charts.

Usage (CLI):
    PYTHONPATH=. python3 -m PPI.fetch_ohlcv \
        --tickers GGAL YPFD PAMP \
        --type ACCIONES \
        --settlement 24hs \
        --start 2025-01-01 \
        --end 2025-12-31

Usage (library):
    from PPI.fetch_ohlcv import fetch_ohlcv, plot_ohlcv
    dfs = fetch_ohlcv(["GGAL", "YPFD"], "ACCIONES", "24hs", "2025-01-01", "2025-12-31")
    plot_ohlcv(dfs)

PPI field mapping:
    openingPrice → open
    max          → high
    min          → low
    price        → close
    volume       → volume
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from ppi_client.ppi import PPI

from finance.config import settings
from finance.utils.logger import logger


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _make_ppi_client() -> PPI:
    """Instantiate and authenticate a PPI client from .env credentials."""
    ppi = PPI(sandbox=False)
    ppi.account.login_api(settings.ppi.public_key, settings.ppi.private_key)
    logger.info("PPI authentication OK")
    return ppi


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

_AUTO_TYPES = ["ACCIONES", "BONOS", "CEDEARS"]


def _fetch_one(
    ppi: "PPI",
    ticker: str,
    instrument_type: str,
    settlement: str,
    start_dt: "datetime",
    end_dt: "datetime",
) -> list | None:
    """Return raw PPI response or None on failure / empty."""
    try:
        raw = ppi.marketdata.search(ticker.upper(), instrument_type, settlement, start_dt, end_dt)
        return raw if raw else None
    except Exception as e:
        logger.debug(f"  {ticker}/{instrument_type}: {e}")
        return None


def fetch_ohlcv(
    tickers: list[str],
    instrument_type: str,
    settlement: str,
    start_date: str,
    end_date: str,
) -> dict[str, pd.DataFrame]:
    """
    Fetch daily OHLCV bars for each ticker from PPI.

    Parameters
    ----------
    tickers        : list of PPI ticker symbols, e.g. ["GGAL", "YPFD"]
    instrument_type: PPI instrument type string, e.g. "ACCIONES", "BONOS", "CEDEARS".
                     Use "AUTO" to try all types and return the first that has data.
    settlement     : settlement window, e.g. "A-24hs", "A-48hs", "INMEDIATA"
    start_date     : ISO date string "YYYY-MM-DD"
    end_date       : ISO date string "YYYY-MM-DD"

    Returns
    -------
    dict mapping ticker → pd.DataFrame with columns:
        date, open, high, low, close, volume
    (index is DatetimeIndex)
    """
    ppi = _make_ppi_client()
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    result: dict[str, pd.DataFrame] = {}

    for ticker in tickers:
        # Determine which types to try
        if instrument_type.upper() == "AUTO":
            types_to_try = _AUTO_TYPES
        else:
            types_to_try = [instrument_type]

        raw = None
        matched_type = instrument_type
        for itype in types_to_try:
            logger.info(f"Fetching {ticker} ({itype}/{settlement}) {start_date} → {end_date}")
            raw = _fetch_one(ppi, ticker, itype, settlement, start_dt, end_dt)
            if raw:
                matched_type = itype
                break

        if not raw:
            logger.warning(f"No data returned for {ticker} (tried: {', '.join(types_to_try)})")
            continue

        df = pd.DataFrame(raw)

        # Normalize column names from PPI response
        rename = {
            "date": "date",
            "openingPrice": "open",
            "max": "high",
            "min": "low",
            "price": "close",
            "volume": "volume",
        }
        df = df.rename(columns=rename)

        # Keep only OHLCV columns that exist
        cols = [c for c in ["date", "open", "high", "low", "close", "volume"] if c in df.columns]
        df = df[cols].copy()

        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()

        # Cast numeric columns
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["close"])
        result[ticker] = df
        logger.info(f"  {ticker} [{matched_type}]: {len(df)} bars  close={df['close'].iloc[-1]:.2f}")

    return result


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def plot_ohlcv(
    data: dict[str, pd.DataFrame],
    title: str = "PPI OHLCV",
    show: bool = True,
    save_html: str | None = None,
) -> go.Figure:
    """
    Render interactive candlestick charts (one per ticker) using Plotly.

    Parameters
    ----------
    data      : output of fetch_ohlcv()
    title     : overall figure title
    show      : open in browser if True
    save_html : path to write standalone HTML file (optional)
    """
    n = len(data)
    if n == 0:
        logger.warning("No data to plot")
        return go.Figure()

    fig = make_subplots(
        rows=n,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        subplot_titles=list(data.keys()),
        row_heights=[1.0] * n,
    )

    for i, (ticker, df) in enumerate(data.items(), start=1):
        has_ohlc = all(c in df.columns for c in ["open", "high", "low", "close"])

        if has_ohlc:
            fig.add_trace(
                go.Candlestick(
                    x=df.index,
                    open=df["open"],
                    high=df["high"],
                    low=df["low"],
                    close=df["close"],
                    name=ticker,
                    increasing_line_color="#26a69a",
                    decreasing_line_color="#ef5350",
                    showlegend=False,
                ),
                row=i,
                col=1,
            )
        else:
            # Fallback: line chart on close price
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=df["close"],
                    name=ticker,
                    line=dict(width=1.5),
                    showlegend=False,
                ),
                row=i,
                col=1,
            )

        # Volume bars as secondary y-axis overlay
        if "volume" in df.columns and df["volume"].sum() > 0:
            # Normalise volume to 20% of price range for overlay
            price_range = df["close"].max() - df["close"].min()
            vol_scale = (price_range * 0.2) / df["volume"].max() if df["volume"].max() > 0 else 1
            fig.add_trace(
                go.Bar(
                    x=df.index,
                    y=df["volume"] * vol_scale + df["close"].min(),
                    name=f"{ticker} vol",
                    marker_color="rgba(100,100,200,0.25)",
                    showlegend=False,
                ),
                row=i,
                col=1,
            )

        fig.update_yaxes(title_text=ticker, row=i, col=1)

    fig.update_layout(
        title=title,
        xaxis_rangeslider_visible=False,
        height=320 * n,
        template="plotly_dark",
        margin=dict(l=60, r=20, t=60, b=40),
    )

    if save_html:
        fig.write_html(save_html)
        logger.info(f"Chart saved to {save_html}")

    if show:
        fig.show()

    return fig


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch and plot PPI OHLCV data")
    p.add_argument("--tickers", nargs="+", required=True, help="PPI ticker symbols")
    p.add_argument(
        "--type",
        dest="instrument_type",
        default="AUTO",
        help="Instrument type: AUTO, ACCIONES, BONOS, CEDEARS, FUTUROS (default: AUTO — tries all)",
    )
    p.add_argument(
        "--settlement",
        default="A-24hs",
        help="Settlement: A-24hs, A-48hs, INMEDIATA (default: 24hs)",
    )
    p.add_argument(
        "--start",
        default="2025-01-01",
        help="Start date YYYY-MM-DD (default: 2025-01-01)",
    )
    p.add_argument(
        "--end",
        default=datetime.today().strftime("%Y-%m-%d"),
        help="End date YYYY-MM-DD (default: today)",
    )
    p.add_argument(
        "--save",
        default=None,
        metavar="FILE.html",
        help="Save chart to HTML file instead of opening browser",
    )
    p.add_argument(
        "--output",
        choices=["json", "plot"],
        default="plot",
        help="Output mode: 'json' prints OHLCV as JSON array to stdout (for programmatic use); "
             "'plot' opens interactive chart (default: plot)",
    )
    return p.parse_args()


def _to_json(data: dict[str, "pd.DataFrame"]) -> None:
    """Serialize OHLCV data as a JSON array to stdout (one ticker, flat list of bars)."""
    if not data:
        print("[]")
        return
    # Take the first (and typically only) ticker
    ticker, df = next(iter(data.items()))
    bars = []
    for date, row in df.iterrows():
        bar: dict = {"date": str(date.date())}
        for col in ["open", "high", "low", "close", "volume"]:
            if col in row.index:
                v = row[col]
                bar[col] = float(v) if v == v else None  # NaN → None
        bars.append(bar)
    json.dump(bars, sys.stdout, ensure_ascii=False)
    sys.stdout.flush()


if __name__ == "__main__":
    args = _parse_args()
    dfs = fetch_ohlcv(
        tickers=args.tickers,
        instrument_type=args.instrument_type,
        settlement=args.settlement,
        start_date=args.start,
        end_date=args.end,
    )
    if args.output == "json":
        _to_json(dfs)
    else:
        plot_ohlcv(dfs, title=" | ".join(args.tickers), save_html=args.save)
