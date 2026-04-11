"""
HFT Strategies for DLR futures (MatbaRofex).

Each strategy follows the standard signature:
    strategy(current_market, recent_trades, current_position, current_cash) -> list[dict]

All strategies are stateless — state lives in MarketDataBacktester.
"""
import math
import numpy as np
import pandas as pd

from finance.HFT.backtest.types import Direction, OrderType, OrderBookSnapshot, MarketTrade
from finance.HFT.dashboard.calcultions import enhanced_order_flow_imbalance


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _instrument(current_market, recent_trades):
    if current_market:
        return current_market.instrument
    return recent_trades[-1].instrument if recent_trades else None


def _max_volume(instrument, cash, price, multiplier, max_risk_pct=0.68):
    max_risk = max_risk_pct * cash
    return max(1, min(2, math.floor(max_risk / (price * multiplier))))


def _multiplier(instrument):
    return 1000 if 'rx_DDF_DLR' in instrument else 100


# ---------------------------------------------------------------------------
# Strategy 1: OFI (Order Flow Imbalance)
# Buys when buy pressure dominates, sells when sell pressure dominates.
# Uses enhanced_order_flow_imbalance from calcultions.py.
# ---------------------------------------------------------------------------

def ofi_strategy(current_market, recent_trades, current_position, current_cash):
    """
    Order Flow Imbalance strategy.
    Signal: OFI > threshold → BUY, OFI < -threshold → SELL.
    Requires at least 20 recent trades to compute OFI.
    """
    signals = []
    instrument = _instrument(current_market, recent_trades)
    if not instrument or not current_market or len(recent_trades) < 20:
        return signals

    mult = _multiplier(instrument)
    mid = (current_market.bid_price + current_market.ask_price) / 2
    spread = current_market.ask_price - current_market.bid_price
    if spread / mid > 0.003:  # spread > 30bps → skip
        return signals

    # Build trades DataFrame for OFI calculation (needs time + side + volume)
    trades_df = pd.DataFrame([{
        'time': t.timestamp,
        'volume': t.volume,
        'side': 'B' if t.direction == Direction.BUY else 'S',
    } for t in recent_trades])

    ofi_df = enhanced_order_flow_imbalance(trades_df)
    if ofi_df.empty or 'imbalance' not in ofi_df.columns:
        return signals
    ofi = ofi_df['imbalance'].iloc[-1]
    if pd.isna(ofi):
        return signals

    pos = current_position.get(instrument, 0)
    vol = _max_volume(instrument, current_cash, current_market.ask_price, mult)

    OFI_THRESHOLD = 0.3

    if ofi > OFI_THRESHOLD and pos <= 0:
        signals.append({
            'direction': Direction.BUY,
            'volume': vol,
            'order_type': OrderType.MARKET,
            'instrument': instrument,
        })
    elif ofi < -OFI_THRESHOLD and pos >= 0:
        signals.append({
            'direction': Direction.SELL,
            'volume': vol,
            'order_type': OrderType.MARKET,
            'instrument': instrument,
        })

    return signals


# ---------------------------------------------------------------------------
# Strategy 2: Mean Reversion (Bollinger Bands)
# Fades moves that exceed 2 std devs from rolling mean.
# ---------------------------------------------------------------------------

def mean_reversion_strategy(current_market, recent_trades, current_position, current_cash):
    """
    Mean reversion using Bollinger Bands on recent trade prices.
    BUY when price < lower band (oversold), SELL when price > upper band (overbought).
    Window: 30 trades, 2 std devs.
    """
    signals = []
    instrument = _instrument(current_market, recent_trades)
    if not instrument or not current_market or len(recent_trades) < 30:
        return signals

    mult = _multiplier(instrument)
    spread = current_market.ask_price - current_market.bid_price
    mid = (current_market.bid_price + current_market.ask_price) / 2
    if spread / mid > 0.003:
        return signals

    prices = np.array([t.price for t in recent_trades[-30:]])
    mean = prices.mean()
    std = prices.std()
    if std == 0:
        return signals

    upper = mean + 2 * std
    lower = mean - 2 * std
    last_price = recent_trades[-1].price
    pos = current_position.get(instrument, 0)
    vol = _max_volume(instrument, current_cash, current_market.ask_price, mult)

    if last_price < lower and pos <= 0:
        signals.append({
            'direction': Direction.BUY,
            'volume': vol,
            'order_type': OrderType.LIMIT,
            'price': current_market.ask_price,
            'instrument': instrument,
        })
    elif last_price > upper and pos >= 0:
        signals.append({
            'direction': Direction.SELL,
            'volume': vol,
            'order_type': OrderType.LIMIT,
            'price': current_market.bid_price,
            'instrument': instrument,
        })

    return signals


# ---------------------------------------------------------------------------
# Strategy 3: VWAP Momentum
# Trades in the direction of price vs VWAP, filtered by volume surge.
# ---------------------------------------------------------------------------

def vwap_momentum_strategy(current_market, recent_trades, current_position, current_cash):
    """
    VWAP momentum: buy when price > VWAP + buffer AND volume surging.
    Uses volume-weighted average price of recent trades as reference.
    """
    signals = []
    instrument = _instrument(current_market, recent_trades)
    if not instrument or not current_market or len(recent_trades) < 15:
        return signals

    mult = _multiplier(instrument)
    spread = current_market.ask_price - current_market.bid_price
    mid = (current_market.bid_price + current_market.ask_price) / 2
    if spread / mid > 0.003:
        return signals

    prices = np.array([t.price for t in recent_trades])
    volumes = np.array([t.volume for t in recent_trades], dtype=float)
    total_vol = volumes.sum()
    if total_vol == 0:
        return signals

    vwap = (prices * volumes).sum() / total_vol
    last_price = recent_trades[-1].price
    avg_vol = volumes.mean()
    last_vol = recent_trades[-1].volume

    # Volume surge: last trade volume > 1.5x average
    vol_surge = last_vol > avg_vol * 1.5

    BUFFER = 0.0005  # 5bps buffer above/below VWAP
    pos = current_position.get(instrument, 0)
    vol = _max_volume(instrument, current_cash, current_market.ask_price, mult)

    if last_price > vwap * (1 + BUFFER) and vol_surge and pos <= 0:
        signals.append({
            'direction': Direction.BUY,
            'volume': vol,
            'order_type': OrderType.MARKET,
            'instrument': instrument,
        })
    elif last_price < vwap * (1 - BUFFER) and vol_surge and pos >= 0:
        signals.append({
            'direction': Direction.SELL,
            'volume': vol,
            'order_type': OrderType.MARKET,
            'instrument': instrument,
        })

    return signals
