from finance.HFT.backtest.types import Direction
import pandas as pd
from typing import List


class MetricsCalculator:
    """Calculates backtest performance metrics from PnL history and trade list."""

    def calculate(self, pnl_df: pd.DataFrame, trades_df: pd.DataFrame) -> dict:
        metrics = {}

        if pnl_df.empty:
            return metrics

        initial = pnl_df['total_value'].iloc[0]
        final = pnl_df['total_value'].iloc[-1]
        metrics['total_return'] = (final / initial - 1)
        metrics['total_return_pct'] = metrics['total_return'] * 100

        days = max((pnl_df['timestamp'].iloc[-1] - pnl_df['timestamp'].iloc[0]).days, 1)
        metrics['annualized_return_pct'] = ((final / initial) ** (365.25 / days) - 1) * 100

        pnl_df = pnl_df.copy()
        pnl_df['peak'] = pnl_df['total_value'].cummax()
        pnl_df['drawdown'] = (pnl_df['peak'] - pnl_df['total_value']) / pnl_df['peak']
        metrics['max_drawdown_pct'] = pnl_df['drawdown'].max() * 100

        closed = trades_df[trades_df['closed']] if 'closed' in trades_df.columns else pd.DataFrame()
        if not closed.empty:
            winning = closed[closed['profit'] > 0]
            losing = closed[closed['profit'] < 0]
            metrics['num_trades'] = len(closed)
            metrics['win_rate'] = len(winning) / len(closed)
            metrics['win_rate_pct'] = metrics['win_rate'] * 100
            metrics['avg_win'] = winning['profit'].mean() if len(winning) > 0 else 0.0
            metrics['avg_loss'] = losing['profit'].mean() if len(losing) > 0 else 0.0
            metrics['profit_factor'] = (
                winning['profit'].sum() / abs(losing['profit'].sum())
                if len(losing) > 0 else float('inf')
            )
            metrics['expectancy'] = (
                metrics['avg_win'] * metrics['win_rate'] +
                metrics['avg_loss'] * (1 - metrics['win_rate'])
            )

        returns = pnl_df['total_value'].pct_change().dropna()
        if len(returns) > 1 and returns.std() > 0:
            metrics['sharpe_ratio'] = (returns.mean() / returns.std()) * (252 ** 0.5)
        else:
            metrics['sharpe_ratio'] = 0.0

        return metrics
