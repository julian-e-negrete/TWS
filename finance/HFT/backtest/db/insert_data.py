import psycopg2
import pandas as pd
from psycopg2.extras import execute_values
from finance.HFT.backtest.db.config import dbname, user, password, host, port
from datetime import datetime
import numpy as np
import math

def convert_numpy(value):
    """Convert numpy and infinite values to PostgreSQL-compatible types"""
    if isinstance(value, np.generic):
        return float(value) if np.issubdtype(value, np.floating) else int(value)
    if isinstance(value, (float, int)) and math.isinf(value):
        return None  # Will be stored as NULL in the database
    return value
    

def insert_data ( metrics, position, strategy_trades):
    try:
        
        
        conn = psycopg2.connect(
            dbname= dbname,
            user=user,
            password=password,
            host=host,
            port=port,
            sslmode='disable'
        )
        
        cur = conn.cursor()
        
        prepared_metrics = {k: convert_numpy(v) for k, v in metrics.items()}
            
        # 1. Insert main backtest run
        cur.execute("""
            INSERT INTO backtest_runs (
                timestamp, final_capital, total_return_pct, annualized_return_pct,
                max_drawdown_pct, win_rate_pct, profit_factor, expectancy,
                avg_trade_freq_minutes, skipped_trades, total_trades, analysis
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING run_id
            """,
            (
                datetime.now(),
                prepared_metrics.get('final_cash'),
                prepared_metrics.get('total_return_pct'),
                prepared_metrics.get('annualized_return_pct'),
                prepared_metrics.get('max_drawdown_pct'),
                prepared_metrics.get('win_rate_pct'),
                prepared_metrics.get('profit_factor'),  # Will be NULL if infinite
                prepared_metrics.get('expectancy'),
                prepared_metrics.get('avg_trade_frequency'),
                prepared_metrics.get('skipped_trades', 0),
                prepared_metrics.get('trade_count', prepared_metrics.get('total_trades', 0)),
                prepared_metrics.get('analysis', 'No analysis provided')
            )
        )
        run_id = cur.fetchone()[0]
        
        # 2. Insert positions
        if position:
            positions_data = [
                (run_id, instr, qty, prepared_metrics.get('unrealized_pnl', {}).get(instr, 0))
                for instr, qty in position.items()
            ]
            
            execute_values(
                cur,
                "INSERT INTO positions (run_id, instrument, quantity, unrealized_pnl) VALUES %s",
                positions_data
            )
        
        # 3. Insert signal statistics
        if 'signal_stats' in prepared_metrics:
            signal_data = [
                (run_id, signal_name, count)
                for signal_name, count in prepared_metrics['signal_stats'].items()
            ]
            
            execute_values(
                cur,
                "INSERT INTO signal_stats (run_id, signal_name, signal_count) VALUES %s",
                signal_data
            )
        
        # 4. Insert trade metrics
        cur.execute("""
            INSERT INTO trade_metrics (
                run_id, avg_win, avg_loss
            ) VALUES (%s, %s, %s)
            """,
            (
                run_id,
                prepared_metrics.get('avg_win'),
                prepared_metrics.get('avg_loss')
            )
        )
        
        # 5. Insert market observations and trades
        if strategy_trades:
            trades_by_time = {}
            for trade in strategy_trades:
                key = trade.timestamp
                if key not in trades_by_time:
                    trades_by_time[key] = []
                trades_by_time[key].append(trade)
            
            for timestamp, trades in trades_by_time.items():
                cur.execute("""
                    INSERT INTO market_observations (
                        run_id, timestamp, instrument, position, cash
                    ) VALUES (%s, %s, %s, %s, %s)
                    RETURNING observation_id
                    """,
                    (
                        run_id,
                        timestamp,
                        trades[0].instrument,
                        position.get(trades[0].instrument, 0),
                        prepared_metrics.get('final_cash')
                    )
                )
                obs_id = cur.fetchone()[0]
                
                snapshot_data = [
                    (
                        obs_id,
                        trade.price,
                        trade.volume,
                        trade.direction.name,
                        trade.order_type.name,
                        convert_numpy(trade.profit),
                        trade.closed
                    )
                    for trade in trades
                ]
                
                execute_values(
                    cur,
                    """
                    INSERT INTO trade_snapshots (
                        observation_id, price, volume, direction,
                        order_type, profit, closed
                    ) VALUES %s
                    """,
                    snapshot_data
                )
        
        conn.commit()
        print(f"Successfully inserted backtest results with run_id: {run_id}")
        return run_id
    
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Error inserting backtest data: {e}")
        raise
    finally:
        if conn:
            conn.close()

