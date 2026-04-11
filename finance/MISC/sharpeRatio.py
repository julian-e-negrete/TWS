import yfinance as yf
import numpy as np

from datetime import datetime, timedelta


def get_sharpe_ratio(ticker, start_date, end_date, risk_free_rate):
    # Fetch historical data
    data = yf.download(ticker, start=start_date, end=end_date)
    if data.empty:
        print(f"No data available for {ticker}")
        return None

    # Calculate daily returns
    data['Daily Return'] = data['Adj Close'].pct_change()

    # Calculate mean and standard deviation of daily returns
    mean_daily_return = data['Daily Return'].mean()
    std_daily_return = data['Daily Return'].std()

    # Annualize returns and volatility
    annualized_return = mean_daily_return * 252
    annualized_volatility = std_daily_return * np.sqrt(252)

    # Calculate Sharpe Ratio
    sharpe_ratio = (annualized_return - risk_free_rate) / annualized_volatility
    return sharpe_ratio

# Example usage
ticker = "YPFD.BA"  # Replace with your MERVAL stock ticker
start_date = datetime.today() - timedelta(days=730)
end_date = datetime.today()
risk_free_rate = 0.05  # Example: 5% annualized risk-free rate

sharpe_ratio = get_sharpe_ratio(ticker, start_date, end_date, risk_free_rate)
if sharpe_ratio is not None:
    print(f"Sharpe Ratio for {ticker}: {sharpe_ratio:.2f}")
