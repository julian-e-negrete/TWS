# DEPRECATED — migrated to finance/dashboard/main.py (Dash)
import streamlit as st
import plotly.graph_objs as go
from plotly.subplots import make_subplots

def display_price_chart(df, ticker):
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Price and SMA20 on primary y-axis
    fig.add_trace(go.Scatter(x=df.index, y=df['Close'], name="Price", line=dict(color="black")), secondary_y=False)
    if "SMA20" in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df["SMA20"], name="SMA20", line=dict(color="blue")), secondary_y=False)

    # Volume on secondary y-axis (as bar)
    #fig.add_trace(go.Bar(x=df.index, y=df['volume'], name="Volume", marker_color='lightgrey', opacity=0.5), secondary_y=True)

    # Layout
    fig.update_layout(
        title=f"{ticker} Price and Volume",
        xaxis_title="Date",
        yaxis_title="Price",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        bargap=0,
        height=600,
    )

    fig.update_yaxes(title_text="Price", secondary_y=False)
    #fig.update_yaxes(title_text="Volume", secondary_y=True)

    st.plotly_chart(fig, use_container_width=True)

def display_rsi(df):
    st.subheader("RSI")
    st.line_chart(df["RSI"])
