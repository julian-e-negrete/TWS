"""
Unified Dash dashboard — Tarea 11.1
Migrates finance/dashboard/test/ (Streamlit) to Dash.
Covers: OHLCV price chart, RSI, options chain viewer.
"""
import dash
from dash import dcc, html, Input, Output, dash_table
import plotly.graph_objs as go
from plotly.subplots import make_subplots
import pandas as pd
import yfinance as yf

from finance.utils.logger import logger

app = dash.Dash(__name__, title="AlgoTrading Dashboard")

app.layout = html.Div([
    html.H1("📊 AlgoTrading Dashboard", style={"textAlign": "center"}),

    # Live ticks panel (fed by WebSocket via clientside callback)
    html.Div(id="live-ticks", style={"textAlign": "center", "marginBottom": "10px",
                                      "fontSize": "13px", "color": "#555"}),
    dcc.Store(id="ws-store"),

    html.Div([
        dcc.Input(id="ticker", value="GGAL", debounce=True,
                  placeholder="Ticker...", style={"marginRight": "10px"}),
        dcc.Dropdown(id="period",
                     options=[{"label": v, "value": v} for v in ["5d", "1mo", "3mo", "6mo", "1y"]],
                     value="1mo", clearable=False, style={"width": "120px", "display": "inline-block"}),
        dcc.Dropdown(id="interval",
                     options=[{"label": v, "value": v} for v in ["1h", "1d", "1wk"]],
                     value="1d", clearable=False, style={"width": "120px", "display": "inline-block", "marginLeft": "10px"}),
    ], style={"textAlign": "center", "marginBottom": "20px"}),

    dcc.Graph(id="price-chart"),
    dcc.Graph(id="rsi-chart"),

    html.H2("Options Chain", style={"textAlign": "center", "marginTop": "30px"}),
    html.Div([
        dcc.Dropdown(id="expiry", placeholder="Select expiry...",
                     style={"width": "300px", "margin": "0 auto"}),
    ]),
    html.Div(id="options-tables"),

    dcc.Interval(id="refresh", interval=60_000, n_intervals=0),

    # WebSocket client — connects to ws_server.py and stores data in ws-store
    html.Script("""
        (function() {
            var ws = new WebSocket('ws://localhost:8765');
            ws.onmessage = function(e) {
                var store = document.getElementById('ws-store');
                if (store) store.setAttribute('data-value', e.data);
                // Trigger Dash store update via hidden input
                var el = document.getElementById('_ws_trigger');
                if (el) { el.value = e.data; el.dispatchEvent(new Event('change')); }
            };
        })();
    """),
], style={"fontFamily": "Arial, sans-serif", "maxWidth": "1400px", "margin": "0 auto"})


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

@app.callback(
    Output("price-chart", "figure"),
    Output("rsi-chart", "figure"),
    Output("expiry", "options"),
    Input("ticker", "value"),
    Input("period", "value"),
    Input("interval", "value"),
    Input("refresh", "n_intervals"),
)
def update_charts(ticker, period, interval, _):
    ticker = (ticker or "GGAL").upper()
    try:
        df = yf.download(ticker, period=period, interval=interval, progress=False)
    except Exception as e:
        logger.error("yfinance error: {e}", e=e)
        empty = go.Figure()
        return empty, empty, []

    if df.empty:
        empty = go.Figure()
        return empty, empty, []

    # Flatten MultiIndex columns if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # SMA20
    df["SMA20"] = df["Close"].rolling(20).mean()
    # RSI
    delta = df["Close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    df["RSI"] = 100 - (100 / (1 + gain / loss.replace(0, float("nan"))))

    # Price chart
    price_fig = make_subplots(specs=[[{"secondary_y": True}]])
    price_fig.add_trace(go.Scatter(x=df.index, y=df["Close"], name="Close", line=dict(color="black")))
    price_fig.add_trace(go.Scatter(x=df.index, y=df["SMA20"], name="SMA20", line=dict(color="blue", dash="dash")))
    price_fig.add_trace(go.Bar(x=df.index, y=df["Volume"], name="Volume",
                               marker_color="lightgrey", opacity=0.4), secondary_y=True)
    price_fig.update_layout(title=f"{ticker} Price", height=450,
                             legend=dict(orientation="h", y=1.02, x=1, xanchor="right"))

    # RSI chart
    rsi_fig = go.Figure()
    rsi_fig.add_trace(go.Scatter(x=df.index, y=df["RSI"], name="RSI", line=dict(color="purple")))
    rsi_fig.add_hline(y=70, line_dash="dash", line_color="red", annotation_text="Overbought")
    rsi_fig.add_hline(y=30, line_dash="dash", line_color="green", annotation_text="Oversold")
    rsi_fig.update_layout(title="RSI (14)", height=250, yaxis=dict(range=[0, 100]))

    # Expiry options
    try:
        expiries = list(yf.Ticker(ticker).options)
        expiry_opts = [{"label": e, "value": e} for e in expiries]
    except Exception:
        expiry_opts = []

    return price_fig, rsi_fig, expiry_opts


@app.callback(
    Output("options-tables", "children"),
    Input("ticker", "value"),
    Input("expiry", "value"),
)
def update_options(ticker, expiry):
    if not ticker or not expiry:
        return html.P("Select a ticker and expiry date.", style={"textAlign": "center"})
    try:
        chain = yf.Ticker(ticker.upper()).option_chain(expiry)
        calls = chain.calls[["strike", "lastPrice", "bid", "ask", "volume", "impliedVolatility"]].head(20)
        puts = chain.puts[["strike", "lastPrice", "bid", "ask", "volume", "impliedVolatility"]].head(20)
    except Exception as e:
        return html.P(f"Options data unavailable: {e}", style={"textAlign": "center"})

    def make_table(df, title):
        return html.Div([
            html.H3(title, style={"textAlign": "center"}),
            dash_table.DataTable(
                data=df.round(4).to_dict("records"),
                columns=[{"name": c, "id": c} for c in df.columns],
                style_table={"overflowX": "auto"},
                style_cell={"textAlign": "center"},
                page_size=20,
            )
        ], style={"width": "48%", "display": "inline-block", "verticalAlign": "top"})

    return html.Div([make_table(calls, "Calls"), make_table(puts, "Puts")],
                    style={"display": "flex", "justifyContent": "space-around"})


if __name__ == "__main__":
    from finance.config.settings import settings
    # Register login endpoint
    from flask import request, jsonify
    from finance.dashboard.auth import authenticate, require_role

    @app.server.route("/auth/login", methods=["POST"])
    def login():
        data = request.get_json() or {}
        token = authenticate(data.get("username", ""), data.get("password", ""))
        if not token:
            return jsonify({"error": "Invalid credentials"}), 401
        return jsonify({"token": token})

    @app.server.route("/auth/verify")
    @require_role("admin", "viewer")
    def verify():
        return jsonify({"status": "ok"})

    app.run(host=settings.dashboard.host, port=settings.dashboard.port,
            debug=settings.dashboard.debug)
