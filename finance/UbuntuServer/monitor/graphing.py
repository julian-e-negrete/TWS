import plotly.graph_objects as go

def update_graph(df):
    fig = go.Figure(data=[go.Candlestick(
        x=df['timestamp'],
        open=df['open'],
        high=df['high'],
        low=df['low'],
        close=df['close']
    )])
    fig.update_layout(title='Live USDT/ARS Candlestick', xaxis_rangeslider_visible=False)
    fig.show()
