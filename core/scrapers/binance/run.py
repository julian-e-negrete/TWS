# scrapers/binance/run.py — P7 Binance kline monitor / SPEC §1 P7 / T-MOD-1
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
import time
import pandas as pd
from binance import ThreadedWebsocketManager
from logger import get_logger
from fetch import log_ws_message
from notifier import notify
from shared.db_pool import get_conn, put_conn
from shared.models import BinanceTick, BinanceTrade
from pydantic import ValidationError
from config import BINANCE_API_KEY, BINANCE_SECRET_KEY, INTERVAL, LOOKBACK

_log = get_logger("binance")
INSERT_SQL = """
    INSERT INTO binance_ticks (symbol, timestamp, open, high, low, close, volume)
    VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
"""
INSERT_TRADE_SQL = """
    INSERT INTO binance_trades (time, symbol, price, qty, is_buyer_maker, trade_id)
    VALUES (%s, %s, %s, %s, %s, %s)
"""


class BinanceMonitor:
    def __init__(self, symbols: list):
        self.symbols = symbols
        self.data_map = {s: pd.DataFrame() for s in symbols}
        self.last_len = {s: 0 for s in symbols}
        self.twm = None
        self._last_msg = 0

    def _insert(self, tick: BinanceTick):
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(INSERT_SQL, (
                tick.symbol, tick.timestamp,
                tick.open, tick.high, tick.low, tick.close, tick.volume,
            ))
            conn.commit()
        except Exception as e:
            conn.rollback()
            _log.error("DB insert failed: %s", e)
        finally:
            put_conn(conn)

    def _insert_trade(self, trade: BinanceTrade):
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(INSERT_TRADE_SQL, (
                trade.time, trade.symbol, trade.price,
                trade.qty, trade.is_buyer_maker, trade.trade_id,
            ))
            conn.commit()
        except Exception as e:
            conn.rollback()
            _log.error("DB trade insert failed: %s", e)
        finally:
            put_conn(conn)

    def process_trade(self, msg, symbol):
        if msg.get("e") == "error":
            _log.error("WS error on %s: %s — forcing reconnect", symbol, msg)
            self._last_msg = 0
            return
        self._last_msg = time.time()
        if msg.get("e") != "aggTrade":
            return
        try:
            trade = BinanceTrade(
                time=pd.to_datetime(msg["T"], unit="ms"),
                symbol=symbol,
                price=msg["p"],
                qty=msg["q"],
                is_buyer_maker=msg["m"],
                trade_id=msg["a"],
            )
        except Exception as e:
            _log.error("trade validation failed: %s", e)
            return
        self._insert_trade(trade)

    def process_message(self, msg, symbol):
        if msg.get("e") == "error":
            _log.error("WS error on %s: %s — forcing reconnect", symbol, msg)
            self._last_msg = 0
            return
        self._last_msg = time.time()
        log_ws_message("binance", msg)
        if msg.get("e") != "kline":
            return
        k = msg["k"]
        try:
            tick = BinanceTick(
                symbol=symbol,
                timestamp=pd.to_datetime(k["t"], unit="ms"),
                open=k["o"], high=k["h"], low=k["l"], close=k["c"], volume=k["v"],
            )
        except ValidationError as e:
            _log.error("binance tick validation failed: %s", e)
            return

        if float(tick.volume) > 0:
            self._insert(tick)

        df = self.data_map[symbol]
        df = pd.concat([df, pd.DataFrame([tick.model_dump()])]).drop_duplicates(subset="timestamp").tail(LOOKBACK)
        self.data_map[symbol] = df

    def start(self):
        # SPEC §1 P7 — reconnect loop: restart TWM on ReadLoopClosed or stale connection
        while True:
            try:
                import asyncio
                asyncio.set_event_loop(asyncio.new_event_loop())
                self.twm = ThreadedWebsocketManager(api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY)
                self.twm.start()
                for symbol in self.symbols:
                    self.twm.start_kline_socket(
                        callback=lambda msg, s=symbol: self.process_message(msg, s),
                        symbol=symbol.lower(), interval=INTERVAL,
                    )
                    self.twm.start_aggtrade_socket(
                        callback=lambda msg, s=symbol: self.process_trade(msg, s),
                        symbol=symbol.lower(),
                    )
                _log.info("binance WS started for %s", self.symbols)
                self._last_msg = time.time()
                while True:
                    time.sleep(30)
                    if time.time() - self._last_msg > 60:
                        _log.warning("no messages for 120s — reconnecting")
                        break
            except KeyboardInterrupt:
                self.stop()
                return
            except Exception as e:
                _log.error("binance WS error: %s — reconnecting in 10s", e)
            finally:
                try:
                    self.twm.stop()
                except Exception:
                    pass
            time.sleep(10)

    def stop(self):
        if self.twm:
            self.twm.stop()
        _log.info("binance monitor stopped")


def run(symbols=("USDTARS", "BTCUSDT", "ETHARS", "BTCARS", "BNBARS", "USDCUSDT", "ETHUSDT", "ETHUSDC", "SOLUSDT")):
    BinanceMonitor(list(symbols)).start()


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        notify("binance", e)
        raise
