"""
Strategies adapted for BYMA equities and Binance crypto.
Same logic as dlr_strategies but with market-appropriate thresholds.
"""
import math
import numpy as np
import pandas as pd

from finance.HFT.backtest.types import Direction, OrderType
from finance.HFT.dashboard.calcultions import enhanced_order_flow_imbalance


def _instrument(current_market, recent_trades):
    if current_market:
        return current_market.instrument
    return recent_trades[-1].instrument if recent_trades else None


def _vol(cash, price, max_risk_pct=0.5):
    """Max 1 unit for equities/crypto (multiplier=1, prices can be large)."""
    return max(1, math.floor(max_risk_pct * cash / price)) if price > 0 else 1


# ---------------------------------------------------------------------------
# BYMA strategies — spread threshold relaxed to 1% (BYMA avg ~0.5%)
# ---------------------------------------------------------------------------

def byma_vwap(current_market, recent_trades, current_position, current_cash):
    signals = []
    instrument = _instrument(current_market, recent_trades)
    if not instrument or not current_market or len(recent_trades) < 15:
        return signals
    mid = (current_market.bid_price + current_market.ask_price) / 2
    if mid == 0 or (current_market.ask_price - current_market.bid_price) / mid > 0.015:
        return signals
    prices = np.array([t.price for t in recent_trades])
    volumes = np.array([t.volume for t in recent_trades], dtype=float)
    total_vol = volumes.sum()
    if total_vol == 0:
        return signals
    vwap = (prices * volumes).sum() / total_vol
    last_price = recent_trades[-1].price
    avg_vol = volumes.mean()
    vol_surge = recent_trades[-1].volume > avg_vol * 1.5
    BUFFER = 0.005  # 50bps for BYMA
    pos = current_position.get(instrument, 0)
    vol = _vol(current_cash, current_market.ask_price)
    if last_price > vwap * (1 + BUFFER) and vol_surge and pos <= 0:
        signals.append({'direction': Direction.BUY, 'volume': vol,
                        'order_type': OrderType.MARKET, 'instrument': instrument})
    elif last_price < vwap * (1 - BUFFER) and vol_surge and pos >= 0:
        signals.append({'direction': Direction.SELL, 'volume': vol,
                        'order_type': OrderType.MARKET, 'instrument': instrument})
    return signals


def byma_mean_reversion(current_market, recent_trades, current_position, current_cash):
    signals = []
    instrument = _instrument(current_market, recent_trades)
    if not instrument or not current_market or len(recent_trades) < 30:
        return signals
    mid = (current_market.bid_price + current_market.ask_price) / 2
    if mid == 0 or (current_market.ask_price - current_market.bid_price) / mid > 0.015:
        return signals
    prices = np.array([t.price for t in recent_trades[-30:]])
    mean, std = prices.mean(), prices.std()
    if std == 0:
        return signals
    last_price = recent_trades[-1].price
    pos = current_position.get(instrument, 0)
    vol = _vol(current_cash, current_market.ask_price)
    if last_price < mean - 2 * std and pos <= 0:
        signals.append({'direction': Direction.BUY, 'volume': vol,
                        'order_type': OrderType.LIMIT, 'price': current_market.ask_price,
                        'instrument': instrument})
    elif last_price > mean + 2 * std and pos >= 0:
        signals.append({'direction': Direction.SELL, 'volume': vol,
                        'order_type': OrderType.LIMIT, 'price': current_market.bid_price,
                        'instrument': instrument})
    return signals


# ---------------------------------------------------------------------------
# Binance strategies — no spread filter (synthetic spread from OHLCV is tiny)
# ---------------------------------------------------------------------------

def binance_vwap(current_market, recent_trades, current_position, current_cash):
    signals = []
    instrument = _instrument(current_market, recent_trades)
    if not instrument or not current_market or len(recent_trades) < 15:
        return signals
    prices = np.array([t.price for t in recent_trades])
    volumes = np.array([t.volume for t in recent_trades], dtype=float)
    total_vol = volumes.sum()
    if total_vol == 0:
        return signals
    vwap = (prices * volumes).sum() / total_vol
    last_price = recent_trades[-1].price
    avg_vol = volumes.mean()
    vol_surge = recent_trades[-1].volume > avg_vol * 1.5
    BUFFER = 0.002  # 20bps for crypto 1-min bars
    pos = current_position.get(instrument, 0)
    vol = _vol(current_cash, current_market.ask_price)
    if last_price > vwap * (1 + BUFFER) and vol_surge and pos <= 0:
        signals.append({'direction': Direction.BUY, 'volume': vol,
                        'order_type': OrderType.MARKET, 'instrument': instrument})
    elif last_price < vwap * (1 - BUFFER) and vol_surge and pos >= 0:
        signals.append({'direction': Direction.SELL, 'volume': vol,
                        'order_type': OrderType.MARKET, 'instrument': instrument})
    return signals


def binance_mean_reversion(current_market, recent_trades, current_position, current_cash):
    signals = []
    instrument = _instrument(current_market, recent_trades)
    if not instrument or not current_market or len(recent_trades) < 20:
        return signals
    prices = np.array([t.price for t in recent_trades[-20:]])
    mean, std = prices.mean(), prices.std()
    if std == 0:
        return signals
    last_price = recent_trades[-1].price
    pos = current_position.get(instrument, 0)
    vol = _vol(current_cash, current_market.ask_price)
    if last_price < mean - 1.5 * std and pos <= 0:
        signals.append({'direction': Direction.BUY, 'volume': vol,
                        'order_type': OrderType.MARKET, 'instrument': instrument})
    elif last_price > mean + 1.5 * std and pos >= 0:
        signals.append({'direction': Direction.SELL, 'volume': vol,
                        'order_type': OrderType.MARKET, 'instrument': instrument})
    return signals
