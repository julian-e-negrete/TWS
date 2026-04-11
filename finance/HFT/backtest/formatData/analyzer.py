import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Tuple, Dict, Any, Optional

def analyze_orderbook_data(data):
    """Comprehensive analysis of order book data"""
    df = pd.DataFrame(data)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df.set_index('timestamp', inplace=True)
    df = df.sort_index()
    
    # Ensure numeric columns are clean
    for col in ['bid_price', 'ask_price', 'bid_size', 'ask_size', 'last_price', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # Drop rows with NaN in key columns
    df = df.dropna(subset=['bid_price', 'ask_price', 'bid_size', 'ask_size'])
    
    df['spread'] = df['ask_price'] - df['bid_price']
    df['mid_price'] = (df['ask_price'] + df['bid_price']) / 2
    df['order_imbalance'] = (df['bid_size'] - df['ask_size']) / (df['bid_size'] + df['ask_size']).replace(0, np.nan)  # Avoid division by zero
    df['mid_returns'] = np.log(df['mid_price'] / df['mid_price'].shift(1))
    rolling_window = min(10, len(df) // 4)
    df['rolling_volatility'] = df['mid_returns'].rolling(window=rolling_window).std()
    
    trades_df = df[df['side'].isin(['BUY', 'SELL'])].copy()
    return df, trades_df

def create_interactive_plots(df, trades_df):
    """Create interactive Plotly subplots"""
    fig = make_subplots(rows=5, cols=2, 
                        subplot_titles=('Order Book Prices and Trade Activity', 'Bid-Ask Spread Over Time',
                                       'Liquidity at Best Bid', 'Liquidity at Best Ask',
                                       'Order Imbalance Analysis', 'Rolling Volatility of Mid Price',
                                       'Cumulative Trading Volume', 'Individual Trade Sizes',
                                       'Distribution of Mid Prices', 'Distribution of Bid-Ask Spreads'))

    # 1. Price and Trade Activity
    fig.add_trace(go.Scatter(x=df.index, y=df['bid_price'], name='Bid Price', mode='lines+markers', marker=dict(color='green')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['ask_price'], name='Ask Price', mode='lines+markers', marker=dict(color='red')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['last_price'], name='Last Price', mode='markers', marker=dict(color='blue')), row=1, col=1)
    if len(trades_df) > 0:
        buy_mask = trades_df['side'] == 'BUY'
        sell_mask = trades_df['side'] == 'SELL'
        fig.add_trace(go.Scatter(x=trades_df[buy_mask].index, y=trades_df[buy_mask]['last_price'] * 1.0003, 
                                name='Buy Trades', mode='markers', marker=dict(color='lime', symbol='triangle-up')), row=1, col=1)
        fig.add_trace(go.Scatter(x=trades_df[sell_mask].index, y=trades_df[sell_mask]['last_price'] * 0.9997, 
                                name='Sell Trades', mode='markers', marker=dict(color='lightcoral', symbol='triangle-down')), row=1, col=1)

    # 2. Spread Analysis
    fig.add_trace(go.Scatter(x=df.index, y=df['spread'], name='Bid-Ask Spread', mode='lines', line=dict(color='purple')), row=1, col=2)
    fig.add_trace(go.Scatter(x=[df.index.min(), df.index.max()], y=[df['spread'].mean(), df['spread'].mean()], 
                            name=f'Avg Spread: {df["spread"].mean():.4f}', mode='lines', line=dict(color='orange', dash='dash')), row=1, col=2)

    # 3. Liquidity at Best Bid
    fig.add_trace(go.Scatter(x=df.index, y=df['bid_size'], name='Bid Size', mode='lines', line=dict(color='darkgreen')), row=2, col=1)

    # 4. Liquidity at Best Ask
    fig.add_trace(go.Scatter(x=df.index, y=df['ask_size'], name='Ask Size', mode='lines', line=dict(color='darkred')), row=2, col=2)

    # 5. Order Imbalance
    fig.add_trace(go.Scatter(x=df.index, y=df['order_imbalance'], name='Order Imbalance', mode='lines', line=dict(color='orange')), row=3, col=1)
    fig.add_trace(go.Scatter(x=[df.index.min(), df.index.max()], y=[0, 0], name='Zero Line', mode='lines', line=dict(color='black', dash='dash')), row=3, col=1)
    fig.add_trace(go.Bar(x=df.index, y=np.where(df['order_imbalance'] >= 0, df['order_imbalance'], 0), name='Buy Pressure', 
                        marker_color='green', opacity=0.3), row=3, col=1)
    fig.add_trace(go.Bar(x=df.index, y=np.where(df['order_imbalance'] < 0, df['order_imbalance'], 0), name='Sell Pressure', 
                        marker_color='red', opacity=0.3), row=3, col=1)

    # 6. Volatility
    if not df['rolling_volatility'].isna().all():
        fig.add_trace(go.Scatter(x=df.index, y=df['rolling_volatility'], name='Rolling Volatility', mode='lines', line=dict(color='brown')), row=3, col=2)

    # 7. Cumulative Volume
    fig.add_trace(go.Scatter(x=df.index, y=df['volume'], name='Cumulative Volume', mode='lines', line=dict(color='teal')), row=4, col=1)

    # 8. Trade Sizes
    if len(trades_df) > 0:
        trades_df['trade_size'] = trades_df['volume'].diff().fillna(0).clip(lower=0)
        buy_trades = trades_df[trades_df['side'] == 'BUY']
        sell_trades = trades_df[trades_df['side'] == 'SELL']
        if len(buy_trades) > 0:
            fig.add_trace(go.Scatter(x=buy_trades.index, y=buy_trades['trade_size'], name='Buy Trade Size', mode='markers', 
                                    marker=dict(color='green', symbol='triangle-up')), row=4, col=2)
        if len(sell_trades) > 0:
            fig.add_trace(go.Scatter(x=sell_trades.index, y=sell_trades['trade_size'], name='Sell Trade Size', mode='markers', 
                                    marker=dict(color='red', symbol='triangle-down')), row=4, col=2)

    # 9. Mid Price Distribution
    mid_price_data = df['mid_price'].dropna()
    if not mid_price_data.empty and mid_price_data.dtype in [np.float64, np.float32, np.int64, np.int32]:
        fig.add_trace(go.Histogram(x=mid_price_data, name='Mid Price', marker_color='skyblue', opacity=0.7), row=5, col=1)
        last_hist = fig.data[-1]
        if last_hist and hasattr(last_hist, 'y') and last_hist.y is not None and len(last_hist.y) > 0:
            max_height = max(last_hist.y)
            fig.add_trace(go.Scatter(x=[mid_price_data.mean(), mid_price_data.mean()], y=[0, max_height], 
                                    name=f'Mean: {mid_price_data.mean():.4f}', mode='lines', line=dict(color='red', dash='dash')), row=5, col=1)
            fig.add_trace(go.Scatter(x=[mid_price_data.median(), mid_price_data.median()], y=[0, max_height], 
                                    name=f'Median: {mid_price_data.median():.4f}', mode='lines', line=dict(color='green', dash='dash')), row=5, col=1)
        else:
            print("Warning: Histogram for Mid Price has no valid data. Skipping mean/median lines.")
    else:
        print("Warning: df['mid_price'] is empty or invalid after cleaning. Skipping Mid Price Distribution.")

    # 10. Spread Distribution
    spread_data = df['spread'].dropna()
    if not spread_data.empty and spread_data.dtype in [np.float64, np.float32, np.int64, np.int32]:
        fig.add_trace(go.Histogram(x=spread_data, name='Bid-Ask Spread', marker_color='purple', opacity=0.7), row=5, col=2)
        last_hist = fig.data[-1]
        if last_hist and hasattr(last_hist, 'y') and last_hist.y is not None and len(last_hist.y) > 0:
            max_height = max(last_hist.y)
            fig.add_trace(go.Scatter(x=[spread_data.mean(), spread_data.mean()], y=[0, max_height], 
                                    name=f'Mean: {spread_data.mean():.4f}', mode='lines', line=dict(color='orange', dash='dash')), row=5, col=2)
        else:
            print("Warning: Histogram for Spread has no valid data. Skipping mean line.")
    else:
        print("Warning: df['spread'] is empty or invalid after cleaning. Skipping Spread Distribution.")

    fig.update_layout(height=1200, width=1000, title_text="Comprehensive Order Book Analysis", showlegend=True)
    fig.update_xaxes(matches='x')  # Sync x-axes across subplots
    fig.show()
    fig.write_html("order_book_analysis.html")  # Save as interactive HTML

def print_statistical_summary(df, trades_df):
    """Print comprehensive statistical summary"""
    print("=" * 60)
    print("COMPREHENSIVE ORDER BOOK ANALYSIS SUMMARY")
    print("=" * 60)
    
    print(f"\n1. DATA OVERVIEW:")
    print(f"   Total observations: {len(df):,}")
    print(f"   Time period: {df.index.min()} to {df.index.max()}")
    print(f"   Duration: {df.index.max() - df.index.min()}")
    
    print(f"\n2. PRICE STATISTICS:")
    print(f"   Mid Price - Mean: {df['mid_price'].mean():.6f}")
    print(f"   Mid Price - Std: {df['mid_price'].std():.6f}")
    print(f"   Mid Price - Min: {df['mid_price'].min():.6f}")
    print(f"   Mid Price - Max: {df['mid_price'].max():.6f}")
    print(f"   Price Range: {df['mid_price'].max() - df['mid_price'].min():.6f}")
    
    print(f"\n3. SPREAD STATISTICS:")
    print(f"   Spread - Mean: {df['spread'].mean():.6f}")
    print(f"   Spread - Std: {df['spread'].std():.6f}")
    print(f"   Spread - Min: {df['spread'].min():.6f}")
    print(f"   Spread - Max: {df['spread'].max():.6f}")
    
    print(f"\n4. LIQUIDITY STATISTICS:")
    print(f"   Avg Bid Size: {df['bid_size'].mean():.2f}")
    print(f"   Avg Ask Size: {df['ask_size'].mean():.2f}")
    print(f"   Max Bid Size: {df['bid_size'].max():.2f}")
    print(f"   Max Ask Size: {df['ask_size'].max():.2f}")
    
    print(f"\n5. TRADE ACTIVITY:")
    print(f"   Total inferred trades: {len(trades_df):,}")
    if len(trades_df) > 0:
        trade_counts = trades_df['side'].value_counts()
        print(f"   Buy trades: {trade_counts.get('BUY', 0):,}")
        print(f"   Sell trades: {trade_counts.get('SELL', 0):,}")
        trades_sorted = trades_df.sort_index()
        trade_sizes = trades_sorted['volume'].diff().dropna()
        if len(trade_sizes) > 0:
            print(f"   Avg trade size: {trade_sizes.mean():.2f}")
            print(f"   Largest trade: {trade_sizes.max():.2f}")
    
    print(f"\n6. VOLATILITY:")
    if not df['rolling_volatility'].isna().all():
        print(f"   Avg rolling volatility: {df['rolling_volatility'].mean():.6f}")
        print(f"   Max volatility: {df['rolling_volatility'].max():.6f}")
    
    print(f"\n7. ORDER IMBALANCE:")
    print(f"   Avg imbalance: {df['order_imbalance'].mean():.4f}")
    print(f"   Time with buy pressure (imbalance > 0): {len(df[df['order_imbalance'] > 0])/len(df)*100:.1f}%")
    print(f"   Time with sell pressure (imbalance < 0): {len(df[df['order_imbalance'] < 0])/len(df)*100:.1f}%")
    
    print("\n" + "=" * 60)

def identify_key_events(df, trades_df):
    """Identify and report key market events"""
    print("\nKEY MARKET EVENTS IDENTIFIED:")
    print("-" * 40)
    
    # 1. Largest spread events
    largest_spreads = df.nlargest(3, 'spread')
    for i, (idx, row) in enumerate(largest_spreads.iterrows(), 1):
        print(f"{i}. Largest Spread: {row['spread']:.4f} at {idx}")
        print(f"   Bid: {row['bid_price']} @ {row['bid_size']}, Ask: {row['ask_price']} @ {row['ask_size']}")
    
    # 2. Significant price moves
    price_changes = df['mid_price'].diff().abs()
    large_moves = price_changes.nlargest(3)
    for i, (idx, change) in enumerate(large_moves.items(), 1):
        if not pd.isna(change):
            print(f"{i+3}. Large Price Move: {change:.4f} at {idx}")
    
    # 3. Liquidity crunches
    low_bid_liquidity = df.nsmallest(3, 'bid_size')
    low_ask_liquidity = df.nsmallest(3, 'ask_size')
    
    for i, (idx, row) in enumerate(low_bid_liquidity.iterrows(), 1):
        print(f"{i+6}. Low Bid Liquidity: {row['bid_size']} @ {idx}")
    
    for i, (idx, row) in enumerate(low_ask_liquidity.iterrows(), 1):
        print(f"{i+9}. Low Ask Liquidity: {row['ask_size']} @ {idx}")

def generate_trading_signals(df: pd.DataFrame, 
                           config: Dict[str, Any] = None) -> pd.DataFrame:
    """
    Generate trading signals based on multiple technical indicators with configurable parameters.
    
    Args:
        df: DataFrame containing price data and indicators
        config: Dictionary with configuration parameters for signal thresholds
        
    Returns:
        DataFrame with trading signals and signal strengths
    """
    # Default configuration
    default_config = {
        'breakout_zscore': 2.0,
        'volatility_zscore': 1.5,
        'imbalance_threshold': 0.2,
        'spread_zscore': 2.0,
        'volatility_window': 20,
        'signal_smoothing': 5
    }
    
    config = {**default_config, **(config or {})}
    
    signals = pd.DataFrame(index=df.index, columns=['signal', 'signal_strength'])
    signals['signal'] = 0  # 0: hold, 1: buy, -1: sell
    signals['signal_strength'] = 0.0
    
    # Validate required columns
    required_cols = ['mid_price', 'rolling_volatility', 'order_imbalance', 'spread']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")
    
    # 1. Breakout Signal (large price move with volume confirmation)
    price_changes = df['mid_price'].diff().abs()
    large_move_threshold = price_changes.rolling(window=config['volatility_window']).mean() + \
                          config['breakout_zscore'] * price_changes.rolling(window=config['volatility_window']).std()
    
    breakout_mask = (price_changes > large_move_threshold)
    signals.loc[breakout_mask, 'signal'] = np.where(
        df['mid_price'].diff() > 0, 1, -1
    )
    signals.loc[breakout_mask, 'signal_strength'] = (
        price_changes / large_move_threshold
    ).clip(0, 3)
    
    # 2. Mean Reversion Signal (high volatility with imbalance)
    high_vol_threshold = df['rolling_volatility'].rolling(window=config['volatility_window']).mean() + \
                        config['volatility_zscore'] * df['rolling_volatility'].rolling(window=config['volatility_window']).std()
    
    # Sell signal: high volatility + negative imbalance (oversold)
    sell_mask = (df['rolling_volatility'] > high_vol_threshold) & \
               (df['order_imbalance'] < -config['imbalance_threshold'])
    signals.loc[sell_mask, 'signal'] = -1
    signals.loc[sell_mask, 'signal_strength'] = (
        (df['rolling_volatility'] / high_vol_threshold) * 
        (df['order_imbalance'].abs() / config['imbalance_threshold'])
    ).clip(0, 3)
    
    # Buy signal: high volatility + positive imbalance (overbought)
    buy_mask = (df['rolling_volatility'] > high_vol_threshold) & \
              (df['order_imbalance'] > config['imbalance_threshold'])
    signals.loc[buy_mask, 'signal'] = 1
    signals.loc[buy_mask, 'signal_strength'] = (
        (df['rolling_volatility'] / high_vol_threshold) * 
        (df['order_imbalance'] / config['imbalance_threshold'])
    ).clip(0, 3)
    
    # 3. Arbitrage Opportunity (wide spread with mean reversion expectation)
    spread_threshold = df['spread'].rolling(window=config['volatility_window']).mean() + \
                      config['spread_zscore'] * df['spread'].rolling(window=config['volatility_window']).std()
    
    spread_mask = (df['spread'] > spread_threshold)
    signals.loc[spread_mask, 'signal'] = 1  # Buy expecting spread to narrow
    signals.loc[spread_mask, 'signal_strength'] = (
        df['spread'] / spread_threshold
    ).clip(0, 3)
    
    # Smooth signals to avoid whipsaws
    if config['signal_smoothing'] > 1:
        signals['signal_smoothed'] = signals['signal'].rolling(
            window=config['signal_smoothing'], 
            min_periods=1
        ).mean()
        signals['signal'] = np.where(
            signals['signal_smoothed'].abs() > 0.5,
            np.sign(signals['signal_smoothed']),
            0
        ).astype(int)
    
    return signals

def generate_trading_signals(df: pd.DataFrame, 
                           config: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    """
    Generate trading signals based on multiple technical indicators with configurable parameters.
    
    Args:
        df: DataFrame containing price data and indicators
        config: Dictionary with configuration parameters for signal thresholds
        
    Returns:
        DataFrame with trading signals and signal strengths
    """
    # Default configuration
    default_config = {
        'breakout_zscore': 2.0,
        'volatility_zscore': 1.5,
        'imbalance_threshold': 0.2,
        'spread_zscore': 2.0,
        'volatility_window': 20,
        'signal_smoothing': 5
    }
    
    config = {**default_config, **(config or {})}
    
    signals = pd.DataFrame(index=df.index, columns=['signal', 'signal_strength'])
    signals['signal'] = 0  # 0: hold, 1: buy, -1: sell
    signals['signal_strength'] = 0.0
    
    # Validate required columns
    required_cols = ['mid_price', 'rolling_volatility', 'order_imbalance', 'spread']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")
    
    # 1. Breakout Signal (large price move with volume confirmation)
    price_changes = df['mid_price'].diff().abs()
    large_move_threshold = price_changes.rolling(window=config['volatility_window']).mean() + \
                          config['breakout_zscore'] * price_changes.rolling(window=config['volatility_window']).std()
    
    breakout_mask = (price_changes > large_move_threshold)
    
    # Fix: Create signal values array first, then assign
    breakout_signals = pd.Series(0, index=df.index)
    breakout_signals.loc[breakout_mask & (df['mid_price'].diff() > 0)] = 1
    breakout_signals.loc[breakout_mask & (df['mid_price'].diff() < 0)] = -1
    
    signals.loc[breakout_mask, 'signal'] = breakout_signals.loc[breakout_mask]
    signals.loc[breakout_mask, 'signal_strength'] = (
        price_changes[breakout_mask] / large_move_threshold[breakout_mask]
    ).clip(0, 3)
    
    # 2. Mean Reversion Signal (high volatility with imbalance)
    high_vol_threshold = df['rolling_volatility'].rolling(window=config['volatility_window']).mean() + \
                        config['volatility_zscore'] * df['rolling_volatility'].rolling(window=config['volatility_window']).std()
    
    # Sell signal: high volatility + negative imbalance (oversold)
    sell_mask = (df['rolling_volatility'] > high_vol_threshold) & \
               (df['order_imbalance'] < -config['imbalance_threshold'])
    signals.loc[sell_mask, 'signal'] = -1
    signals.loc[sell_mask, 'signal_strength'] = (
        (df.loc[sell_mask, 'rolling_volatility'] / high_vol_threshold[sell_mask]) * 
        (df.loc[sell_mask, 'order_imbalance'].abs() / config['imbalance_threshold'])
    ).clip(0, 3)
    
    # Buy signal: high volatility + positive imbalance (overbought)
    buy_mask = (df['rolling_volatility'] > high_vol_threshold) & \
              (df['order_imbalance'] > config['imbalance_threshold'])
    signals.loc[buy_mask, 'signal'] = 1
    signals.loc[buy_mask, 'signal_strength'] = (
        (df.loc[buy_mask, 'rolling_volatility'] / high_vol_threshold[buy_mask]) * 
        (df.loc[buy_mask, 'order_imbalance'] / config['imbalance_threshold'])
    ).clip(0, 3)
    
    # 3. Arbitrage Opportunity (wide spread with mean reversion expectation)
    spread_threshold = df['spread'].rolling(window=config['volatility_window']).mean() + \
                      config['spread_zscore'] * df['spread'].rolling(window=config['volatility_window']).std()
    
    spread_mask = (df['spread'] > spread_threshold)
    signals.loc[spread_mask, 'signal'] = 1  # Buy expecting spread to narrow
    signals.loc[spread_mask, 'signal_strength'] = (
        df.loc[spread_mask, 'spread'] / spread_threshold[spread_mask]
    ).clip(0, 3)
    
    # Smooth signals to avoid whipsaws
    if config['signal_smoothing'] > 1:
        signals['signal_smoothed'] = signals['signal'].rolling(
            window=config['signal_smoothing'], 
            min_periods=1
        ).mean()
        signals['signal'] = np.where(
            signals['signal_smoothed'].abs() > 0.5,
            np.sign(signals['signal_smoothed']),
            0
        ).astype(int)
        signals.drop('signal_smoothed', axis=1, inplace=True)
    
    return signals

def simulate_strategy(df: pd.DataFrame, 
                     signals: pd.DataFrame,
                     initial_capital: float = 100000,
                     transaction_cost: float = 0.001,
                     position_sizing: str = 'full') -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Simulate trading strategy with realistic constraints and costs.
    
    Args:
        df: Price data DataFrame
        signals: Signals DataFrame from generate_trading_signals
        initial_capital: Starting capital
        transaction_cost: Percentage cost per trade (bid-ask spread + commissions)
        position_sizing: 'full' for all-in, 'fixed' for fixed size, 'percent' for percentage of capital
        
    Returns:
        Tuple of (portfolio_df, trades_df)
    """
    portfolio = []
    position = 0
    capital = initial_capital
    trades = []
    
    # Ensure we have unique timestamps
    unique_timestamps = df.index.unique()
    
    for i, timestamp in enumerate(unique_timestamps):
        try:
            # Get current data
            current_data = df.loc[timestamp]
            if isinstance(current_data, pd.DataFrame):
                current_row = current_data.iloc[0]
            else:
                current_row = current_data
            
            current_price = current_row['mid_price']
            
            # Get signal - handle both Series and scalar cases
            signal_data = signals.loc[timestamp, 'signal']
            if isinstance(signal_data, pd.Series):
                current_signal = signal_data.iloc[0] if len(signal_data) > 0 else 0
            else:
                current_signal = signal_data
            
            # Calculate portfolio value
            current_value = capital + (position * current_price)
            
            # Position sizing logic
            if position_sizing == 'full':
                target_position = int(capital // current_price) if capital > 0 else 0
            elif position_sizing == 'fixed':
                target_position = 100  # Fixed number of shares
            elif position_sizing == 'percent':
                target_position = int((capital * 0.1) // current_price)  # 10% of capital
            else:
                target_position = int(capital // current_price)
            
            # Execute trades based on signals
            if current_signal == 1 and position == 0 and capital > current_price:
                # Buy signal
                shares_to_buy = min(target_position, int(capital // current_price))
                if shares_to_buy > 0:
                    cost = shares_to_buy * current_price * (1 + transaction_cost)
                    capital -= cost
                    position += shares_to_buy
                    trades.append({
                        'timestamp': timestamp,
                        'action': 'BUY',
                        'shares': shares_to_buy,
                        'price': current_price,
                        'cost': cost
                    })
                    
            elif current_signal == -1 and position > 0:
                # Sell signal
                proceeds = position * current_price * (1 - transaction_cost)
                capital += proceeds
                trades.append({
                    'timestamp': timestamp,
                    'action': 'SELL',
                    'shares': position,
                    'price': current_price,
                    'proceeds': proceeds
                })
                position = 0
            
            # Record portfolio state
            portfolio.append({
                'timestamp': timestamp,
                'capital': capital,
                'position': position,
                'price': current_price,
                'value': capital + (position * current_price),
                'signal': current_signal
            })
            
        except Exception as e:
            print(f"Error processing timestamp {timestamp}: {e}")
            continue
    
    # Create portfolio DataFrame
    portfolio_df = pd.DataFrame(portfolio)
    portfolio_df.set_index('timestamp', inplace=True)
    
    # Calculate performance metrics
    if len(portfolio_df) > 1:
        portfolio_df['returns'] = portfolio_df['value'].pct_change()
        portfolio_df['cumulative_returns'] = (1 + portfolio_df['returns']).cumprod() - 1
    else:
        portfolio_df['returns'] = 0.0
        portfolio_df['cumulative_returns'] = 0.0
    
    # Print performance summary
    final_value = portfolio_df['value'].iloc[-1] if len(portfolio_df) > 0 else initial_capital
    total_return = (final_value / initial_capital - 1) * 100
    
    sharpe_ratio = 0.0
    if len(portfolio_df) > 1 and portfolio_df['returns'].std() > 0:
        sharpe_ratio = (portfolio_df['returns'].mean() / portfolio_df['returns'].std() * np.sqrt(252))
    
    print(f"Initial Capital: ${initial_capital:,.2f}")
    print(f"Final Portfolio Value: ${final_value:,.2f}")
    print(f"Total Return: {total_return:.2f}%")
    print(f"Number of Trades: {len(trades)}")
    print(f"Sharpe Ratio: {sharpe_ratio:.2f}")
    
    if len(portfolio_df) > 0:
        max_drawdown = calculate_max_drawdown(portfolio_df['value'])
        print(f"Maximum Drawdown: {max_drawdown:.2f}%")
    
    return portfolio_df, pd.DataFrame(trades)

def calculate_max_drawdown(values: pd.Series) -> float:
    """Calculate maximum drawdown from a series of portfolio values."""
    if len(values) == 0:
        return 0.0
    
    peak = values.expanding(min_periods=1).max()
    drawdown = (values - peak) / peak
    return drawdown.min() * 100
