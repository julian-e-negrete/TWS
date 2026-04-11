"""
Live WebSocket runner — subscribes to Matriz, builds rolling feature window,
calls PPO policy, and either logs signals (paper) or places real orders (live).

Includes:
  - PositionState machine with cooldown + max_position filtering
  - Enhanced paper logging (fill price, simulated P&L, regime, position)
  - Graceful shutdown: flatten position on SIGINT if live

Usage:
    python -m finance.HFT.ml.live_runner --mode paper --instrument DLR
    python -m finance.HFT.ml.live_runner --mode live  --instrument DLR --max_position 2 --cooldown_seconds 10
"""
import argparse
import json
import signal
import sys
import os
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")  # CPU-only, suppress CUDA warning

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

import numpy as np
import pandas as pd
import websocket

from finance.HFT.ml import get_config
from finance.HFT.ml.features import extract_features, FEATURE_COLS
from finance.HFT.ml.rl_agent import load_policy
from finance.HFT.ml.monitoring import MLMonitor
from finance.utils.logger import logger
from finance.utils.db_pool import get_pg_engine
from sqlalchemy import text

INSTRUMENT_TOPICS = {
    'DLR':          None,
    'GGAL':         'md.bm_MERV_GGALD_24hs',
    'GGAL_OPTIONS': None,
    'BTC_MARGIN':   None,
    'CCL_SPREAD':   ['md.bm_MERV_AL30_24hs', 'md.bm_MERV_AL30D_24hs'],
}
MATRIZ_URL = "wss://matriz.eco.xoms.com.ar/ws"

INSTRUMENT_DEFAULTS = {
    'GGAL_OPTIONS': {'max_position': 10,  'cooldown_seconds': 30},
    'BTC_MARGIN':   {'max_position': 1,   'cooldown_seconds': 5},
    'CCL_SPREAD':   {'max_position': 100, 'cooldown_seconds': 10},
}


# ---------------------------------------------------------------------------
# Item 3: Position State Machine
# ---------------------------------------------------------------------------

@dataclass
class PositionState:
    position: int = 0          # negative=short, 0=flat, positive=long
    last_signal_ts: float = 0  # epoch seconds
    pending: bool = False
    max_position: int = 100
    cooldown_seconds: float = 5.0
    simulated_pnl: float = 0.0
    last_entry_price: float = 0.0

    def can_trade(self, action: int, now: float) -> tuple[bool, str]:
        """Returns (allowed, reason). action: 1=BUY, 2=SELL."""
        if self.pending:
            return False, "pending_order"
        if now - self.last_signal_ts < self.cooldown_seconds:
            return False, "cooldown"
        direction = 1 if action == 1 else -1
        new_pos = self.position + direction
        if abs(new_pos) > self.max_position:
            return False, "max_position"
        # No duplicate signals in same direction
        if direction > 0 and self.position > 0:
            return False, "already_long"
        if direction < 0 and self.position < 0:
            return False, "already_short"
        return True, "ok"

    def record_signal(self, action: int, fill_price: float, now: float):
        direction = 1 if action == 1 else -1
        if self.position != 0 and self.last_entry_price > 0:
            self.simulated_pnl += (fill_price - self.last_entry_price) * self.position
        self.position += direction
        self.last_entry_price = fill_price
        self.last_signal_ts = now
        self.pending = True

    def confirm_fill(self):
        self.pending = False

    @property
    def regime_label(self) -> str:
        if self.position > 0:   return 'long'
        if self.position < 0:   return 'short'
        return 'flat'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_dlr_topic() -> str:
    try:
        with get_pg_engine().connect() as conn:
            row = conn.execute(text(
                "SELECT instrument FROM ticks WHERE instrument LIKE '%DDF_DLR%' "
                "ORDER BY time DESC LIMIT 1"
            )).fetchone()
        if row:
            return f"md.{row[0].replace('M:', '')}"
    except Exception as e:
        logger.warning("Could not resolve DLR topic: {e}", e=e)
    return 'md.rx_DDF_DLR_MAR26'


def _resolve_options_topic() -> str:
    """Subscribe to the nearest active GGAL option expiry."""
    try:
        with get_pg_engine().connect() as conn:
            row = conn.execute(text(
                "SELECT ticker FROM ppi_options_chain "
                "WHERE underlying='GGAL' AND expiry > CURRENT_DATE AND volume > 0 "
                "ORDER BY expiry ASC, volume DESC LIMIT 1"
            )).fetchone()
        if row:
            return f"md.bm_MERV_{row[0]}_24hs"
    except Exception as e:
        logger.warning("Could not resolve options topic: {e}", e=e)
    return ''


def _regime_label(obs: np.ndarray) -> str:
    spread_idx = FEATURE_COLS.index('spread_bps')
    vol_idx    = FEATURE_COLS.index('vol_surge_ratio')
    spread = obs[spread_idx]
    vol    = obs[vol_idx]
    s = 'wide' if spread > 20 else 'tight'
    v = 'surge' if vol > 1.5 else 'normal'
    return f"{s}_{v}"


def _save_paper_signal(instrument: str, action: int, signal_price: float,
                       spread: float, state: PositionState, regime: str):
    action_name = {1: 'BUY', 2: 'SELL'}[action]
    half_spread = spread / 2
    fill_price = signal_price + half_spread if action == 1 else signal_price - half_spread
    ts = datetime.now(timezone.utc).isoformat()
    try:
        with get_pg_engine().begin() as conn:
            conn.execute(text("""
                INSERT INTO bt_strategy_runs
                    (instrument, strategy, date, total_return, sharpe, max_drawdown,
                     win_rate, num_trades, profit_factor, expectancy, skipped_trades, metadata)
                VALUES
                    (:instrument, 'ppo_live', CURRENT_DATE, 0, 0, 0, 0, 1, 0, 0, 0,
                     CAST(:meta AS jsonb))
            """), {
                'instrument': instrument,
                'meta': json.dumps({
                    'action': action_name,
                    'signal_price': signal_price,
                    'simulated_fill_price': fill_price,
                    'simulated_pnl': state.simulated_pnl,
                    'position_after_signal': state.position,
                    'regime': regime,
                    'ts': ts,
                }),
            })
    except Exception as e:
        logger.warning("Failed to save paper signal: {e}", e=e)


def _place_live_order(instrument: str, action: int, price: float) -> bool:
    from ppi_client.ppi import PPI
    from finance.PPI.classes.account_ppi import Account
    from ppi_client.models.order import Order
    ppi = PPI(sandbox=False)
    account = Account(ppi)
    side = 'Buy' if action == 1 else 'Sell'
    try:
        order = Order(account.account_number, instrument, side, 1, price, 'LIMIT', 'Day')
        ppi.order.send(order)
        logger.info("Live order sent: {side} {instr} @ {price}", side=side, instr=instrument, price=price)
        return True
    except Exception as e:
        logger.error("Live order failed: {e}", e=e)
        return False


def _flatten_position(instrument: str, state: PositionState, price: float):
    """Send market order to flatten open position."""
    if state.position == 0:
        return
    action = 2 if state.position > 0 else 1  # SELL to close long, BUY to close short
    logger.info("Flattening position {pos} for {instr}", pos=state.position, instr=instrument)
    _place_live_order(instrument, action, price)


def _log_shutdown_pnl(instrument: str, state: PositionState):
    try:
        with get_pg_engine().begin() as conn:
            conn.execute(text("""
                INSERT INTO bt_strategy_runs
                    (instrument, strategy, date, total_return, sharpe, max_drawdown,
                     win_rate, num_trades, profit_factor, expectancy, skipped_trades, metadata)
                VALUES
                    (:instrument, 'ppo_live_shutdown', CURRENT_DATE,
                     :pnl, 0, 0, 0, 0, 0, 0, 0, CAST(:meta AS jsonb))
            """), {
                'instrument': instrument,
                'pnl': state.simulated_pnl,
                'meta': json.dumps({'final_position': state.position,
                                    'ts': datetime.now(timezone.utc).isoformat()}),
            })
    except Exception as e:
        logger.warning("Failed to log shutdown P&L: {e}", e=e)


def _log_position_snapshot(instrument: str, state: PositionState,
                            current_price: float, entry_price: float):
    """Write current position + unrealized P&L to DB every poll cycle for Grafana."""
    direction = 'LONG' if state.position > 0 else ('SHORT' if state.position < 0 else 'FLAT')
    unrealized = (current_price - entry_price) * state.position if entry_price > 0 else 0.0
    try:
        with get_pg_engine().begin() as conn:
            conn.execute(text("""
                INSERT INTO bt_strategy_runs
                    (instrument, strategy, date, total_return, sharpe, max_drawdown,
                     win_rate, num_trades, profit_factor, expectancy, skipped_trades, metadata)
                VALUES
                    (:instrument, 'ppo_live_position', CURRENT_DATE,
                     :pnl, 0, 0, 0, 0, 0, 0, 0, CAST(:meta AS jsonb))
            """), {
                'instrument': instrument,
                'pnl': state.simulated_pnl + unrealized,
                'meta': json.dumps({
                    'direction': direction,
                    'position': state.position,
                    'entry_price': entry_price,
                    'current_price': current_price,
                    'unrealized_pnl': round(unrealized, 2),
                    'realized_pnl': round(state.simulated_pnl, 2),
                    'total_pnl': round(state.simulated_pnl + unrealized, 2),
                    'ts': datetime.now(timezone.utc).isoformat(),
                }),
            })
    except Exception as e:
        logger.warning("Failed to log position snapshot: {e}", e=e)


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

class LiveRunner:
    def __init__(self, instrument_type: str, mode: str,
                 max_position: int, cooldown_seconds: float,
                 model_version: str | None = None):
        self.instrument_type = instrument_type
        self.mode = mode
        self.policy = load_policy(instrument_type, model_version)
        self._mon = MLMonitor(instrument_type)
        self._tick_buf: deque = deque(maxlen=get_config()['features']['rolling_window_size'])
        self._state = PositionState(max_position=max_position, cooldown_seconds=cooldown_seconds)
        self._last_mid: float = 0.0
        self._last_spread: float = 0.0
        self._instrument_name: str = ''
        self._ws = None

    def _on_message(self, ws, message):
        raw = message if not message.startswith('{') else json.loads(message).get('msg', '')
        if not raw.startswith('M:'):
            return
        parts = raw.split('|')
        if len(parts) < 8:
            return
        try:
            bid   = float(parts[3])
            ask   = float(parts[4])
            last  = float(parts[6])
            vol   = int(parts[8]) if len(parts) > 8 and parts[8] else 0
            ts    = pd.Timestamp.now(tz='UTC')
            instr = parts[0].split(':')[1]
        except (ValueError, IndexError):
            return

        self._instrument_name = instr
        self._last_mid    = (bid + ask) / 2
        self._last_spread = ask - bid

        self._tick_buf.append({
            'time': ts, 'bid_price': bid, 'ask_price': ask,
            'bid_volume': int(parts[2]) if parts[2] else 0,
            'ask_volume': int(parts[5]) if parts[5] else 0,
            'total_volume': vol, 'last_price': last, 'instrument': instr,
        })

        window_size = get_config()['features']['rolling_window_size']
        if len(self._tick_buf) < window_size:
            return

        ticks_df  = pd.DataFrame(list(self._tick_buf))
        trades_df = ticks_df[['time', 'last_price', 'total_volume', 'instrument']].copy()
        trades_df['price']  = trades_df['last_price']
        trades_df['volume'] = trades_df['total_volume'].diff().clip(lower=0).fillna(1)
        trades_df['side']   = 'B'
        trades_df = trades_df[['time', 'price', 'volume', 'side', 'instrument']]

        try:
            feat = extract_features(ticks_df, trades_df).fillna(0.0)
            if feat.empty:
                return
            obs = feat.iloc[-1][FEATURE_COLS].values.astype(np.float32)
            action, _ = self.policy.predict(obs, deterministic=True)
            action = int(action)
        except Exception as e:
            logger.warning("Feature/predict error: {e}", e=e)
            return

        if action == 0:
            return

        now = time.time()
        allowed, reason = self._state.can_trade(action, now)
        if not allowed:
            logger.debug("Signal filtered: {reason}", reason=reason)
            return

        action_name = {1: 'BUY', 2: 'SELL'}[action]
        regime = _regime_label(obs)
        logger.info("[{mode}] {instr} → {action} @ {price:.2f} regime={regime} pos={pos}",
                    mode=self.mode.upper(), instr=instr, action=action_name,
                    price=self._last_mid, regime=regime, pos=self._state.position)

        fill_price = self._last_mid + (self._last_spread / 2 if action == 1 else -self._last_spread / 2)
        self._state.record_signal(action, fill_price, now)

        if self.mode == 'paper':
            _save_paper_signal(instr, action, self._last_mid, self._last_spread, self._state, regime)
            self._state.confirm_fill()
        else:
            ok = _place_live_order(instr, action, self._last_mid)
            if ok:
                self._state.confirm_fill()

        self._mon.log_signal(action_name, instr, self._last_mid)
        self._mon.log_position(self._state.position, self._state.simulated_pnl)

    def _on_open(self, ws):
        topic = INSTRUMENT_TOPICS.get(self.instrument_type)
        if topic is None:
            if self.instrument_type == 'DLR':
                topic = _resolve_dlr_topic()
            elif self.instrument_type == 'GGAL_OPTIONS':
                topic = _resolve_options_topic()
        if topic:
            ws.send(json.dumps({"_req": "S", "topicType": "md", "topics": [topic], "replace": True}))
            logger.info("Subscribed to {topic}", topic=topic)

    def _on_error(self, ws, error):
        logger.error("WS error: {e}", e=error)

    def _on_close(self, ws, *_):
        logger.info("WS closed")

    def run(self, session_id: str, conn_id: str):
        url = f"{MATRIZ_URL}?session_id={session_id}&conn_id={conn_id}"
        self._ws = websocket.WebSocketApp(
            url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )

        cfg = get_config()

        def _shutdown(sig, frame):
            logger.info("SIGINT received — shutting down...")
            if self.mode == 'live' and self._state.position != 0 and cfg['live']['flatten_on_shutdown']:
                _flatten_position(self._instrument_name, self._state, self._last_mid)
                deadline = time.time() + 5
                while self._state.pending and time.time() < deadline:
                    time.sleep(0.1)
            _log_shutdown_pnl(self._instrument_name, self._state)
            self._ws.close()
            sys.exit(0)

        signal.signal(signal.SIGINT, _shutdown)
        self._ws.run_forever()


def run_crypto_margin(symbol: str = 'BTCUSDT', leverage: int = 3,
                      mode: str = 'paper', model_version: str | None = None,
                      max_position: int = 1, cooldown_seconds: float = 5.0,
                      monitor=None):
    """
    Live runner for Binance margin using AsyncBinanceMonitor (kline + aggTrade streams).
    Pass an existing monitor instance to share it with binance/monitor/main.py,
    or leave None to create a new one.
    """
    import asyncio
    from finance.HFT.ml.agents.train_crypto import load_policy as load_crypto_policy
    from finance.HFT.ml.features_crypto import extract_crypto_features_live, CRYPTO_FEATURE_COLS
    from finance.BINANCE.monitor.data_stream_async import AsyncBinanceMonitor

    instrument = f'{symbol}_MARGIN_{leverage}X'
    policy = load_crypto_policy(symbol, leverage, model_version)
    state  = PositionState(max_position=max_position, cooldown_seconds=cooldown_seconds)

    # Restore position state from last DB snapshot (survives restarts)
    try:
        with get_pg_engine().connect() as conn:
            snap = conn.execute(text("""
                SELECT metadata FROM bt_strategy_runs
                WHERE strategy='ppo_live_position' AND instrument=:instr
                ORDER BY run_at DESC LIMIT 1
            """), {"instr": instrument}).fetchone()
        if snap:
            import json as _json
            raw = snap[0]
            m = raw if isinstance(raw, dict) else _json.loads(raw)
            state.position = int(m.get('position', 0))
            state.last_entry_price = float(m.get('entry_price', 0))
            state.simulated_pnl = float(m.get('realized_pnl', 0))
            logger.info("Restored position from DB: {dir} @ {entry} pnl={pnl}",
                        dir=m.get('direction'), entry=m.get('entry_price'), pnl=m.get('realized_pnl'))
    except Exception as e:
        logger.warning("Could not restore position from DB: {e}", e=e)

    mon_ml = MLMonitor(instrument)
    own_monitor = monitor is None
    if own_monitor:
        monitor = AsyncBinanceMonitor([symbol])

    logger.info("Crypto margin runner: {instr} mode={mode} leverage={lev}x",
                instr=instrument, mode=mode, lev=leverage)

    async def _policy_loop():
        """Poll monitor data every 60s and fire signals."""
        while True:
            await asyncio.sleep(60)
            try:
                feat = extract_crypto_features_live(symbol, monitor)

                # Always log position snapshot regardless of feature availability
                klines = monitor.data_map.get(symbol)
                price = float(klines['close'].iloc[-1]) if klines is not None and not klines.empty else 0.0
                if price > 0:
                    entry = state.last_entry_price if state.position != 0 else price
                    _log_position_snapshot(instrument, state, price, entry)

                if feat is None:
                    continue

                obs = feat[CRYPTO_FEATURE_COLS].values.astype(np.float32)
                action, _ = policy.predict(obs, deterministic=True)
                action = int(action)

                if action == 0:
                    continue

                now = time.time()
                allowed, reason = state.can_trade(action, now)
                if not allowed:
                    logger.debug("Filtered: {r}", r=reason)
                    continue

                if price == 0:
                    continue

                action_name = {1: 'BUY', 2: 'SELL'}[action]
                ofi = float(feat.get('ofi', 0.0))
                logger.info("[{mode}] {instr} → {action} @ {price:.2f} lev={lev}x OFI={ofi:.3f}",
                            mode=mode.upper(), instr=instrument, action=action_name,
                            price=price, lev=leverage, ofi=ofi)

                fill_price = price * (1.001 if action == 1 else 0.999)
                state.record_signal(action, fill_price, now)

                if mode == 'paper':
                    _save_paper_signal(instrument, action, price, 0.0, state, 'crypto')
                    state.confirm_fill()
                else:
                    ok = _place_live_order(instrument, action, price)
                    if ok:
                        state.confirm_fill()

                mon_ml.log_signal(action_name, instrument, price)
                mon_ml.log_position(state.position, state.simulated_pnl)

            except Exception as e:
                logger.error("Policy loop error: {e}", e=e)

    def _shutdown(sig, frame):
        _log_shutdown_pnl(instrument, state)
        if own_monitor:
            monitor.stop()
        sys.exit(0)
    signal.signal(signal.SIGINT, _shutdown)

    async def _main():
        if own_monitor:
            await asyncio.gather(monitor.start(), _policy_loop())
        else:
            await _policy_loop()

    asyncio.run(_main())


if __name__ == '__main__':
    cfg = get_config()
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode',             default=cfg['live']['default_mode'], choices=['paper', 'live'])
    parser.add_argument('--instrument',       default='DLR',
                        choices=['DLR', 'GGAL', 'GGAL_OPTIONS', 'BTC_MARGIN', 'CCL_SPREAD'])
    parser.add_argument('--session-id',       default='')
    parser.add_argument('--conn-id',          default='')
    parser.add_argument('--max_position',     type=int,   default=None)
    parser.add_argument('--cooldown_seconds', type=float, default=None)
    parser.add_argument('--model_version',    default=None)
    parser.add_argument('--leverage',         type=int,   default=3, help='Leverage for BTC_MARGIN')
    args = parser.parse_args()

    defaults = INSTRUMENT_DEFAULTS.get(args.instrument, {})
    max_pos  = args.max_position     or defaults.get('max_position',     cfg['live']['max_position'])
    cooldown = args.cooldown_seconds or defaults.get('cooldown_seconds', cfg['live']['cooldown_seconds'])

    if args.instrument == 'BTC_MARGIN':
        run_crypto_margin('BTCUSDT', args.leverage, args.mode, args.model_version, max_pos, cooldown)
    else:
        runner = LiveRunner(args.instrument, args.mode, max_pos, cooldown, args.model_version)
        runner.run(args.session_id, args.conn_id)
