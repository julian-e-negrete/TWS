import dash
from dash import dcc, html, Input, Output, State, dash_table
import plotly.graph_objs as go
import pandas as pd
import yfinance as yf
import time

from fetcher import live_data, start_websocket_client, get_options_chain

# Start websocket listener
start_websocket_client()

# Initialize Dash app
app = dash.Dash(__name__)
app.title = "Live Intraday Market Monitor"
app.layout = html.Div([
    html.H1("📈 Intraday Market Dashboard", style={"textAlign": "center"}),

    dcc.Interval(
        id="interval-component",
        interval=60*1000,  # every 60 seconds
        n_intervals=0
    ),

    html.Div(id="graphs-container", style={"textAlign": "center", "marginBottom": "50px"}),

    html.H2("📝 Options Chain Viewer", style={"textAlign": "center", "marginTop": "50px"}),

    html.Div(id="options-chain-tables")
])

# Callback to dynamically generate graphs
@app.callback(
    Output("graphs-container", "children"),
    Input("interval-component", "n_intervals")
)
def update_graphs(n):
    graphs = []

    for ticker, data_list in live_data.items():
        df = pd.DataFrame(data_list)

        if df.empty:
            continue

        df = df.sort_values("timestamp")

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df["timestamp"],
            y=df["Adj Close"],
            mode="lines+markers",
            name=ticker
        ))

        fig.update_layout(
            title=ticker,
            xaxis_title="Time",
            yaxis_title="Price",
            height=300,
            xaxis=dict(tickformat="%H:%M")
        )

        graphs.append(
            html.Div([
                dcc.Graph(figure=fig)
            ], style={
                "display": "inline-block",
                "width": "30%",
                "verticalAlign": "top",
                "padding": "10px"
            })
        )

    return graphs

# Callback to display options chain
@app.callback(
    Output("options-chain-tables", "children"),
    Input("interval-component", "n_intervals")
)
def display_options_chain(n):
    

    # Obtener el options chain
    calls, puts = get_options_chain()
    
    # Retornar las tablas de calls y puts
    return html.Div([
        html.H4("Calls"),
        dash_table.DataTable(
            data=calls.to_dict("records"),
            columns=[{"name": i, "id": i} for i in calls.columns],
            style_table={"overflowX": "auto"},
            page_size=10
        ),
        html.H4("Puts", style={"marginTop": "30px"}),
        dash_table.DataTable(
            data=puts.to_dict("records"),
            columns=[{"name": i, "id": i} for i in puts.columns],
            style_table={"overflowX": "auto"},
            page_size=10
        )
    ])

if __name__ == "__main__":
    app.run(debug=True)
