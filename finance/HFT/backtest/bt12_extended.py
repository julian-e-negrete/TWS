"""
BT-12: Extended strategy suite.

Part A — ppi_ohlcv (36 tickers, daily OHLCV):
  macd          — MACD(12,26,9) signal crossover
  stochastic    — Stochastic(14,3): <20 buy, >80 sell
  atr_breakout  — ATR(14) breakout: close > prev_high + ATR buy, < prev_low - ATR sell
  momentum      — 10-day rate-of-change: >5% buy, <-5% sell
  mean_rev      — z-score(20): z<-1.5 buy, z>1.5 sell

Part B — binance_ticks (BTC/USDTARS, 1-min bars resampled to 1h):
  crypto_rsi        — RSI(14): <30 buy, >70 sell
  crypto_macd       — MACD(12,26,9) crossover
  crypto_bb         — Bollinger(20,2): below lower buy, above upper sell
  crypto_momentum   — 6h ROC: >2% buy, <-2% sell

Commission: 0.5% per side for ppi, 0.1% for crypto (Binance).
Exit: hold 1 bar (1 day for ppi, 1h for crypto), exit at next close.
"""
import json
import numpy as np
import pandas as pd
from sqlalchemy import text
from prometheus_client import CollectorRegistry, Gauge, Counter, push_to_gateway

from finance.utils.db_pool import get_pg_engine
from finance.utils.logger import logger

COMM_PPI    = 0.005
COMM_CRYPTO = 0.001

CATEGORIES = {
    "ACCIONES": ["GGAL","YPFD","BMA","PAMP","TXAR","ALUA","BBAR","CRES","SUPV","TECO2","TGNO4","TGSU2","VALO","MIRG","LOMA"],
    "BONOS":    ["AL30","AL30D","GD30","GD30D","AL35","GD35","AE38","GD41","GD46","AL29","GD29"],
    "CEDEARS":  ["AAPL","MSFT","GOOGL","AMZN","TSLA","NVDA","META","PBR","MELI","GLOB"],
}


# ── helpers ──────────────────────────────────────────────────────────────────

def _simulate(closes: pd.Series, signals: pd.Series, commission: float) -> dict:
    """signals: +1=buy, -1=sell. Entry at close[i], exit at close[i+1]."""
    trades = []
    for i in range(len(closes) - 1):
        sig = signals.iloc[i]
        if sig == 0:
            continue
        entry = float(closes.iloc[i])
        exit_p = float(closes.iloc[i + 1])
        if entry == 0:
            continue
        gross = (exit_p - entry) / entry if sig == 1 else (entry - exit_p) / entry
        net = gross - 2 * commission
        trades.append(net)

    # Current live position: last non-zero signal in the series
    last_sig_idx = signals[signals != 0].index[-1] if (signals != 0).any() else None
    current_position = int(signals.iloc[-1]) if signals.iloc[-1] != 0 else 0
    last_signal_price = float(closes.loc[last_sig_idx]) if last_sig_idx is not None else 0.0
    last_signal_dir   = int(signals.loc[last_sig_idx]) if last_sig_idx is not None else 0
    current_price     = float(closes.iloc[-1])
    unrealized_pnl    = (current_price - last_signal_price) / last_signal_price * last_signal_dir \
                        if last_signal_price > 0 and last_signal_dir != 0 else 0.0

    if not trades:
        return {"num_trades": 0, "total_return": 0.0, "win_rate": 0.0,
                "profit_factor": 0.0, "sharpe": 0.0, "expectancy": 0.0,
                "current_position": current_position, "last_signal_price": last_signal_price,
                "last_signal_dir": last_signal_dir, "unrealized_pnl": round(unrealized_pnl, 6)}
    arr = np.array(trades)
    wins = (arr > 0).sum()
    pos = arr[arr > 0].sum()
    neg = abs(arr[arr < 0].sum())
    sharpe = float(arr.mean() / arr.std() * np.sqrt(252)) if arr.std() > 0 else 0.0
    return {
        "num_trades": len(trades),
        "total_return": round(float(arr.sum()), 6),
        "win_rate": round(float(wins / len(trades)), 4),
        "profit_factor": round(float(pos / neg), 4) if neg > 0 else None,
        "sharpe": round(sharpe, 4),
        "expectancy": round(float(arr.mean()), 6),
        "current_position": current_position,
        "last_signal_price": last_signal_price,
        "last_signal_dir": last_signal_dir,
        "unrealized_pnl": round(unrealized_pnl, 6),
    }


def _push(instrument: str, strategy: str, m: dict):
    try:
        reg = CollectorRegistry()
        Gauge("algotrading_backtest_total_return",  "", ["strategy","instrument"], registry=reg).labels(strategy=strategy, instrument=instrument).set(m["total_return"])
        Gauge("algotrading_backtest_sharpe",        "", ["strategy","instrument"], registry=reg).labels(strategy=strategy, instrument=instrument).set(m["sharpe"])
        Gauge("algotrading_backtest_win_rate",      "", ["strategy","instrument"], registry=reg).labels(strategy=strategy, instrument=instrument).set(m["win_rate"])
        Gauge("algotrading_backtest_profit_factor", "", ["strategy","instrument"], registry=reg).labels(strategy=strategy, instrument=instrument).set(m["profit_factor"] or 0)
        Gauge("algotrading_live_position",          "", ["strategy","instrument"], registry=reg).labels(strategy=strategy, instrument=instrument).set(m.get("current_position", 0))
        Gauge("algotrading_live_entry_price",       "", ["strategy","instrument"], registry=reg).labels(strategy=strategy, instrument=instrument).set(m.get("last_signal_price", 0))
        Gauge("algotrading_live_unrealized_pnl",    "", ["strategy","instrument"], registry=reg).labels(strategy=strategy, instrument=instrument).set(m.get("unrealized_pnl", 0))
        Counter("algotrading_backtest_runs_total",  "", ["strategy"],              registry=reg).labels(strategy=strategy).inc()
        push_to_gateway("localhost:9091", job="backtest",
                        grouping_key={"strategy": strategy, "instrument": instrument},
                        registry=reg)
    except Exception as e:
        logger.debug("Pushgateway: {e}", e=e)


def _save(instrument: str, strategy: str, m: dict):
    if m["num_trades"] == 0:
        return
    with get_pg_engine().begin() as conn:
        conn.execute(text("""
            INSERT INTO bt_strategy_runs
                (instrument, strategy, date, total_return, sharpe, win_rate,
                 profit_factor, num_trades, expectancy, metadata, run_at)
            VALUES (:inst, :strat, CURRENT_DATE, :ret, :sh, :wr, :pf, :n, :exp,
                    CAST(:meta AS jsonb), NOW())
            ON CONFLICT DO NOTHING
        """), {
            "inst": instrument, "strat": strategy,
            "ret": float(m["total_return"]), "sh": float(m["sharpe"]),
            "wr": float(m["win_rate"]),
            "pf": float(m["profit_factor"]) if m["profit_factor"] else None,
            "n": int(m["num_trades"]), "exp": float(m["expectancy"]),
            "meta": json.dumps({"source": "bt12"}),
        })
    _push(instrument, strategy, m)


# ── Part A: ppi_ohlcv strategies ─────────────────────────────────────────────

def _load_ohlcv(ticker: str) -> pd.DataFrame:
    with get_pg_engine().connect() as conn:
        df = pd.read_sql(text(
            "SELECT date, open, high, low, close, volume FROM ppi_ohlcv WHERE ticker=:t ORDER BY date"
        ), conn, params={"t": ticker})
    return df.reset_index(drop=True)


def strat_macd(df: pd.DataFrame) -> dict:
    c = df["close"]
    ema12 = c.ewm(span=12).mean()
    ema26 = c.ewm(span=26).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9).mean()
    sig = pd.Series(0, index=df.index)
    sig[(macd > signal) & (macd.shift(1) <= signal.shift(1))] = 1
    sig[(macd < signal) & (macd.shift(1) >= signal.shift(1))] = -1
    return _simulate(c, sig, COMM_PPI)


def strat_stochastic(df: pd.DataFrame, k=14, d=3) -> dict:
    low_k  = df["low"].rolling(k).min()
    high_k = df["high"].rolling(k).max()
    pct_k  = 100 * (df["close"] - low_k) / (high_k - low_k + 1e-9)
    pct_d  = pct_k.rolling(d).mean()
    sig = pd.Series(0, index=df.index)
    sig[(pct_k < 20) & (pct_d < 20)] = 1
    sig[(pct_k > 80) & (pct_d > 80)] = -1
    return _simulate(df["close"], sig, COMM_PPI)


def strat_atr_breakout(df: pd.DataFrame, period=14) -> dict:
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"]  - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    sig = pd.Series(0, index=df.index)
    sig[df["close"] > df["high"].shift(1) + atr] = 1
    sig[df["close"] < df["low"].shift(1)  - atr] = -1
    return _simulate(df["close"], sig, COMM_PPI)


def strat_momentum(df: pd.DataFrame, period=10) -> dict:
    roc = df["close"].pct_change(period)
    sig = pd.Series(0, index=df.index)
    sig[roc > 0.05]  = 1
    sig[roc < -0.05] = -1
    return _simulate(df["close"], sig, COMM_PPI)


def strat_mean_rev(df: pd.DataFrame, period=20) -> dict:
    c = df["close"]
    z = (c - c.rolling(period).mean()) / (c.rolling(period).std() + 1e-9)
    sig = pd.Series(0, index=df.index)
    sig[z < -1.5] = 1
    sig[z >  1.5] = -1
    return _simulate(c, sig, COMM_PPI)


PPI_STRATEGIES = {
    "macd":         strat_macd,
    "stochastic":   strat_stochastic,
    "atr_breakout": strat_atr_breakout,
    "momentum":     strat_momentum,
    "mean_rev":     strat_mean_rev,
}


def run_ppi():
    results = []
    for cat, tickers in CATEGORIES.items():
        for ticker in tickers:
            df = _load_ohlcv(ticker)
            if len(df) < 30:
                continue
            for name, fn in PPI_STRATEGIES.items():
                m = fn(df)
                _save(ticker, name, m)
                results.append({"cat": cat, "ticker": ticker, "strategy": name, **m})
                if m["num_trades"] > 0:
                    print(f"  {ticker:<6} {name:<14} trades={m['num_trades']:>3}  "
                          f"ret={m['total_return']:>+.3f}  sharpe={m['sharpe']:>+.2f}  "
                          f"wr={m['win_rate']:.0%}")
    return pd.DataFrame(results)


# ── Part B: Binance crypto strategies ────────────────────────────────────────

def _load_crypto(symbol: str, resample: str = "1h") -> pd.DataFrame:
    with get_pg_engine().connect() as conn:
        df = pd.read_sql(text(
            "SELECT timestamp, open, high, low, close, volume FROM binance_ticks "
            "WHERE symbol=:s ORDER BY timestamp"
        ), conn, params={"s": symbol})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp")
    if resample != "1min":
        df = df.resample(resample).agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        ).dropna()
    return df.reset_index()


def crypto_rsi(df: pd.DataFrame, period=14) -> dict:
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    sig = pd.Series(0, index=df.index)
    sig[rsi < 30] = 1
    sig[rsi > 70] = -1
    return _simulate(df["close"], sig, COMM_CRYPTO)


def crypto_macd(df: pd.DataFrame) -> dict:
    c = df["close"]
    macd = c.ewm(span=12).mean() - c.ewm(span=26).mean()
    signal = macd.ewm(span=9).mean()
    sig = pd.Series(0, index=df.index)
    sig[(macd > signal) & (macd.shift(1) <= signal.shift(1))] = 1
    sig[(macd < signal) & (macd.shift(1) >= signal.shift(1))] = -1
    return _simulate(c, sig, COMM_CRYPTO)


def crypto_bb(df: pd.DataFrame, period=20, std=2.0) -> dict:
    c = df["close"]
    mid = c.rolling(period).mean()
    band = c.rolling(period).std()
    sig = pd.Series(0, index=df.index)
    sig[c < mid - std * band] = 1
    sig[c > mid + std * band] = -1
    return _simulate(c, sig, COMM_CRYPTO)


def crypto_momentum(df: pd.DataFrame, period=6) -> dict:
    roc = df["close"].pct_change(period)
    sig = pd.Series(0, index=df.index)
    sig[roc > 0.02]  = 1
    sig[roc < -0.02] = -1
    return _simulate(df["close"], sig, COMM_CRYPTO)


CRYPTO_STRATEGIES = {
    "crypto_rsi":      crypto_rsi,
    "crypto_macd":     crypto_macd,
    "crypto_bb":       crypto_bb,
    "crypto_momentum": crypto_momentum,
}


def run_crypto():
    results = []
    for symbol in ["BTCUSDT", "USDTARS"]:
        df = _load_crypto(symbol, resample="1h")
        logger.info("{sym}: {n} hourly bars", sym=symbol, n=len(df))
        for name, fn in CRYPTO_STRATEGIES.items():
            m = fn(df)
            _save(symbol, name, m)
            results.append({"symbol": symbol, "strategy": name, **m})
            if m["num_trades"] > 0:
                print(f"  {symbol:<10} {name:<18} trades={m['num_trades']:>4}  "
                      f"ret={m['total_return']:>+.4f}  sharpe={m['sharpe']:>+.2f}  "
                      f"wr={m['win_rate']:.0%}")
    return pd.DataFrame(results)


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "═"*70)
    print("  BT-12 Part A — ppi_ohlcv: MACD, Stochastic, ATR, Momentum, MeanRev")
    print("═"*70)
    ppi_df = run_ppi()

    print("\n" + "═"*70)
    print("  BT-12 Part B — Binance: RSI, MACD, BB, Momentum (1h bars)")
    print("═"*70)
    crypto_df = run_crypto()

    # Summary tables
    print("\n=== PPI — Best strategy per ticker (by Sharpe) ===")
    if not ppi_df.empty and ppi_df["num_trades"].sum() > 0:
        best = (ppi_df[ppi_df["num_trades"] > 0]
                .sort_values("sharpe", ascending=False)
                .groupby("ticker").first().reset_index()
                [["ticker","cat","strategy","total_return","sharpe","win_rate","num_trades"]])
        print(best.to_string(index=False))

    print("\n=== Crypto — All results ===")
    if not crypto_df.empty:
        print(crypto_df[["symbol","strategy","num_trades","total_return","sharpe","win_rate","profit_factor"]]
              .to_string(index=False))

    print("\nAll results saved to bt_strategy_runs + Grafana.")
