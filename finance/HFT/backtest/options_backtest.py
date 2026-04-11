"""
BT-11: GGAL options backtest — Black-Scholes strategies.

Strategies:
  bs_long_call   — BUY calls when market_price < BS * 0.95 (underpriced)
  bs_short_call  — SELL calls when market_price > BS * 1.05 (overpriced)
  bs_long_put    — BUY puts when market_price < BS * 0.95 (underpriced)
  bs_short_put   — SELL puts when market_price > BS * 1.05 (overpriced)

Exit assumption: hold to next trading day, exit at next-day close.
"""
import json
from datetime import date, datetime
import numpy as np
import pandas as pd
from scipy.stats import norm
from scipy.optimize import brentq
from sqlalchemy import text
from prometheus_client import CollectorRegistry, Gauge, Counter, push_to_gateway

from finance.utils.db_pool import get_pg_engine
from finance.utils.logger import logger

RISK_FREE   = 0.40    # BCRA ARS reference rate
COMMISSION  = 0.005   # 0.5% per side
BUY_THRESH  = 0.90    # buy when market < BS * 0.90
SELL_THRESH = 1.10    # sell when market > BS * 1.10
MAX_MISPR   = 200.0   # ignore signals where |mispricing| > 200% (deep OTM noise)
MIN_T_DAYS  = 7       # skip options within 7 days of expiry
CONTRACT    = 100     # GGAL options: 100 shares per contract

STRATEGIES = {
    "bs_long_call":  {"option_type": "C", "direction": "BUY"},
    "bs_short_call": {"option_type": "C", "direction": "SELL"},
    "bs_long_put":   {"option_type": "P", "direction": "BUY"},
    "bs_short_put":  {"option_type": "P", "direction": "SELL"},
}


# ---------------------------------------------------------------------------
# Black-Scholes helpers
# ---------------------------------------------------------------------------

def _bs(S, K, T, r, sigma, opt_type):
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return np.nan
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if opt_type == "C":
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def _iv(S, K, T, r, mkt, opt_type):
    try:
        return brentq(lambda s: _bs(S, K, T, r, s, opt_type) - mkt, 1e-5, 5.0)
    except Exception:
        return np.nan


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load(expiry: date):
    engine = get_pg_engine()
    with engine.connect() as conn:
        # Only tickers that traded in the last 30 days (liquid universe)
        active = pd.read_sql(text("""
            SELECT DISTINCT ticker FROM ppi_options_chain
            WHERE underlying='GGAL' AND expiry=:exp AND volume > 0
              AND date >= CURRENT_DATE - INTERVAL '30 days'
        """), conn, params={"exp": expiry})
        if active.empty:
            raise ValueError(f"No active tickers for expiry={expiry}")
        tickers = tuple(active["ticker"].tolist())
        opts = pd.read_sql(text("""
            SELECT ticker, option_type, strike, expiry, date, close, volume
            FROM ppi_options_chain
            WHERE underlying='GGAL' AND expiry=:exp AND close IS NOT NULL
              AND ticker = ANY(:tickers)
            ORDER BY ticker, date
        """), conn, params={"exp": expiry, "tickers": list(tickers)})
        spot = pd.read_sql(text("""
            SELECT date, close AS spot FROM ppi_ohlcv WHERE ticker='GGAL' ORDER BY date
        """), conn)
    logger.info("Active tickers (traded last 30d): {n}", n=len(tickers))
    opts["date"] = pd.to_datetime(opts["date"]).dt.date
    spot["date"] = pd.to_datetime(spot["date"]).dt.date
    return opts, dict(zip(spot["date"], spot["spot"]))


# ---------------------------------------------------------------------------
# Build enriched dataframe with BS price + IV (no look-ahead)
# ---------------------------------------------------------------------------

def _enrich(opts: pd.DataFrame, spot_map: dict, expiry: date) -> pd.DataFrame:
    # Strikes are quoted in ARS×10 vs spot in ARS — normalize throughout
    STRIKE_DIVISOR = 10.0

    # Compute IV per ticker per day (no look-ahead: only used as prev_day median)
    iv_map: dict[str, dict] = {}
    for ticker, grp in opts.groupby("ticker"):
        for _, row in grp.sort_values("date").iterrows():
            S = spot_map.get(row["date"])
            if S is None: continue
            K = row["strike"] / STRIKE_DIVISOR
            if not (S * 0.5 <= K <= S * 2.0): continue
            T = (expiry - row["date"]).days / 365.0
            iv = _iv(S, K, T, RISK_FREE, row["close"], row["option_type"])
            if not np.isnan(iv):
                iv_map.setdefault(ticker, {})[row["date"]] = iv

    rows = []
    for ticker, grp in opts.groupby("ticker"):
        ticker_ivs = iv_map.get(ticker, {})
        dates_sorted = sorted(ticker_ivs)
        grp_sorted = grp.sort_values("date").reset_index(drop=True)
        next_close_map = dict(zip(grp_sorted["date"], grp_sorted["close"].shift(-1)))
        for _, row in grp_sorted.iterrows():
            if row["volume"] == 0:
                continue
            S = spot_map.get(row["date"])
            if S is None:
                continue
            K = row["strike"] / STRIKE_DIVISOR
            if not (S * 0.5 <= K <= S * 2.0):
                continue
            T = (expiry - row["date"]).days / 365.0
            if T < MIN_T_DAYS / 365.0:
                continue
            prev_ivs = [ticker_ivs[d] for d in dates_sorted if d < row["date"]]
            if not prev_ivs:
                continue
            sigma = float(np.median(prev_ivs))
            bs = _bs(S, K, T, RISK_FREE, sigma, row["option_type"])
            if np.isnan(bs) or bs <= 0:
                continue
            nc = next_close_map.get(row["date"])
            rows.append({
                "ticker": ticker, "option_type": row["option_type"],
                "strike": K, "date": row["date"],
                "spot": float(S), "market": float(row["close"]),
                "next_close": float(nc) if pd.notna(nc) else np.nan,
                "bs": round(float(bs), 4), "sigma": round(sigma, 4),
                "mispricing": round((row["close"] - bs) / bs * 100, 2),
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Simulate one strategy
# ---------------------------------------------------------------------------

def _simulate(df: pd.DataFrame, opt_type: str, direction: str,
              strategy: str, expiry: date, live: bool = True) -> dict:
    # Exit at next-day market close (realistic), not at BS theoretical price
    sub = df[
        (df["option_type"] == opt_type) &
        df["next_close"].notna() &
        (df["mispricing"].abs() <= MAX_MISPR)   # filter deep-OTM noise
    ].copy()
    trades = []
    for _, row in sub.iterrows():
        mkt, bs, exit_p = row["market"], row["bs"], row["next_close"]
        if direction == "BUY" and mkt < bs * BUY_THRESH:
            entry = mkt
        elif direction == "SELL" and mkt > bs * SELL_THRESH:
            entry = mkt
        else:
            continue
        gross = (exit_p - entry) if direction == "BUY" else (entry - exit_p)
        net = gross - (entry + exit_p) * COMMISSION
        net = round(net, 4)

        if live:
            sign = "▲" if net > 0 else "▼"
            action = f"{'OPEN BUY ':9}" if direction == "BUY" else f"{'OPEN SELL':9}"
            print(f"  {row['date']}  {action}  {row['ticker']:<12}  K={row['strike']:>7.1f}  "
                  f"S={row['spot']:>6.0f}  entry={entry:>7.2f}  exit={exit_p:>7.2f}  "
                  f"BS={bs:>7.2f}  misp={row['mispricing']:>+6.1f}%  "
                  f"PnL={net:>+8.2f}  {sign}")

        _push_trade(strategy, row["ticker"], expiry, net, direction)

        trades.append({
            "date": row["date"], "ticker": row["ticker"],
            "option_type": opt_type, "strike": row["strike"],
            "spot": row["spot"],
            "direction": direction, "entry": entry, "exit": exit_p,
            "bs": row["bs"], "sigma": row["sigma"],
            "mispricing_pct": row["mispricing"],
            "net_pnl": net,
        })

    if not trades:
        return {"num_trades": 0, "total_pnl": 0.0, "total_return": 0.0, "win_rate": 0.0, "profit_factor": 0.0, "expectancy": 0.0, "trades": []}

    tdf = pd.DataFrame(trades)
    wins = (tdf["net_pnl"] > 0).sum()
    n = len(tdf)
    pos = tdf[tdf["net_pnl"] > 0]["net_pnl"].sum()
    neg = abs(tdf[tdf["net_pnl"] < 0]["net_pnl"].sum())
    # Normalize: total_return = sum(net_pnl) / sum(entry * CONTRACT)
    # This gives a % return on capital deployed per trade
    notional = float((tdf["entry"] * CONTRACT).sum())
    total_return = round(float(tdf["net_pnl"].sum()) / notional, 6) if notional > 0 else 0.0
    return {
        "num_trades": n,
        "total_pnl": round(float(tdf["net_pnl"].sum()), 4),   # raw ARS — for display
        "total_return": total_return,                           # normalized ratio — for DB/Grafana
        "win_rate": round(wins / n, 4),
        "profit_factor": round(pos / neg, 4) if neg > 0 else None,
        "expectancy": round(float(tdf["net_pnl"].mean()), 4),
        "trades": trades,
    }


# ---------------------------------------------------------------------------
# Persist + push to Grafana
# ---------------------------------------------------------------------------

def _push_trade(strategy: str, ticker: str, expiry: date, net_pnl: float, direction: str):
    """Push individual trade result to Pushgateway with ticker-level granularity."""
    instrument = f"GGAL_options_{expiry}"
    try:
        reg = CollectorRegistry()
        Gauge("algotrading_options_trade_pnl", "Last trade net PnL",
              ["strategy", "instrument", "ticker", "direction"], registry=reg
              ).labels(strategy=strategy, instrument=instrument,
                       ticker=ticker, direction=direction).set(net_pnl)
        push_to_gateway("localhost:9091", job="backtest",
                        grouping_key={"strategy": strategy, "instrument": instrument, "ticker": ticker},
                        registry=reg)
    except Exception as e:
        logger.debug("Pushgateway unavailable: {e}", e=e)


def _push_summary(expiry: date, strategy: str, metrics: dict):
    instrument = f"GGAL_options_{expiry}"
    try:
        reg = CollectorRegistry()
        Gauge("algotrading_backtest_total_return",  "", ["strategy","instrument"], registry=reg).labels(strategy=strategy, instrument=instrument).set(metrics["total_return"])
        Gauge("algotrading_backtest_win_rate",      "", ["strategy","instrument"], registry=reg).labels(strategy=strategy, instrument=instrument).set(metrics["win_rate"])
        Gauge("algotrading_backtest_profit_factor", "", ["strategy","instrument"], registry=reg).labels(strategy=strategy, instrument=instrument).set(metrics["profit_factor"] or 0)
        Counter("algotrading_backtest_runs_total",  "", ["strategy"],              registry=reg).labels(strategy=strategy).inc()
        push_to_gateway("localhost:9091", job="backtest",
                        grouping_key={"strategy": strategy, "instrument": instrument},
                        registry=reg)
    except Exception as e:
        logger.debug("Pushgateway unavailable: {e}", e=e)


def _save(expiry: date, strategy: str, metrics: dict):
    instrument = f"GGAL_options_{expiry}"
    engine = get_pg_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO bt_strategy_runs
                (instrument, strategy, date, total_return, win_rate, profit_factor,
                 num_trades, expectancy, metadata, run_at)
            VALUES
                (:inst, :strat, :dt, :ret, :wr, :pf, :n, :exp, CAST(:meta AS jsonb), NOW())
            ON CONFLICT DO NOTHING
        """), {
            "inst": instrument, "strat": strategy, "dt": expiry,
            "ret": float(metrics["total_return"]),   # normalized ratio
            "wr": float(metrics["win_rate"]),
            "pf": float(metrics["profit_factor"]) if metrics["profit_factor"] else None,
            "n": int(metrics["num_trades"]),
            "exp": float(metrics["expectancy"]),
            "meta": json.dumps({"sigma_source": "prev_day_iv_median",
                                 "total_pnl_ars": metrics["total_pnl"]}),
        })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(expiry: date):
    logger.info("Loading options data for expiry={exp}", exp=expiry)
    opts, spot_map = _load(expiry)
    logger.info("Enriching {n} option rows with BS prices...", n=len(opts))
    df = _enrich(opts, spot_map, expiry)
    logger.info("Enriched {n} rows. Running strategies...", n=len(df))

    print(f"\n{'Strategy':<20} {'Trades':>7} {'Total PnL':>12} {'Win Rate':>10} {'Prof.Factor':>12} {'Expectancy':>12}")
    print("-" * 75)
    all_metrics = {}
    for name, cfg in STRATEGIES.items():
        print(f"\n{'─'*90}")
        print(f"  STRATEGY: {name}  ({cfg['direction']} {cfg['option_type']})  expiry={expiry}")
        print(f"  {'Date':<12} {'Action':<9} {'Ticker':<12} {'Strike':>8} {'Spot':>6} "
              f"{'Entry':>8} {'Exit':>8} {'BS':>8} {'Misp%':>7} {'PnL':>9}")
        print(f"  {'─'*88}")
        m = _simulate(df, cfg["option_type"], cfg["direction"], name, expiry, live=True)
        _save(expiry, name, m)
        _push_summary(expiry, name, m)
        pf = f"{m['profit_factor']:.2f}" if m["profit_factor"] else "  inf"
        all_metrics[name] = m
        print(f"\n  → {name:<20} trades={m['num_trades']:>4}  total_pnl={m['total_pnl']:>+10.2f}"
              f"  win_rate={m['win_rate']:>6.1%}  pf={pf}  expectancy={m['expectancy']:>+8.4f}")

    print(f"\n{'═'*75}")
    print(f"{'Strategy':<20} {'Trades':>7} {'Total PnL':>12} {'Win Rate':>10} {'Prof.Factor':>12}")
    print(f"{'─'*75}")
    for name, m in all_metrics.items():
        pf = f"{m['profit_factor']:.2f}" if m["profit_factor"] else "  inf"
        print(f"{name:<20} {m['num_trades']:>7} {m['total_pnl']:>12.2f} {m['win_rate']:>10.1%} {pf:>12}")

    print(f"\nAll results saved to bt_strategy_runs and pushed to Grafana (per-ticker).")

    # P&L by ticker summary
    for name, m in all_metrics.items():
        if not m["trades"]: continue
        tdf = pd.DataFrame(m["trades"])
        by_ticker = tdf.groupby("ticker")["net_pnl"].sum().sort_values(ascending=False)
        print(f"\n  {name} — P&L by ticker:")
        for ticker, pnl in by_ticker.items():
            bar = "█" * min(int(abs(pnl) / 20), 30)
            sign = "+" if pnl >= 0 else "-"
            print(f"    {ticker:<14} {sign}{abs(pnl):>8.2f}  {'▲' if pnl>=0 else '▼'} {bar}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--expiry", default="2026-04-17")
    args = parser.parse_args()
    run(datetime.strptime(args.expiry, "%Y-%m-%d").date())
