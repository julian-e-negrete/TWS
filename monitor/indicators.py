import ta

def compute_rsi(df):
    rsi_series = ta.momentum.RSIIndicator(close=df['close']).rsi()
    latest_rsi = rsi_series.iloc[-1]
    print(f"[INFO] Latest RSI: {latest_rsi:.2f}")
    return latest_rsi
