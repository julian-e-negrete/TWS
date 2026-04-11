import backtrader as bt
from alpha_vantage.timeseries import TimeSeries # pyright: ignore[reportMissingImports]
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import quantstats as qs # type: ignore

class ProfessionalStrategy(bt.Strategy):
    params = (
        ('entry_fast_ma', 15),
        ('entry_slow_ma', 40),
        ('trend_ma', 200),
        ('rsi_period', 11),
        ('atr_period', 10),
        ('risk_per_trade', 0.01),
        ('profit_factor', 2.5),
        ('volume_ma_period', 21),
        ('min_adx', 30),
        ('max_hold_bars', 20)
    )

    def __init__(self):
        # Primary trend filter
        self.trend_ma = bt.indicators.EMA(self.data.close, period=self.p.trend_ma)
        
        # Entry signals
        self.fast_ma = bt.indicators.EMA(self.data.close, period=self.p.entry_fast_ma)
        self.slow_ma = bt.indicators.EMA(self.data.close, period=self.p.entry_slow_ma)
        self.crossover = bt.indicators.CrossOver(self.fast_ma, self.slow_ma)
        
        # Momentum and volatility
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.adx = bt.indicators.ADX(self.data)
        
        # Volume filter
        self.vol_ma = bt.indicators.SMA(self.data.volume, period=self.p.volume_ma_period)
        
        # Trade management
        self.order = None
        self.entry_price = 0
        self.stop_price = 0
        self.target_price = 0
        self.bar_count = 0
        self.trade_history = []
        self.entry_bar = 0
        self.active_trade = None  # Track active trade ID or order

    def log(self, txt):
        print(f'{self.data.datetime.date(0)}, {txt}')

    def notify_trade(self, trade):
        if trade.isclosed:
            pnl = trade.pnl
            pnlcomm = trade.pnlcomm
            self.trade_history.append({
                'entry': trade.price,
                'exit': trade.value,
                'pnl': pnl,
                'pnlcomm': pnlcomm,
                'duration': trade.barlen
            })
            self.log(f"TRADE CLOSED: Gross PnL=${pnl:.2f}, Net PnL=${pnlcomm:.2f}, Duration={trade.barlen} days")
            self.active_trade = None

    def notify_order(self, order):
        if order.status == order.Completed:
            if order.isbuy():
                self.log(f"BUY EXECUTED: {order.executed.size} shares @ ${order.executed.price:.2f}")
                self.entry_price = order.executed.price
                self.entry_bar = self.bar_count
                self.active_trade = order.ref  # Store order reference
            elif order.issell():
                self.log(f"SELL EXECUTED: {order.executed.size} shares @ ${order.executed.price:.2f}")
                self.entry_price = order.executed.price
                self.entry_bar = self.bar_count
                self.active_trade = order.ref  # Store order reference
            self.order = None  # Clear order after execution

    def next(self):
        self.bar_count += 1
        
        # Only cancel stale orders
        if self.order and self.order.status in [self.order.Created, self.order.Submitted]:
            if (self.bar_count - self.entry_bar) > 2:  # Cancel after 2 bars
                self.cancel(self.order)
                self.log("ORDER CANCELED: Stale order")
                self.order = None
        
        # Check if in position
        if self.position:
            # Calculate current unrealized PnL
            current_price = self.data.close[0]
            current_pnl = self.position.size * (current_price - self.position.price)
            self.log(f"Current Position: Size={self.position.size}, Unrealized PnL=${current_pnl:.2f}")
            
            # Check exit conditions
            if (self.position.size > 0 and 
                (self.crossover < 0 or 
                 current_price < self.stop_price or
                 current_price > self.target_price or
                 (self.bar_count - self.entry_bar) > self.p.max_hold_bars)):
                self.order = self.close()
                self.log(f"EXIT LONG SIGNAL: Current Price={current_price:.2f}, Stop={self.stop_price:.2f}, Target={self.target_price:.2f}")
            
            elif (self.position.size < 0 and 
                  (self.crossover > 0 or 
                   current_price > self.stop_price or
                   current_price < self.target_price or
                   (self.bar_count - self.entry_bar) > self.p.max_hold_bars)):
                self.order = self.close()
                self.log(f"EXIT SHORT SIGNAL: Current Price={current_price:.2f}, Stop={self.stop_price:.2f}, Target={self.target_price:.2f}")
        
        # Entry conditions - only if no position
        else:
            # Bullish entry conditions
            bullish = (
                self.data.close[0] > self.trend_ma[0] and
                self.crossover > 0 and
                self.rsi < 65 and
                self.data.volume[0] > self.vol_ma[0] * 1.2 and
                self.adx[0] > self.p.min_adx
            )
            
            # Bearish entry conditions
            bearish = (
                self.data.close[0] < self.trend_ma[0] and
                self.crossover < 0 and
                self.rsi > 35 and
                self.data.volume[0] > self.vol_ma[0] * 1.2 and
                self.adx[0] > self.p.min_adx
            )
            
            if bullish or bearish:
                # Calculate position size with volatility adjustment
                atr = max(self.atr[0], 0.01)  # Avoid division by zero
                position_size = (self.broker.getvalue() * self.p.risk_per_trade) / atr
                position_size = int(position_size)  # Floor to nearest integer
                
                # Use current close price for entry
                entry_price = self.data.close[0]
                
                # Calculate stop and target
                if bullish:
                    self.stop_price = entry_price - atr * 1.5
                    self.target_price = entry_price + atr * self.p.profit_factor
                    self.order = self.buy(size=position_size, exectype=bt.Order.Limit, 
                                         price=entry_price)
                    self.log(f"BUY ORDER PLACED: Size={position_size:.0f}, Entry={entry_price:.2f}, Stop={self.stop_price:.2f}, Target={self.target_price:.2f}")
                    
                elif bearish:
                    self.stop_price = entry_price + atr * 1.5
                    self.target_price = entry_price - atr * self.p.profit_factor
                    self.order = self.sell(size=position_size, exectype=bt.Order.Limit, 
                                          price=entry_price)
                    self.log(f"SELL ORDER PLACED: Size={position_size:.0f}, Entry={entry_price:.2f}, Stop={self.stop_price:.2f}, Target={self.target_price:.2f}")

def get_data(api_key, symbol, save_csv=True):
    try:
        ts = TimeSeries(key=api_key, output_format='pandas')
        data, _ = ts.get_daily(symbol=symbol, outputsize='full')
        data.index = pd.to_datetime(data.index)
        data.rename(columns={
            '1. open': 'open',
            '2. high': 'high',
            '3. low': 'low',
            '4. close': 'close',
            '5. volume': 'volume',
        }, inplace=True)
        # Ensure data is sorted oldest to newest
        data = data.sort_index(ascending=True)
        
        if save_csv:
            data.to_csv(f'{symbol}_daily.csv')
        return data
    except Exception as e:
        print(f"Alpha Vantage failed: {e}. Loading from CSV...")
        data = pd.read_csv(f'{symbol}_daily.csv', index_col=0, parse_dates=True)
        return data.sort_index(ascending=True)

if __name__ == '__main__':
    from finance.config import settings
    # Backtest Setup
    cerebro = bt.Cerebro()
    api_key = settings.backtrader.api_key

    # Get and prepare data
    df = get_data(api_key, 'GGAL')
    print(f"Data loaded: {len(df)} rows from {df.index[0]} to {df.index[-1]}")

    # Create data feed
    data = bt.feeds.PandasData(
        dataname=df,
        open='open',
        high='high',
        low='low',
        close='close',
        volume='volume'
    )
    cerebro.adddata(data)
    cerebro.broker.setcash(10000.0)
    cerebro.broker.setcommission(commission=0.005)

    # Add strategy for optimization
    cerebro.optstrategy(
        ProfessionalStrategy,
        entry_fast_ma=range(10, 20, 5),
        entry_slow_ma=range(30, 50, 10),
        profit_factor=[2.0, 2.5, 3.0],
        min_adx=[25, 30, 35]
    )

    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Days)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='ta')

    print("Running optimization...")
    opt_results = cerebro.run(maxcpus=1)

    # Find best parameters
    best_sharpe = -999
    best_params = None

    for result in opt_results:
        for res in result:  # Handle multi-strategy runs
            # Get Sharpe ratio, handle None cases thoroughly
            sharpe = res.analyzers.sharpe.get_analysis()
            sharpe_ratio = sharpe.get('sharperatio', -999) if isinstance(sharpe, dict) else -999
            # Get trade analysis
            trade_analysis = res.analyzers.ta.get_analysis()
            total_trades = trade_analysis.get('total', {}).get('total', 0) if isinstance(trade_analysis, dict) else 0
            # Log for debugging
            params = res.params._getkwargs()
            print(f"Params: {params}, Sharpe: {sharpe_ratio}, Trades: {total_trades}")
            # Only consider strategies with trades and valid Sharpe ratio
            if total_trades > 0 and isinstance(sharpe_ratio, (int, float)) and sharpe_ratio > best_sharpe:
                best_sharpe = sharpe_ratio
                best_params = params

    print(f"\nBEST PARAMETERS: Sharpe={best_sharpe:.2f}")
    print(best_params)

    # Run final backtest with best parameters
    if best_params:  # Only run if valid parameters were found
        cerebro = bt.Cerebro()
        cerebro.adddata(data)
        cerebro.broker.setcash(10000.0)
        cerebro.broker.setcommission(commission=0.005)
        cerebro.addstrategy(ProfessionalStrategy, **best_params)
        cerebro.addanalyzer(bt.analyzers.PyFolio, _name='pyfolio')

        print("\nRunning final backtest with best parameters...")
        final_result = cerebro.run()
        strat = final_result[0]

        # Generate performance report
        pyfoliozer = strat.analyzers.getbyname('pyfolio')
        returns, positions, transactions, gross_lev = pyfoliozer.get_pf_items()

        # Convert returns to pandas Series with datetime index
        returns = pd.Series(returns)
        returns.index = pd.to_datetime(returns.index)

        # Performance tear sheet
        qs.reports.html(
            returns,
            title="GGAL Strategy Tearsheet",
            output="tearsheet.html",
            live_start_date="2023-01-01"
        )

        print("Tearsheet generated as tearsheet.html")

        # Plot the results
        cerebro.plot(style='candlestick', volume=False)
    else:
        print("No valid parameters found. No trades executed during optimization or no valid Sharpe ratios.")