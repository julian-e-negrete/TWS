import ta
import pandas as pd
from finance.utils.logger import logger


def compute_rsi(df: pd.DataFrame) -> float:
    rsi = ta.momentum.RSIIndicator(close=df["close"]).rsi().iloc[-1]
    logger.info("RSI={rsi:.2f}", rsi=rsi)
    return rsi
