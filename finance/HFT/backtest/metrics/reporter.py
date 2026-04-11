from finance.utils.logger import logger
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns


class Reporter:
    """Generates equity curve, drawdown, profit distribution and position charts."""

    def __init__(self, instrument_multipliers: dict):
        self.multipliers = instrument_multipliers

    def plot(self, pnl_df: pd.DataFrame, trades_df: pd.DataFrame, output: str = 'backtest_results.png'):
        if pnl_df.empty:
            logger.warning("No PnL history to plot")
            return

        sns.set_style("whitegrid")
        sns.set_context("notebook", font_scale=1.2)
        plt.ioff()
        fig, axes = plt.subplots(2, 2, figsize=(15, 10))

        # Equity curve
        for instr in self.multipliers:
            d = pnl_df[pnl_df['instrument'] == instr]
            if not d.empty:
                sns.lineplot(data=d, x='timestamp', y='total_value', label=instr, ax=axes[0, 0])
        axes[0, 0].set_title('Equity Curve')
        axes[0, 0].tick_params(axis='x', rotation=45)

        # Drawdown
        for instr in self.multipliers:
            d = pnl_df[pnl_df['instrument'] == instr].copy()
            if not d.empty:
                d['peak'] = d['total_value'].cummax()
                d['drawdown'] = (d['peak'] - d['total_value']) / d['peak']
                sns.lineplot(data=d, x='timestamp', y='drawdown', label=instr, ax=axes[0, 1])
        axes[0, 1].set_title('Drawdown')
        axes[0, 1].tick_params(axis='x', rotation=45)

        # Profit distribution
        for instr in self.multipliers:
            d = trades_df[trades_df['instrument'] == instr] if not trades_df.empty else pd.DataFrame()
            if not d.empty:
                sns.histplot(data=d, x='profit', bins=30, label=instr, alpha=0.5, ax=axes[1, 0])
        axes[1, 0].set_title('Profit Distribution')

        # Position over time
        for instr in self.multipliers:
            d = pnl_df[pnl_df['instrument'] == instr]
            if not d.empty:
                sns.lineplot(data=d, x='timestamp', y='position', label=instr, ax=axes[1, 1])
        axes[1, 1].set_title('Position Over Time')
        axes[1, 1].tick_params(axis='x', rotation=45)

        plt.tight_layout()
        fig.savefig(output)
        plt.close(fig)
        logger.info("Saved backtest chart to {output}", output=output)

    def print_report(self, metrics: dict):
        logger.info("=" * 60)
        logger.info("TRADING PERFORMANCE REPORT")
        logger.info("=" * 60)
        for k, v in metrics.items():
            if isinstance(v, float):
                logger.info("  {k}: {v:.4f}", k=k, v=v)
            else:
                logger.info("  {k}: {v}", k=k, v=v)
        logger.info("=" * 60)
