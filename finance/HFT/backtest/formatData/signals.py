import pandas as pd

import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import QuantLib as ql


def sentiment_analysis(comparison_df):
    """
    sentiment analysis
    """
    # Market sentiment indicators
    comparison_df['market_sentiment'] = comparison_df['close'] / comparison_df['calculated_price'] - 1
    
    print(f"\nMARKET SENTIMENT ANALYSIS:")
    print(f"Average sentiment: {comparison_df['market_sentiment'].mean():.2%}")
    print(f"Max optimism (greed): {comparison_df['market_sentiment'].min():.2%}")
    print(f"Max pessimism (fear): {comparison_df['market_sentiment'].max():.2%}")
    
    # Sentiment extremes
    extreme_optimism = comparison_df['market_sentiment'] > 0.10  # >10% premium
    extreme_pessimism = comparison_df['market_sentiment'] < -0.10  # >10% discount
    
    print(f"Extreme optimism periods: {extreme_optimism.sum()}")
    print(f"Extreme pessimism periods: {extreme_pessimism.sum()}")
    
    # Does sentiment predict mean reversion?
    comparison_df['next_return'] = comparison_df['close'].pct_change().shift(-1)
    sentiment_vs_return = comparison_df['market_sentiment'].corr(comparison_df['next_return'])
    
    print(f"\nSENTIMENT MEAN-REVERSION ANALYSIS:")
    print(f"Correlation between sentiment and next return: {sentiment_vs_return:.3f}")
    
    if sentiment_vs_return < -0.2:
        print("→ Strong mean-reversion: Extreme sentiment predicts opposite moves")
    elif sentiment_vs_return > 0.2:
        print("→ Momentum: Sentiment persists in same direction")
    else:
        print("→ No clear predictive relationship")
    
    return comparison_df



def identify_trading_signals(comparison_df, strike_price, underlying_symbol):
    """
    Enhanced with time decay and volatility filters using expiration data
    """
    comparison_df['price_divergence'] = comparison_df['calculated_price'] - comparison_df['close']
    comparison_df['divergence_pct'] = (comparison_df['price_divergence'] / comparison_df['close']) * 100
    
    print("="*70)
    print("BLACK-SCHOLES vs MARKET SENTIMENT SIGNALS")
    print("="*70)
    print("ENHANCED WITH EXPIRATION-BASED DECAY FILTERS")
    print("="*70)
    
    # Calculate days to expiry for each row
    comparison_df = calculate_days_to_expiry(comparison_df)
    
    # Initialize signals
    comparison_df['signal'] = 'HOLD'
    comparison_df['signal_rationale'] = 'Prices aligned'
    
    # Calculate expected time decay and volatility impact
    #comparison_df = calculate_decay_metrics(comparison_df)
    
    # Generate raw signals
    over_optimistic = comparison_df['close'] < comparison_df['calculated_price'] * 1.1
    optimistic = (comparison_df['close'] < comparison_df['calculated_price'] * 1.05) & ~over_optimistic
    over_pessimistic = comparison_df['close'] > comparison_df['calculated_price'] * 0.9
    pessimistic = (comparison_df['close'] > comparison_df['calculated_price'] * 0.95) & ~over_pessimistic
    
    # Apply signals with rationale
    comparison_df.loc[over_optimistic, 'signal'] = 'STRONG_BUY'
    comparison_df.loc[over_optimistic, 'signal_rationale'] = 'Market over-optimistic: Price > BS +10%'
    
    comparison_df.loc[optimistic, 'signal'] = 'BUY'
    comparison_df.loc[optimistic, 'signal_rationale'] = 'Market optimistic: Price > BS +5%'
    
    comparison_df.loc[over_pessimistic, 'signal'] = 'STRONG_SELL'
    comparison_df.loc[over_pessimistic, 'signal_rationale'] = 'Market over-pessimistic: Price < BS -10%'
    
    comparison_df.loc[pessimistic, 'signal'] = 'SELL'
    comparison_df.loc[pessimistic, 'signal_rationale'] = 'Market pessimistic: Price < BS -5%'
    
    # APPLY INTRADAY FILTERS - Only trade when profitable after decay
    signal_mask = comparison_df['signal'] != 'HOLD'
 
    # Print analysis
    signal_counts = comparison_df[comparison_df['signal'] != 'HOLD']['signal'].value_counts()
   
    
    print("RAW SIGNAL DISTRIBUTION:")
    print(signal_counts)

    total_signals = len(comparison_df[comparison_df['signal'] != 'HOLD'])
    #total_eligible = len(comparison_df[comparison_df['trade_eligible']])

    
    return comparison_df

def calculate_days_to_expiry(comparison_df):
    """
    Calculate days to expiry for each timestamp using QuantLib Date
    """
    comparison_df['days_to_expiry'] = np.nan
    
    for i, row in comparison_df.iterrows():
        # Convert current date to QuantLib Date
        current_date = i  # Assuming index is datetime
        ql_current = ql.Date(row["timestamp"].day, row["timestamp"].month, row["timestamp"].year)
        
        # Get expiration date (you need to have this in your data)
        # Assuming you have 'expiration_date' column or can calculate it
        expiry_date = row.get('expiration_date')  # This should be a datetime object
        
        if pd.notna(expiry_date):
            ql_expiry = ql.Date(expiry_date.day, expiry_date.month, expiry_date.year)
            days_to_expiry = ql_expiry - ql_current
            comparison_df.at[i, 'days_to_expiry'] = days_to_expiry
        else:
            # Fallback: use fixed DTE if not available
            comparison_df['days_to_expiry'] = 72  # Based on your actual average    
    return comparison_df

def calculate_decay_metrics(comparison_df):


    # Calculate bid-ask spread impact
    if 'bid' in comparison_df.columns and 'ask' in comparison_df.columns:
        comparison_df['bid_ask_spread'] = comparison_df['ask'] - comparison_df['bid']
        comparison_df['bid_ask_spread_pct'] = (
            comparison_df['bid_ask_spread'] / ((comparison_df['bid'] + comparison_df['ask']) / 2) * 100
        )
    else:
        # Realistic intraday option spreads
        comparison_df['bid_ask_spread_pct'] = np.where(
            comparison_df['days_to_expiry'] < 7,  # Near expiration
            8.0,  # Wider spreads for weeklies
            np.where(
                comparison_df['days_to_expiry'] < 14,  # 1-2 weeks
                5.0,
                3.0  # Longer DTE
            )
        )
    

    
    return comparison_df

def trading_strategy(comparison_df, initial_capital, 
                    entry_consecutive=5, exit_consecutive=3,
                    max_spread_pct=0.002, max_hold_hours=24,
                    profit_target_pct=0.02, stop_loss_pct=0.01):

    # Only take eligible trades that pass filters
    comparison_df['bid_ask_spread_pct'] = max_spread_pct
   
    signals = comparison_df
    if len(signals) == 0:
        print("No eligible trades found after decay/volatility filters")
        return None
    
    # Require DatetimeIndex for accurate timing
    if not isinstance(signals.index, pd.DatetimeIndex):
        raise ValueError("The index of comparison_df must be a pd.DatetimeIndex for proper holding time calculation.")
    
    # Add signal strength and consecutive count
    signals['signal_strength'] = signals['signal'].apply(lambda x: 1 if 'BUY' in x else (-1 if 'SELL' in x else 0))
    signals['consecutive_count'] = 0
    
    # Calculate consecutive signal counts
    current_count = 0
    current_signal = 0
    
    for i in range(len(signals)):
        if signals['signal_strength'].iloc[i] == current_signal:
            current_count += 1
        else:
            current_count = 1
            current_signal = signals['signal_strength'].iloc[i]
        
        signals.loc[signals.index[i], 'consecutive_count'] = current_count
    
    current_capital = initial_capital
    results = []
    current_position = None  # None, 'LONG', or 'SHORT'
    entry_index = None
    entry_price = None
    
    for i in range(len(signals)):
        current_signal_data = signals.iloc[i]
        current_price = current_signal_data['close']
        
        # Check if we're in a position
        if current_position is None:
            # Look for entry signal: consecutive strong signals
            if (current_signal_data['consecutive_count'] >= entry_consecutive):
                hour = signals.index[i].hour

                if(hour >= 16):
                    continue
                # Determine position type
                if 'BUY' in current_signal_data['signal']:
                    current_position = 'LONG'
                    entry_price = current_price
                    entry_index = i
                    entry_time = signals.index[i]
                    
                    # Calculate position size
                    leverage_factor = 100
                    contract_value_at_entry = entry_price * leverage_factor
                    contracts_traded = initial_capital / contract_value_at_entry  # Number of contracts
                
                    results.append({
                        'entry_date': entry_time,
                        'signal': current_signal_data['signal'],
                        'entry_price': entry_price,
                        'position': current_position,
                        'entry_reason': f"{current_signal_data['consecutive_count']} consecutive BUY signals",
                        'contracts_traded': contracts_traded
                    })
                    
                elif 'SELL' in current_signal_data['signal']:
                    current_position = 'SHORT'
                    entry_price = current_price
                    entry_index = i
                    entry_time = signals.index[i]
                    
                    # Calculate position size
                    leverage_factor = 100
                    contract_value_at_entry = entry_price * leverage_factor
                    contracts_traded = initial_capital / contract_value_at_entry  # Number of contracts
                 
                    results.append({
                        'entry_date': entry_time,
                        'signal': current_signal_data['signal'],
                        'entry_price': entry_price,
                        'position': current_position,
                        'entry_reason': f"{current_signal_data['consecutive_count']} consecutive SELL signals",
                        'contracts_traded': contracts_traded
                    })
                    
        else:
            # We're in a position, check for exit conditions
            exit_reason = None
            current_pnl = 0
            
            # Calculate current PnL (percentage for exit conditions)
            if current_position == 'LONG':
                current_pnl = (current_price - entry_price) / entry_price
            else:  # SHORT
                current_pnl = (entry_price - current_price) / entry_price
            
            # Exit condition 1: Profit target
            if current_pnl >= profit_target_pct:
                exit_reason = f"Profit target reached ({current_pnl*100:.2f}%)"
            
            # Exit condition 2: Stop loss
            elif current_pnl <= -stop_loss_pct:
                exit_reason = f"Stop loss triggered ({current_pnl*100:.2f}%)"
            
            # Exit condition 3: Opposite trend (3+ consecutive opposite signals)
            elif current_signal_data['consecutive_count'] >= exit_consecutive:
                if (current_position == 'LONG' and 'SELL' in current_signal_data['signal']) or \
                   (current_position == 'SHORT' and 'BUY' in current_signal_data['signal']):
                    exit_reason = f"{current_signal_data['consecutive_count']} consecutive opposite signals"
            
            # Exit condition 4: Market hour >= 16:00
            current_hour = signals.index[i].hour
            if current_hour >= 16:
                exit_reason = f"Market close at or after 16:00 ({current_hour}:00)"
                
            if exit_reason:
                
                # Calculate holding time for all exit conditions
                time_diff = signals.index[i] - entry_time
                time_diff_hours = time_diff.total_seconds() / 3600
                
                # Append holding time to exit reason for market close
                if "Market close" in exit_reason:
                    exit_reason += f" (held for {time_diff_hours:.1f}h)"
                    
                    
                exit_price = current_price
                entry_data = results[-1]  # Get the last entry
                
                # Calculate returns with leverage
                leverage_factor = 100
                contracts_traded = entry_data['contracts_traded']
                
                # Raw return per contract (in cash)
                if current_position == 'LONG':
                    raw_return_cash = (exit_price - entry_data['entry_price']) * leverage_factor
                    raw_return_pct = (exit_price - entry_data['entry_price']) / entry_data['entry_price']
                else:  # SHORT
                    raw_return_cash = (entry_data['entry_price'] - exit_price) * leverage_factor
                    raw_return_pct = (entry_data['entry_price'] - exit_price) / entry_data['entry_price']
                
                # Total raw return for all contracts
                total_raw_return_cash = raw_return_cash * contracts_traded
                
                # Spread costs (half at entry, half at exit)
                contract_value_at_entry = entry_data['entry_price'] * leverage_factor
                entry_spread = signals.iloc[entry_index]['bid_ask_spread_pct'] / 100 / 2
                exit_spread = current_signal_data['bid_ask_spread_pct'] / 100 / 2
                total_spread_cost = (entry_spread + exit_spread) * contract_value_at_entry * contracts_traded
                
                # Net return in cash
                net_return_cash = total_raw_return_cash - total_spread_cost
                
                # Update capital
                current_capital += net_return_cash
                
                # Calculate percentage returns for reporting
                net_return_pct = net_return_cash / initial_capital
                
                # Update the trade result
                results[-1].update({
                    'exit_date': signals.index[i],
                    'exit_price': exit_price,
                    'holding_hours': time_diff_hours,
                    'raw_return_pct': raw_return_pct * 100,
                    'raw_return_cash': total_raw_return_cash,
                    'spread_cost': total_spread_cost,
                    'net_return_cash': net_return_cash,
                    'net_return_pct': net_return_pct * 100,
                    'exit_reason': exit_reason,
                    'final_capital': current_capital
                })
                
                current_position = None
                entry_index = None
                entry_price = None
    
    # Performance metrics
    completed_trades = [trade for trade in results if 'exit_date' in trade]
    
    if not completed_trades:
        print("No completed trades - checking why...")
        print(f"Total signals: {len(signals)}")
        print(f"Signals distribution: {signals['signal'].value_counts().to_dict()}")
        
        # Check if we entered any positions but didn't exit
        if results and 'exit_date' not in results[-1]:
            print(f"Open position: {results[-1]}")
        
        return pd.DataFrame(completed_trades)
    
    total_return = (current_capital / initial_capital - 1) * 100
    net_returns = [trade['net_return_pct'] / 100 for trade in completed_trades]
    raw_returns = [trade['raw_return_pct'] / 100 for trade in completed_trades]
    
    win_rate = (np.array(net_returns) > 0).mean() * 100
    sharpe_ratio = np.mean(net_returns) / np.std(net_returns) * np.sqrt(252 * 6.5) if len(net_returns) > 1 else 0
    
    print(f"\nTREND-FOLLOWING PERFORMANCE:")
    print(f"Entry condition: {entry_consecutive}+ consecutive signals")
    print(f"Exit condition: {exit_consecutive}+ opposite signals OR {profit_target_pct*100:.1f}% profit/{stop_loss_pct*100:.1f}% loss")
    print(f"Initial capital: ${initial_capital:,.0f}")
    print(f"Final capital: ${current_capital:,.2f}")
    print(f"Total return: {total_return:.1f}%")
    print(f"Win rate: {win_rate:.1f}%")
    print(f"Sharpe ratio: {sharpe_ratio:.2f}")
    print(f"Number of trades: {len(completed_trades)}")
    
    # Analyze exit reasons
    exit_reasons = {}
    for trade in completed_trades:
        reason = trade['exit_reason']
        exit_reasons[reason] = exit_reasons.get(reason, 0) + 1
    
    print(f"\nEXIT REASONS:")
    for reason, count in exit_reasons.items():
        print(f"{reason}: {count} trades")
    
    # Detailed analysis
    avg_holding = np.mean([t['holding_hours'] for t in completed_trades])
    avg_spread_cost = np.mean([t['spread_cost'] / t['contracts_traded'] for t in completed_trades]) * 100
    avg_raw_return = np.mean(raw_returns) * 100
    avg_net_return = np.mean(net_returns) * 100
    
    print(f"\nDETAILED ANALYSIS:")
    print(f"Avg holding time: {avg_holding:.1f} hours")
    print(f"Avg raw return: {avg_raw_return:.2f}%")
    print(f"Avg spread cost per contract: {avg_spread_cost:.2f}%")
    print(f"Avg net return: {avg_net_return:.2f}%")
    
    return pd.DataFrame(completed_trades)

def plot_trading_signals(comparison_df, strike_price, underlying_symbol):
    """
    Create seaborn plots for trading signals analysis with proper formatting
    """
    # Set up the plotting style
    sns.set_style("whitegrid")
    sns.set_palette("husl")
    
    # Create subplots
    fig, axes = plt.subplots(2, 3, figsize=(18, 12))
    fig.suptitle(f'Black-Scholes vs Market Analysis: {underlying_symbol} Strike ${strike_price}', 
                fontsize=16, fontweight='bold')
    
    # 1. Price comparison over time
    sns.lineplot(data=comparison_df, x=comparison_df.index, y='close', 
                ax=axes[0, 0], label='Market Price', alpha=0.8, linewidth=2)
    sns.lineplot(data=comparison_df, x=comparison_df.index, y='calculated_price', 
                ax=axes[0, 0], label='Black-Scholes Price', alpha=0.8, linewidth=2)
    axes[0, 0].set_title('Price Comparison Over Time')
    axes[0, 0].set_ylabel('Option Price ($)')
    axes[0, 0].legend()
    axes[0, 0].tick_params(axis='x', rotation=45)
    
    # 2. Price divergence distribution
    sns.histplot(data=comparison_df, x='price_divergence', ax=axes[0, 1], bins=30, kde=True)
    mean_divergence = comparison_df['price_divergence'].mean()
    axes[0, 1].axvline(mean_divergence, color='red', linestyle='--', 
                      label=f'Mean: {mean_divergence:.2f}')
    axes[0, 1].set_title('Price Divergence Distribution')
    axes[0, 1].set_xlabel('Price Divergence (Calculated - Market)')
    axes[0, 1].legend()
    
    # 3. Scatter plot: Calculated vs Market prices
    sns.regplot(data=comparison_df, x='close', y='calculated_price', ax=axes[0, 2], 
               scatter_kws={'alpha': 0.6}, line_kws={'color': 'red'})
    max_price = max(comparison_df['close'].max(), comparison_df['calculated_price'].max())
    axes[0, 2].plot([0, max_price], [0, max_price], 'g--', label='Perfect fit', alpha=0.7)
    axes[0, 2].set_title('Calculated vs Market Prices')
    axes[0, 2].set_xlabel('Market Price ($)')
    axes[0, 2].set_ylabel('Calculated Price ($)')
    axes[0, 2].legend()
    
    # 4. Divergence percentage over time with signal highlights
    # Create signal color mapping
    signal_colors = {
        'STRONG_BUY': 'darkgreen',
        'BUY': 'lightgreen', 
        'HOLD': 'gray',
        'SELL': 'lightcoral',
        'STRONG_SELL': 'darkred'
    }
    
    # Plot divergence with signal points
    sns.lineplot(data=comparison_df, x=comparison_df.index, y='divergence_pct', 
                ax=axes[1, 0], color='blue', alpha=0.7, label='Divergence %')
    
    # Add signal points
    for signal, color in signal_colors.items():
        signal_data = comparison_df[comparison_df['signal'] == signal]
        if not signal_data.empty:
            axes[1, 0].scatter(signal_data.index, signal_data['divergence_pct'], 
                              color=color, s=50, label=signal, alpha=0.8)
    
    axes[1, 0].axhline(y=0, color='black', linestyle='-', alpha=0.5)
    axes[1, 0].axhline(y=10, color='red', linestyle='--', alpha=0.5)
    axes[1, 0].axhline(y=-10, color='blue', linestyle='--', alpha=0.5)
    axes[1, 0].set_title('Divergence % with Trading Signals')
    axes[1, 0].set_ylabel('Divergence (%)')
    axes[1, 0].set_xlabel('Date')
    axes[1, 0].tick_params(axis='x', rotation=45)
    axes[1, 0].legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    
    # 5. Signal distribution count plot
    signal_counts = comparison_df['signal'].value_counts()
    colors = [signal_colors.get(signal, 'gray') for signal in signal_counts.index]
    sns.barplot(x=signal_counts.index, y=signal_counts.values, ax=axes[1, 1], palette=colors)
    axes[1, 1].set_title('Signal Distribution')
    axes[1, 1].set_ylabel('Count')
    axes[1, 1].tick_params(axis='x', rotation=45)
    
    # Add value labels on bars
    for i, v in enumerate(signal_counts.values):
        axes[1, 1].text(i, v + 0.1, str(v), ha='center', va='bottom', fontweight='bold')
    
    # 6. Rolling mean of divergence percentage
    comparison_df['rolling_divergence'] = comparison_df['divergence_pct'].rolling(window=5).mean()
    sns.lineplot(data=comparison_df, x=comparison_df.index, y='rolling_divergence', 
                ax=axes[1, 2], color='purple', linewidth=2, label='5-Day Rolling Mean')
    axes[1, 2].axhline(y=0, color='black', linestyle='-', alpha=0.5)
    axes[1, 2].set_title('5-Day Rolling Average Divergence')
    axes[1, 2].set_ylabel('Divergence (%)')
    axes[1, 2].set_xlabel('Date')
    axes[1, 2].tick_params(axis='x', rotation=45)
    axes[1, 2].legend()
    
    plt.tight_layout()
    plt.show()
    
    # Additional detailed analysis plot
    plt.figure(figsize=(12, 8))
    
    # Create signal timeline with proper numeric mapping
    signal_map = {'STRONG_BUY': 2, 'BUY': 1, 'HOLD': 0, 'SELL': -1, 'STRONG_SELL': -2}
    comparison_df['signal_strength'] = comparison_df['signal'].map(signal_map)
    
    # Plot signal strength over time
    plt.subplot(2, 1, 1)
    colors = comparison_df['signal'].map(signal_colors)
    plt.scatter(comparison_df.index, comparison_df['signal_strength'], 
               c=colors, s=100, alpha=0.8)
    plt.axhline(y=0, color='black', linestyle='-', alpha=0.3)
    plt.title('Trading Signal Strength Timeline')
    plt.ylabel('Signal Strength')
    plt.yticks([-2, -1, 0, 1, 2], ['STRONG_SELL', 'SELL', 'HOLD', 'BUY', 'STRONG_BUY'])
    plt.grid(True, alpha=0.3)
