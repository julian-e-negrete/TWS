
#ppi loader import

from ppi_client.api.constants import ACCOUNTDATA_TYPE_ACCOUNT_NOTIFICATION, ACCOUNTDATA_TYPE_PUSH_NOTIFICATION, \
    ACCOUNTDATA_TYPE_ORDER_NOTIFICATION
from ppi_client.ppi import PPI

#time import
from datetime import datetime
from zoneinfo import ZoneInfo


import pandas as pd
import re

import QuantLib as ql



#function imports

from finance.HFT.backtest.db.load_data import load_tick_historical

from finance.HFT.backtest.formatData.LOB import process_db_data

from finance.HFT.backtest.formatData.minutes_ticker import fetch_minute_trades

from finance.HFT.backtest.formatData.analyzer import analyze_orderbook_data, create_interactive_plots, generate_trading_signals, print_statistical_summary, identify_key_events, simulate_strategy

from finance.HFT.backtest.PPI.opciones.get_maturity import get_maturity

from finance.PPI.classes import Account, Market_data, Opciones

from finance.HFT.backtest.opciones.blackscholes import black_scholes_model

from finance.HFT.backtest.formatData.signals import identify_trading_signals, trading_strategy, sentiment_analysis, plot_trading_signals


import pickle
import os

#plotting imports
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend; safe for import in headless environments
import matplotlib.pyplot as plt
import seaborn as sns




def calculate_and_save_greeks(ohlc_underlying, ticker, strike_price, expiry,risk_free ,save_path='calculated_data.pkl' ):
    """
    Calculate option prices and Greeks, and save to file
    """
    # Check if calculated data already exists
    if os.path.exists(save_path):
        print(f"Loading pre-calculated data from {save_path}")
        with open(save_path, 'rb') as f:
            return pickle.load(f)
        
        
        
    ppi = PPI(sandbox=False)

    account = Account(ppi)
    
    

    market = Market_data(account.ppi)


    date_format = "%Y-%m-%d"

    start_date = datetime.strptime(f"{datetime.now().year}-{datetime.now().month - 1}-01", date_format)
    end_date = datetime.now()
    underliying = "GGAL".strip().upper()


    lst_historical = market.get_historical_data(underliying, "ACCIONES", "A-24HS", start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
    df = pd.DataFrame(lst_historical)
    #print(df)
    
    Opciones_class = Opciones(df, account, market)

    daily_volatility = Opciones_class.daily_volatility()
    annual_volatility = Opciones_class.annual_volatility()

    delta = len(Opciones_class.df['Daily Return'].dropna())

    
    calculated_data = []
    
    
    
    print("Calculating option prices and Greeks...")
    print(f"risk free rate: {risk_free * 100}%")
    print(f"Annual Volatility: {(annual_volatility * 100):.2f}% based on {delta} days of data")
    for index, row in ohlc_underlying.iterrows():
        option, actual_price, delta, gamma, vega, theta, rho, iv = black_scholes_model(
            underliying, ticker, strike_price, expiry, row["close"],Opciones_class, annual_volatility,risk_free, True
        )
        
        # Append data to the list
        calculated_data.append({
            'timestamp': row["timestamp"],  # Use the timestamp column
            'calculated_price': option,
            'delta': delta,
            'gamma': gamma,
            'vega': vega,
            'theta': theta,
            'rho': rho,
            'implied_volatility': iv,
            'underlying_price': row["close"]
        })
        
        # print(f"Calculated option price: {option}")
        # print(f"Delta: {delta}, Gamma: {gamma}, Vega: {vega}, Theta: {theta}, Rho: {rho}")
    
    # Convert to DataFrame
    calculated_df = pd.DataFrame(calculated_data)
    
    # Save the calculated data
    with open(save_path, 'wb') as f:
        pickle.dump(calculated_df, f)
    print(f"Calculated data saved to {save_path}")
    
    return calculated_df




def recalculate_data(ohlc_underlying, ticker, strike_price, expiry,risk_free, save_path='calculated_data.pkl'):
    """Force recalculation and overwrite existing data"""
    if os.path.exists(save_path):
        os.remove(save_path)
        print("Removed existing calculated data file")
    
    return calculate_and_save_greeks(ohlc_underliying, ticker, strike_price, expiry, risk_free, 'calculated_data.pkl')




def compare_with_market_prices(calculated_df, ohlc_option):
    """
    Compare calculated prices with market prices
    """
    # Make sure both DataFrames have timestamp as datetime
    calculated_df['timestamp'] = pd.to_datetime(calculated_df['timestamp'])
    ohlc_option = ohlc_option.copy()
    ohlc_option['timestamp'] = pd.to_datetime(ohlc_option['timestamp'])
    
    # Merge on timestamp column instead of index
    comparison_df = pd.merge(
        ohlc_option,
        calculated_df,
        on='timestamp',
        how='inner',
        suffixes=('_market', '_calculated')
    )
    
    if comparison_df.empty:
        print("Warning: No matching timestamps found between calculated data and market data!")
        print("Calculated timestamps sample:", calculated_df['timestamp'].head())
        print("Market timestamps sample:", ohlc_option['timestamp'].head())
        return comparison_df
    
    # Calculate differences
    comparison_df['price_difference'] = comparison_df['calculated_price'] - comparison_df['close']
    comparison_df['price_error_pct'] = (comparison_df['price_difference'] / comparison_df['close']) * 100
    
    return comparison_df



def analyze_comparison_results(comparison_df):
    """
    Perform detailed analysis and visualization of the comparison results
    """
    
    # Use seaborn style for better looking plots
    sns.set_style("whitegrid")
    sns.set_palette("husl")
    
    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    fig.suptitle('Black-Scholes Model vs Market Prices Analysis', fontsize=16)
    
    # 1. Price comparison over time (using seaborn lineplot)
    sns.lineplot(data=comparison_df, x='timestamp', y='close', ax=axes[0, 0], label='Market Price', alpha=0.7)
    sns.lineplot(data=comparison_df, x='timestamp', y='calculated_price', ax=axes[0, 0], label='Calculated Price', alpha=0.7)
    axes[0, 0].set_title('Price Comparison Over Time')
    axes[0, 0].set_ylabel('Option Price')
    axes[0, 0].legend()
    axes[0, 0].tick_params(axis='x', rotation=45)
    
    # 2. Price difference distribution (using seaborn histplot)
    sns.histplot(data=comparison_df, x='price_difference', ax=axes[0, 1], bins=30, kde=True)
    axes[0, 1].axvline(comparison_df['price_difference'].mean(), color='red', linestyle='--', label=f'Mean: {comparison_df["price_difference"].mean():.2f}')
    axes[0, 1].set_title('Price Difference Distribution')
    axes[0, 1].set_xlabel('Price Difference (Calculated - Market)')
    axes[0, 1].legend()
    
    # 3. Scatter plot: Calculated vs Market prices (using seaborn regplot)
    sns.regplot(data=comparison_df, x='close', y='calculated_price', ax=axes[0, 2], scatter_kws={'alpha':0.6}, line_kws={'color':'red'})
    max_price = max(comparison_df['close'].max(), comparison_df['calculated_price'].max())
    axes[0, 2].plot([0, max_price], [0, max_price], 'r--', label='Perfect fit')
    axes[0, 2].set_title('Calculated vs Market Prices')
    axes[0, 1].set_xlabel('Market Price')
    axes[0, 1].set_ylabel('Calculated Price')
    axes[0, 2].legend()
    
    # 4. Delta vs Price Error (using seaborn scatterplot)
    sns.scatterplot(data=comparison_df, x='delta', y='price_error_pct', ax=axes[1, 0], alpha=0.6)
    axes[1, 0].set_title('Delta vs Price Error %')
    axes[1, 0].set_xlabel('Delta')
    axes[1, 0].set_ylabel('Error %')
    
    # 5. Underlying price vs both option prices
    sns.scatterplot(data=comparison_df, x='underlying_price', y='close', ax=axes[1, 1], alpha=0.6, label='Market')
    sns.scatterplot(data=comparison_df, x='underlying_price', y='calculated_price', ax=axes[1, 1], alpha=0.6, label='Calculated')
    axes[1, 1].set_title('Underlying Price vs Option Prices')
    axes[1, 1].set_xlabel('Underlying Price')
    axes[1, 1].set_ylabel('Option Price')
    axes[1, 1].legend()
    
    # 6. Time series of percentage error
    sns.lineplot(data=comparison_df, x='timestamp', y='price_error_pct', ax=axes[1, 2], alpha=0.7)
    axes[1, 2].axhline(comparison_df['price_error_pct'].mean(), color='red', linestyle='--', 
                      label=f'Mean Error: {comparison_df["price_error_pct"].mean():.1f}%')
    axes[1, 2].set_title('Percentage Error Over Time')
    axes[1, 2].set_ylabel('Error %')
    axes[1, 2].tick_params(axis='x', rotation=45)
    axes[1, 2].legend()
    
    plt.tight_layout()
    plt.savefig('option_price_analysis.png', dpi=300, bbox_inches='tight')
    plt.show()
    
    # Additional: Heatmap of correlations using seaborn
    # plt.figure(figsize=(10, 8))
    # corr_matrix = comparison_df[['close', 'calculated_price', 'underlying_price', 
    #                            'delta', 'gamma', 'vega', 'theta', 'rho']].corr()
    # sns.heatmap(corr_matrix, annot=True, cmap='coolwarm', center=0, square=True)
    # plt.title('Correlation Matrix Heatmap')
    # plt.tight_layout()
    # plt.savefig('correlation_heatmap.png', dpi=300, bbox_inches='tight')
    # plt.show()
    
    
    
def statistical_annalysis(comparison_df, strike_price):
    
    # Additional statistical analysis
    print("\n" + "="*50)
    print("DETAILED STATISTICAL ANALYSIS")
    print("="*50)
    """
    Specialized analysis for very out-of-the-money options
    """
    comparison_df['abs_price_error_pct'] = comparison_df['price_error_pct'].abs()
    comparison_df['moneyness'] = comparison_df['underlying_price'] / strike_price
    
    print("="*70)
    print("ANALYSIS FOR VERY OUT-OF-THE-MONEY OPTION")
    print("="*70)
    
    # Moneyness context
    avg_moneyness = comparison_df['moneyness'].mean()
    print(f"Average Moneyness: {avg_moneyness:.3f}")
    print(f"Option is {((1 - avg_moneyness) * 100):.1f}% out-of-the-money")
    print(f"Strike Price: {strike_price}")
    print(f"Average Underlying Price: {comparison_df['underlying_price'].mean():.2f}")
    
    # 1. Error analysis with OTM context
    print("\n1. PRICING ACCURACY FOR OTM OPTION:")
    print(f"Mean Absolute Error: {comparison_df['price_difference'].abs().mean():.3f}")
    print(f"Mean Percentage Error: {comparison_df['abs_price_error_pct'].mean():.1f}%")
    print(f"Typical option price range: ${comparison_df['close'].min():.2f} - ${comparison_df['close'].max():.2f}")
    
    # 2. Why OTM options are hard to price
    # print("\n2. OTM OPTION PRICING CHALLENGES:")
    # print("• Extreme sensitivity to volatility assumptions")
    # print("• Liquidity effects dominate theoretical pricing")
    # print("• Small absolute errors become large percentage errors")
    # print("• Market makers may widen spreads for OTM options")
    
    # 3. Practical trading implications
    # print("\n3. TRADING IMPLICATIONS:")
    # print(f"• Your average pricing error (${comparison_df['price_difference'].abs().mean():.3f})")
    # print("  is likely smaller than the bid-ask spread")
    # print("• Black-Scholes may over/under-price due to volatility smile")
    # print("• For OTM options, execution quality > pricing precision")
    
    # 4. Error analysis by option price level
    price_bins = pd.cut(comparison_df['close'], bins=[0, 0.5, 1, 2, 5, 10], include_lowest=True)
    error_by_price = comparison_df.groupby(price_bins, observed=True)['abs_price_error_pct'].agg(['mean', 'count'])
    print("\n4. ERROR BY OPTION PRICE LEVEL:")
    print(error_by_price.round(1))
    
    # 5. Check if errors are systematic (consistent bias)
    avg_directional_error = comparison_df['price_error_pct'].mean()
    print(f"\n5. DIRECTIONAL BIAS: {avg_directional_error:+.1f}%")
    if avg_directional_error > 2:
        print("→ Black-Scholes consistently OVER-prices this OTM option")
    elif avg_directional_error < -2:
        print("→ Black-Scholes consistently UNDER-prices this OTM option")
    else:
        print("→ No consistent pricing bias detected")
    
    # # 6. Trading strategy suggestions
    # print("\n6. TRADING STRATEGY SUGGESTIONS:")
    # print("• Focus on liquidity and execution, not perfect pricing")
    # print("• Use Black-Scholes for relative value, not absolute pricing")
    # print("• Consider volatility smile adjustments for OTM options")
    # print("• Monitor bid-ask spreads - they may exceed pricing errors")
    # print("• For very cheap options, commission costs matter more")



if __name__ == '__main__':



    # # Load historical market data
    # market_data = load_tick_historical(
    #     start_date="2025-08-20",
    #     end_date="2025-08-20", 
    #     instrument=symbol
    # )
    
    # # Process data from DataFrame
    # results, lob = process_db_data(market_data, symbol_filter=symbol)
    
    # df = pd.DataFrame(results)
    
    symbol = "M:bm_MERV_GFGC85573O_24hs"

    tz = ZoneInfo("America/Argentina/Buenos_Aires")

    
    date = datetime(2025, 8, 26, tzinfo=tz)
    enddate = datetime(2025, 8, 26, tzinfo=tz)  
    interval = "1"
    
    
    match = re.search(r"_([A-Z]+\d+[A-Z])_", symbol)
    if match:
        ticker = match.group(1)  # GFGC85573O
    
    match = re.search(r"_([A-Z]+\d+[A-Z])_", symbol)
    if match:
        maturity = get_maturity(match.group(1), 2025)  
        
  
    match = re.search(r"[A-Z]+(\d+)[A-Z]", symbol)
    if match:
        strike_price = int(match.group(1))
        
    expiry = ql.Date(maturity.day,maturity.month, maturity.year)
    
    if len(str(strike_price)) > 4:
        strike_price /=10
    
    print(f"data of option: {ticker}")
    print(f"strike price: {strike_price}")
    
    #option, actual_price,delta, gamma, vega, theta, rho  = black_scholes_model("GGAL",ticker, strike_price, expiry)
    
    ohlc_underliying = fetch_minute_trades(date, enddate,"bm_MERV_GGAL_24hs")
    
    
    
    ohlc_option = fetch_minute_trades(date, enddate,f"bm_MERV_{ticker}_24hs")
    
    if(ohlc_underliying.empty and ohlc_option.empty):
                
            
        ppi = PPI(sandbox=False)

        account = Account(ppi)
        
        market = Market_data(account.ppi)


        ohlc_underliying   = market.get_intraday_market_data("GGAL", "ACCIONES", "A-24HS")
        ohlc_option   = market.get_intraday_market_data(ticker, "OPCIONES", "A-24HS")

    

    risk_free_rate = 0.45
    calculated_df = calculate_and_save_greeks(ohlc_underliying, ticker, strike_price, expiry, risk_free_rate, 'calculated_data.pkl')
    

    calculated_df["expiration_date"] = maturity
    
    comparison_df = compare_with_market_prices(calculated_df, ohlc_option)
    
    if not comparison_df.empty:
        
        # Run corrected analysis
        comparison_df = identify_trading_signals(comparison_df, strike_price, "GGAL")     
        
        
        comparison_df = comparison_df.set_index(pd.to_datetime(comparison_df['timestamp']))
        
        # market_data = load_tick_historical(
        #     start_date=date.strftime("%Y-%m-%d"),
        #     end_date=enddate.strftime("%Y-%m-%d"),
        #     instrument=symbol
        # )
        
        # results, lob = process_db_data(market_data, symbol_filter=symbol)
        

        
        
        
        # print("\nTrade Details:")comparison_dfrice", "exit_reason", "net_return_cash"]])
        
       
       
       
        #analyze_comparison_results(comparison_df)
        statistical_annalysis(comparison_df, strike_price)
        #print(comparison_df['abs_price_error_pct'].mean())
        if(comparison_df['abs_price_error_pct'].mean()>20):
            risk_free_rate += 0.30
            calculated_df = recalculate_data(ohlc_underliying, ticker, strike_price, expiry, risk_free_rate)
            calculated_df["expiration_date"] = maturity

            
            compári = compare_with_market_prices(calculated_df, ohlc_option)
    
            if not comparison_df.empty:
                
                # Run corrected analysis
                comparison_df = identify_trading_signals(comparison_df, strike_price, "GGAL")     
                
                
                comparison_df = comparison_df.set_index(pd.to_datetime(comparison_df['timestamp']))
                
            
                statistical_annalysis(comparison_df, strike_price)
                
                
        #plot_trading_signals(comparison_df, strike_price, "GGAL")
            
        initial_capital=100000
        strategy_results = trading_strategy(comparison_df, 
                                            initial_capital,
                                            entry_consecutive=3,   
                                            exit_consecutive=2,      
                                            profit_target_pct=0.30,
                                            stop_loss_pct=0.15,    
                                            max_spread_pct=0.002,
                                            max_hold_hours=6        
                                            )
       
        #print((strategy_results.iloc[-1]["final_capital"] - initial_capital) * 100 / initial_capital)
        while((strategy_results.iloc[-1]["final_capital"] - initial_capital) * 100 / initial_capital <0.3):
            #modify parameters to be more/less aggressive
            strategy_results = trading_strategy(comparison_df, 
                                            initial_capital,
                                            entry_consecutive=7,   
                                            exit_consecutive=5,      
                                            profit_target_pct=0.30,
                                            stop_loss_pct=0.15,    
                                            max_spread_pct=0.002,
                                            max_hold_hours=6        
                                            )
            
        print(strategy_results[["signal", "entry_price", "exit_price", "exit_reason", "net_return_pct", "net_return_cash"]])
    else:
        print("No data to compare. Check if timestamps match between datasets.")
