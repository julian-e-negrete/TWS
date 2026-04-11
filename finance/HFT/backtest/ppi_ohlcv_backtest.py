"""
BT-10: Daily OHLCV strategies on ppi_ohlcv (36 tickers).

Strategies:
  ma_crossover   — BUY when MA20 crosses above MA50, SELL when crosses below
  rsi_reversion  — BUY when RSI < 30, SELL when RSI > 70
  bollinger      — BUY when close < lower band, SELL when close > upper band

Exit: hold 1 day, exit at next close. Commission 0.5% per side.
"""
import json
import numpy as np
import pandas as pd
from sqlalchemy import text
from prometheus_client import CollectorRegistry, Gauge, Counter, push_to_gateway

from finance.utils.db_pool import get_pg_engine
from finance.utils.logger import logger

COMMISSION = 0.005

CATEGORIES = {
    "ACCIONES": ["GGAL","YPFD","BMA","PAMP","TXAR","ALUA","BBAR","CRES","SUPV","TECO2","TGNO4","TGSU2","VALO","MIRG","LOMA"],
    "BONOS":    ["AL30","AL30D","GD30","GD30D","AL35","GD35","AE38","GD41","GD46","AL29","GD29"],
    "CEDEARS":  ["AAPL","MSFT","GOOGL","AMZN","TSLA","NVDA","META","PBR","MELI","GLOB"],
}


def _load(ticker: str) -> pd.DataFrame:
    with get_pg_engine().connect() as conn:
        df = pd.read_sql(text(
            "SELECT date, open, high, low, close, volume FROM ppi_ohlcv WHERE ticker=:t ORDER BY date"
        ), conn, params={"t": ticker})
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df.reset_index(drop=True)


def _simulate(df: pd.DataFrame, signals: pd.Series) -> dict:
    """
    signals: +1=buy, -1=sell, 0=hold. Entry at close[i], exit at close[i+1].
    """
    trades = []
    for i in range(len(df) - 1):
        sig = signals.iloc[i]
        if sig == 0:
            continue
        entry = float(df["close"].iloc[i])
        exit_p = float(df["close"].iloc[i + 1])
        gross = (exit_p - entry) / entry if sig == 1 else (entry - exit_p) / entry
        net = gross - 2 * COMMISSION
        trades.append(net)

    if not trades:
        return {"num_trades": 0, "total_return": 0.0, "win_rate": 0.0, "profit_factor": 0.0, "sharpe": 0.0}

    arr = np.array(trades)
    wins = (arr > 0).sum()
    pos = arr[arr > 0].sum()
    neg = abs(arr[arr < 0].sum())
    sharpe = float(arr.mean() / arr.std() * np.sqrt(252)) if arr.std() > 0 else 0.0
    return {
        "num_trades": len(trades),
        "total_return": float(arr.sum()),
        "win_rate": float(wins / len(trades)),
        "profit_factor": float(pos / neg) if neg > 0 else None,
        "sharpe": round(sharpe, 4),
    }


def ma_crossover(df: pd.DataFrame) -> dict:
    c = df["close"]
    ma20 = c.rolling(20).mean()
    ma50 = c.rolling(50).mean()
    sig = pd.Series(0, index=df.index)
    sig[(ma20 > ma50) & (ma20.shift(1) <= ma50.shift(1))] = 1   # golden cross → buy
    sig[(ma20 < ma50) & (ma20.shift(1) >= ma50.shift(1))] = -1  # death cross → sell
    return _simulate(df, sig)


def rsi_reversion(df: pd.DataFrame, period: int = 14) -> dict:
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    sig = pd.Series(0, index=df.index)
    sig[rsi < 30] = 1    # oversold → buy
    sig[rsi > 70] = -1   # overbought → sell
    return _simulate(df, sig)


def bollinger(df: pd.DataFrame, period: int = 20, std: float = 2.0) -> dict:
    c = df["close"]
    mid = c.rolling(period).mean()
    band = c.rolling(period).std()
    sig = pd.Series(0, index=df.index)
    sig[c < mid - std * band] = 1    # below lower band → buy
    sig[c > mid + std * band] = -1   # above upper band → sell
    return _simulate(df, sig)


STRATEGIES = {"ma_crossover": ma_crossover, "rsi_reversion": rsi_reversion, "bollinger": bollinger}


def _save(ticker: str, strategy: str, m: dict):
    if m["num_trades"] == 0:
        return
    with get_pg_engine().begin() as conn:
        conn.execute(text("""
            INSERT INTO bt_strategy_runs
                (instrument, strategy, date, total_return, sharpe, win_rate, profit_factor, num_trades, metadata, run_at)
            VALUES (:inst, :strat, CURRENT_DATE, :ret, :sh, :wr, :pf, :n, CAST(:meta AS jsonb), NOW())
            ON CONFLICT DO NOTHING
        """), {
            "inst": ticker, "strat": strategy,
            "ret": float(m["total_return"]), "sh": float(m["sharpe"]),
            "wr": float(m["win_rate"]),
            "pf": float(m["profit_factor"]) if m["profit_factor"] else None,
            "n": int(m["num_trades"]),
            "meta": json.dumps({"source": "ppi_ohlcv"}),
        })
    try:
        reg = CollectorRegistry()
        Gauge("algotrading_backtest_total_return",  "", ["strategy","instrument"], registry=reg).labels(strategy=strategy, instrument=ticker).set(m["total_return"])
        Gauge("algotrading_backtest_sharpe",        "", ["strategy","instrument"], registry=reg).labels(strategy=strategy, instrument=ticker).set(m["sharpe"])
        Gauge("algotrading_backtest_win_rate",      "", ["strategy","instrument"], registry=reg).labels(strategy=strategy, instrument=ticker).set(m["win_rate"])
        Gauge("algotrading_backtest_profit_factor", "", ["strategy","instrument"], registry=reg).labels(strategy=strategy, instrument=ticker).set(m["profit_factor"] or 0)
        Counter("algotrading_backtest_runs_total",  "", ["strategy"],              registry=reg).labels(strategy=strategy).inc()
        push_to_gateway("localhost:9091", job="backtest", grouping_key={"strategy": strategy, "instrument": ticker}, registry=reg)
    except Exception as e:
        logger.debug("Pushgateway unavailable: {e}", e=e)


if __name__ == "__main__":
    results = []
    for cat, tickers in CATEGORIES.items():
        for ticker in tickers:
            df = _load(ticker)
            if len(df) < 55:
                logger.warning("Skipping {t}: only {n} rows", t=ticker, n=len(df))
                continue
            for strat_name, strat_fn in STRATEGIES.items():
                m = strat_fn(df)
                _save(ticker, strat_name, m)
                results.append({"category": cat, "ticker": ticker, "strategy": strat_name, **m})

    rdf = pd.DataFrame(results)
    print("\n=== BT-10 Results by Category ===")
    for cat in CATEGORIES:
        sub = rdf[rdf["category"] == cat]
        print(f"\n--- {cat} ---")
        print(sub[["ticker","strategy","num_trades","total_return","sharpe","win_rate","profit_factor"]]
              .sort_values("sharpe", ascending=False)
              .to_string(index=False))

    print("\n=== Best per ticker (by Sharpe) ===")
    best = rdf[rdf["num_trades"] > 0].sort_values("sharpe", ascending=False).groupby("ticker").first().reset_index()
    print(best[["ticker","strategy","total_return","sharpe","win_rate","num_trades"]].to_string(index=False))
