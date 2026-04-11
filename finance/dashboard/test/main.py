# DEPRECATED — migrated to finance/dashboard/main.py (Dash)
# This Streamlit file is kept for reference only. Do not use.
import streamlit as st
from data.fetcher import get_stock_data, get_options_chain
from indicators.ta_utils import add_indicators
from views.layout import display_price_chart, display_rsi
import yfinance as yf
st.set_page_config(layout="wide")
st.title("📊 Options & Stock Dashboard")

ticker = st.text_input("Enter Stock Ticker:", "GGAL").upper()
period = st.selectbox("Period", ["5d", "1mo", "3mo", "6mo", "1y"])
interval = st.selectbox("Interval", ["1h", "1d", "1wk"])

df = get_stock_data(ticker, period, interval)
if df is not None and not df.empty:
    df = add_indicators(df)
    display_price_chart(df, ticker)
    display_rsi(df)

    st.subheader("Options Chain")
    expiries = list(yf.Ticker(ticker).options)
    expiry = st.selectbox("Expiry Date", expiries)

    calls, puts = get_options_chain(ticker, expiry)
    st.write("Calls")
    st.dataframe(calls)
    
    st.write("Puts")
    st.dataframe(puts)
else:
    st.error("No data available. Check ticker or connection.")
