import threading
import time
from typing import Dict, Any
import dash
from dash import dcc, html, Input, Output, State, no_update
import plotly.graph_objs as go
import pandas as pd
import numpy as np
import dash_bootstrap_components as dbc
import sys

from load_data import load_tick_data, load_order_data
from calcultions import enhanced_order_flow_imbalance
from calcultions import RollingOFITFIProcessor
# --- DATA STORE ---
class DataStore:
    def __init__(self):
        self._data = {}
        self._lock = threading.RLock()
        
    def update(self, new_data: Dict[str, Any]) -> None:
        with self._lock:
            self._data.update(new_data)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

data_store = DataStore()

# --- DATA FEEDER ---
class DataFeeder:
    def __init__(self, tick_data: pd.DataFrame, order_data: pd.DataFrame, processor: Any):
        self.tick_data = tick_data
        self.order_data = order_data
        self.processor = processor
        self.tick_data_list = [] 
        self.order_data_list = []
        self.lock = threading.RLock()
        self.current_index = 0
        self.running = False
        self.feed_speed = 1.0
        
    def start_feeding(self, speed: float = 1.0) -> None:
        if not self.running:
            self.running = True
            self.feed_speed = max(0.1, min(10.0, speed))
            threading.Thread(target=self.feed_data, daemon=True).start()
    
    def stop_feeding(self) -> None:
        self.running = False

    def reset_feeder(self):
        with self.lock:
            self.running = False
            self.current_index = 0
            self.tick_data_list = []
            self.order_data_list = []

    def feed_data(self) -> None:
        while self.running and self.current_index < len(self.tick_data):
            self.process_next_batch()
            time.sleep(max(0.01, 0.5 / self.feed_speed))
    
    def process_next_batch(self) -> None:
        with self.lock:
            if self.current_index >= len(self.tick_data):
                self.running = False
                return
            
            batch_size = max(1, int(self.feed_speed))
            for _ in range(batch_size):
                if self.current_index >= len(self.tick_data): break
                
                row = self.tick_data.iloc[self.current_index]
                update = {
                    'time': row['time'],
                    'bid_price': float(row['bid_price']),
                    'bid_volume': float(row['bid_volume']), 
                    'ask_price': float(row['ask_price']),
                    'ask_volume': float(row['ask_volume']),
                    'last_price': float(row['last_price']),
                }
                self.processor.process_lob_update(update)
                self.tick_data_list.append(update)
                self.current_index += 1

    def get_current_state(self) -> Dict[str, Any]:
        with self.lock:
            return {
                'tick_list': list(self.tick_data_list),
                'current_idx': self.current_index,
                'is_running': self.running
            }

# --- MAIN APP LOGIC ---
def main():
    # 1. Load Data (Initial Static View)
    tick_df = load_tick_data("2025-12-29")
    tick_df['time'] = pd.to_datetime(tick_df['time'])
    order_df = load_order_data("2025-12-29")
    
    proc = RollingOFITFIProcessor(max_updates=len(tick_df), tfi_window_ms=600000)
    feeder = DataFeeder(tick_df, order_df, proc)
    
    app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

    app.layout = html.Div([
        html.H1("Live Construction & Full History Analysis", style={'text-align': 'center', 'padding': '20px'}),
        
        # Control Bar
        dbc.Container([
            dbc.Row([
                dbc.Col(dbc.Button('▶ Start', id='play-btn', color='success', className='w-100'), width=2),
                dbc.Col(dbc.Button('⏸ Pause', id='pause-btn', color='warning', className='w-100'), width=2),
                dbc.Col(dbc.Button('🔄 Reset to Whole View', id='reset-btn', color='danger', className='w-100'), width=3),
                dbc.Col(html.Div(id='status-txt', style={'padding-top': '10px'}), width=5)
            ], className='mb-3'),
            dbc.Row([
                dbc.Col(html.Label("Playback Speed:"), width=2),
                dbc.Col(dcc.Slider(id='speed-sld', min=0.1, max=10, step=0.1, value=1.0, marks={i: f'{i}x' for i in range(1, 11)}), width=10)
            ])
        ], fluid=True, style={'background': '#f8f9fa', 'padding': '20px', 'border-radius': '10px'}),

        # Charts
        dbc.Container([
            dcc.Graph(id='main-price-chart', style={'height': '600px'}),
            dcc.Interval(id='ui-interval', interval=1000)
        ], fluid=True, className='mt-4')
    ])

    # Callback for Controls
    @app.callback(
        Output('status-txt', 'children'),
        [Input('play-btn', 'n_clicks'), 
         Input('pause-btn', 'n_clicks'), 
         Input('reset-btn', 'n_clicks')],
        [State('speed-sld', 'value')]
    )
    def handle_controls(play, pause, reset, speed):
        ctx = dash.callback_context
        if not ctx.triggered: return "System Ready"
        btn_id = ctx.triggered[0]['prop_id'].split('.')[0]
        
        if btn_id == 'play-btn':
            feeder.start_feeding(speed)
            return "Status: Running"
        elif btn_id == 'pause-btn':
            feeder.stop_feeding()
            return "Status: Paused"
        elif btn_id == 'reset-btn':
            feeder.reset_feeder()
            return "Status: Reset to Whole View"
        return no_update

    # Callback for the Chart
    @app.callback(
        Output('main-price-chart', 'figure'),
        Input('ui-interval', 'n_intervals')
    )
    def update_chart(n):
        state = feeder.get_current_state()
        stream_ticks = state['tick_list']
        
        fig = go.Figure()

        # LOGIC: If we are in "Reset" or "Initial" state (no stream data), show whole chart
        if not stream_ticks and state['current_idx'] == 0:
            df_view = tick_df
            title = "Whole Market View (Static)"
            opacity = 1.0
            line_width = 1.5
        else:
            # We are actively constructing/playing
            df_view = pd.DataFrame(stream_ticks)
            df_view['time'] = pd.to_datetime(df_view['time'])
            title = f"Live Construction - Progress: {state['current_idx']} / {len(tick_df)}"
            opacity = 1.0
            line_width = 2

        # Add traces
        fig.add_trace(go.Scatter(
            x=df_view['time'], y=df_view['last_price'],
            name='Last Price', line=dict(color='#1f77b4', width=line_width),
            opacity=opacity
        ))
        
        fig.add_trace(go.Scatter(
            x=df_view['time'], y=df_view['ask_price'],
            name='Ask', line=dict(color='rgba(214, 39, 40, 0.5)', width=1)
        ))
        
        fig.add_trace(go.Scatter(
            x=df_view['time'], y=df_view['bid_price'],
            name='Bid', line=dict(color='rgba(44, 160, 44, 0.5)', width=1),
            fill='tonexty', fillcolor='rgba(0, 0, 0, 0.05)'
        ))

        fig.update_layout(
            title=title,
            template='plotly_white',
            uirevision='constant', # Essential to keep the view stable
            xaxis=dict(
                rangeslider=dict(visible=True), # Adds a mini-map at bottom
                type='date'
            ),
            margin=dict(l=20, r=20, t=50, b=20)
        )
        
        return fig

    app.run(debug=True, port=8050)

if __name__ == '__main__':
    main()