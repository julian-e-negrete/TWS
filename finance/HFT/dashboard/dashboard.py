import dash
from dash import dcc, html, Input, Output

import plotly.graph_objs as go
import pandas as pd
import threading
import time


from load_data import load_tick_data, load_order_data
from calcultions import enhanced_order_flow_imbalance
from calcultions import RollingOFITFIProcessor
# Load sample data
tick_data = load_tick_data("2025-12-29")
order_data = load_order_data("2025-12-29")
ofi_data = enhanced_order_flow_imbalance(order_data, window='5min')  # or '1min', '5min' etc.

# At the top, after loading initial data
tick_data_list = []
order_data_list = []


# Example: after loading your dataframes
ofi_tfi_processor = RollingOFITFIProcessor(max_updates=10000, tfi_window_ms=200)
lock = threading.Lock()
# Process LOB updates (tick data)
for _, row in tick_data.iterrows():
    update = {
        'time': row['time'],
        'bid_price': row['bid_price'],
        'bid_size': row['bid_volume'],
        'ask_price': row['ask_price'],
        'ask_size': row['ask_volume'],
    }
    ofi_tfi_processor.process_lob_update(update)

# Process trades (trade data)
for _, row in order_data.iterrows():
    trade = {
        'time': row['time'],
        'side': row['side'],
        'volume': row['volume'],
    }
    ofi_tfi_processor.process_trade(trade)
    
app = dash.Dash(__name__)

app.layout = html.Div([
    html.H1("AGO25 Futures Microstructure Analysis"),
    
    # Price & Spread Section
    html.Div([
        html.H2("Price & Spread"),
        dcc.Graph(id='price-spread-chart'),
        dcc.Interval(id='price-interval', interval=1000)
    ], style={'margin': '20px 0', 'border': '1px solid #ddd', 'padding': '20px', 'borderRadius': '5px'}),
    
    # Order Flow Section
    html.Div([
        html.H2("Order Flow"),
        dcc.Dropdown(
            id='time-window',
            options=[{'label': w, 'value': w} for w in ['1S', '10S', '1min', '5min']],  # Changed 'T' to 'min'
            value='5min',
            style={'width': '200px', 'marginBottom': '20px'}
        ),
        dcc.Graph(id='order-flow-chart')
    ], style={'margin': '20px 0', 'border': '1px solid #ddd', 'padding': '20px', 'borderRadius': '5px'}),
    
    # Depth Analysis Section
    html.Div([
        html.H2("Depth Analysis"),
        html.Div([  # Wrapped slider in a div to apply styles
            dcc.Slider(
                id='depth-time',
                min=0,
                max=len(tick_data)-1,
                value=0,
                marks={i: str(tick_data.iloc[i]['time'].time()) for i in range(0, len(tick_data), len(tick_data)//10)}
            )
        ], style={'marginBottom': '20px'}),
        dcc.Graph(id='depth-chart')
    ], style={'margin': '20px 0', 'border': '1px solid #ddd', 'padding': '20px', 'borderRadius': '5px'}),
    
    # OFI and TFI Stats
    html.Div([
        html.H2("OFI and TFI Statistics"),
        html.Div(id='ofi-tfi-stats'),
        dcc.Interval(id='interval-component', interval=1000, n_intervals=0),
    ], style={'margin': '20px 0', 'border': '1px solid #ddd', 'padding': '20px', 'borderRadius': '5px'})
])

# Price and Spread Chart
@app.callback(
    Output('price-spread-chart', 'figure'),
    Input('price-interval', 'n_intervals')
)
def update_price_chart(n):
    fig = go.Figure()
    
    # Price line
    fig.add_trace(go.Scatter(
        x=tick_data['time'],
        y=tick_data['last_price'],
        name='Price',
        line=dict(color='blue')
    ))
    
    # Spread area
    fig.add_trace(go.Scatter(
        x=tick_data['time'],
        y=tick_data['ask_price'],
        name='Ask',
        line=dict(color='red')
    ))
    
    fig.add_trace(go.Scatter(
        x=tick_data['time'],
        y=tick_data['bid_price'],
        name='Bid',
        line=dict(color='green'),
        fill='tonexty'
    ))
    
    fig.update_layout(title='Price with Bid-Ask Spread')
    return fig

# Order Flow Chart
@app.callback(
    Output('order-flow-chart', 'figure'),
    Input('time-window', 'value')
)
def update_order_flow_chart(window):
    ofi = enhanced_order_flow_imbalance(order_data, window)
    
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=ofi.index,
        y=ofi['buy_volume'],
        name='Buy Volume',
        marker_color='green'
    ))
    fig.add_trace(go.Bar(
        x=ofi.index,
        y=ofi['sell_volume'],
        name='Sell Volume',
        marker_color='red'
    ))
    fig.add_trace(go.Scatter(
        x=ofi.index,
        y=ofi['imbalance'],
        name='Flow Imbalance',
        yaxis='y2',
        line=dict(color='purple')
    ))
    
    fig.update_layout(
        title=f'Order Flow Imbalance ({window} window)',
        yaxis2=dict(
            title='Imbalance',
            overlaying='y',
            side='right',
            range=[-1, 1]
        )
    )
    return fig

# Depth Chart
@app.callback(
    Output('depth-chart', 'figure'),
    Input('depth-time', 'value')
)
def update_depth_chart(idx):
    snapshot = tick_data.iloc[idx]
    
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=['Bid', 'Ask'],
        y=[snapshot['bid_volume'], snapshot['ask_volume']],
        marker_color=['green', 'red']
    ))
    
    fig.update_layout(
        title=f'Market Depth at {snapshot["time"]}',
        xaxis_title='Side',
        yaxis_title='Volume'
    )
    return fig

# OFI and TFI Statistics
@app.callback(
    Output('ofi-tfi-stats', 'children'),
    [Input('interval-component', 'n_intervals')]
)
def update_ofi_tfi_stats(n):
    with lock:
        features = ofi_tfi_processor.snapshot_features()
    return [
        html.Div(f"Order Flow Imbalance: {features['ofi']:.2f}"),
        html.Div(f"Trade Flow Imbalance: {features['tfi']:.2f}"),
        html.Div(f"Spread: {features['spread']:.2f}"),
        html.Div(f"Microprice: {features['microprice']:.2f}"),
    ]
    
    
    
def feed_data_real_time():
    for i in range(len(tick_data)):
        with lock:
            update = {
                'time': tick_data.iloc[i]['time'],
                'bid_price': tick_data.iloc[i]['bid_price'],
                'bid_size': tick_data.iloc[i]['bid_volume'],
                'ask_price': tick_data.iloc[i]['ask_price'],
                'ask_size': tick_data.iloc[i]['ask_volume'],
                'last_price': tick_data.iloc[i]['last_price'],
            }
            ofi_tfi_processor.process_lob_update(update)
            tick_data_list.append(update)  # <-- append new tick


        
            trade_row = order_data.iloc[i]
            trade = {
                'time': trade_row['time'],
                'side': trade_row['side'],
                'volume': trade_row['volume'],
            }
            ofi_tfi_processor.process_trade(trade)
            order_data_list.append(trade)  # <-- append new trade


        time.sleep(30)  # control the feed rate (adjust as needed)

if __name__ == '__main__':
    threading.Thread(target=feed_data_real_time, daemon=True).start()

    app.run(debug=True)


