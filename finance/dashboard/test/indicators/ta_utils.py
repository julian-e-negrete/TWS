import pandas_ta as ta

def add_indicators(df):
    df["SMA20"] = ta.sma(df["Close"], length=20)
    df["RSI"] = ta.rsi(df["Close"])
    df["EMA12"] = ta.ema(df["Close"], length=12)
    df["MACD"] = ta.macd(df["Close"])["MACD_12_26_9"]
    return df
