import pandas as pd
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Any, Optional, Tuple, List
import numpy as np
from datetime import datetime, timedelta
import numpy as np
try:
    from load_data import load_tick_data, load_order_data
except ImportError:
    pass  # legacy import — use finance.HFT.backtest.db.load_data instead


def calculate_spread_stats(tick_df):
    """Calculate spread statistics with robust error handling and input validation"""
    if tick_df.empty or 'ask_price' not in tick_df.columns or 'bid_price' not in tick_df.columns:
        return {
            'avg_spread': 0.0,
            'max_spread': 0.0,
            'min_spread': 0.0,
            'spread_std': 0.0,
            'median_spread': 0.0
        }
    
    try:
        # Ensure numeric types and filter invalid values
        tick_df = tick_df.copy()
        tick_df['ask_price'] = pd.to_numeric(tick_df['ask_price'], errors='coerce')
        tick_df['bid_price'] = pd.to_numeric(tick_df['bid_price'], errors='coerce')
        tick_df = tick_df.dropna(subset=['ask_price', 'bid_price'])
        
        # Calculate spread with sanity checks
        tick_df['spread'] = np.where(
            (tick_df['ask_price'] > 0) & (tick_df['bid_price'] > 0),
            tick_df['ask_price'] - tick_df['bid_price'],
            np.nan
        )
        
        valid_spreads = tick_df['spread'].dropna()
        if valid_spreads.empty:
            return {
                'avg_spread': 0.0,
                'max_spread': 0.0,
                'min_spread': 0.0,
                'spread_std': 0.0,
                'median_spread': 0.0
            }
        
        spread_stats = {
            'avg_spread': valid_spreads.mean(),
            'max_spread': valid_spreads.max(),
            'min_spread': valid_spreads.min(),
            'spread_std': valid_spreads.std(),
            'median_spread': valid_spreads.median()
        }
        
        # Replace any remaining NaN with 0 and ensure float type
        return {k: float(0 if pd.isna(v) else v) for k, v in spread_stats.items()}
    
    except Exception as e:
        print(f"Error calculating spread stats: {e}")
        return {
            'avg_spread': 0.0,
            'max_spread': 0.0,
            'min_spread': 0.0,
            'spread_std': 0.0,
            'median_spread': 0.0
        }
        
        
def enhanced_order_flow_imbalance(order_df, window='10min'):
    """Calculate order flow imbalance with robust data validation"""
    REQUIRED_COLS = ['time', 'side', 'volume']
    
    if order_df.empty or not all(col in order_df.columns for col in REQUIRED_COLS):
        return pd.DataFrame(columns=['buy_volume', 'sell_volume', 'total_volume', 
                                   'net_flow', 'imbalance', 'time'])
    
    try:
        # Create working copy and validate data
        df = order_df.copy()
        df['time'] = pd.to_datetime(df['time'], errors='coerce')
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
        df['side'] = df['side'].str.upper()
        
        # Filter invalid data
        df = df.dropna(subset=['time', 'volume'])
        df = df[df['volume'] > 0]
        df = df[df['side'].isin(['B', 'S'])]
        
        if df.empty:
            return pd.DataFrame(columns=['buy_volume', 'sell_volume', 'total_volume', 
                                       'net_flow', 'imbalance', 'time'])
        
        # Resample with 10-minute windows
        buys = df[df['side'] == 'B'].resample(window, on='time')['volume'].sum().fillna(0)
        sells = df[df['side'] == 'S'].resample(window, on='time')['volume'].sum().fillna(0)
        
        # Calculate metrics with safeguards
        total_volume = buys + sells
        net_flow = buys - sells
        
        # Normalized imbalance calculation with protection against division by zero
        imbalance = np.divide(
            net_flow, 
            total_volume, 
            out=np.zeros_like(net_flow, dtype=float), 
            where=(total_volume > 0)
        )
        
        # Create output DataFrame
        ofi = pd.DataFrame({
            'buy_volume': buys,
            'sell_volume': sells,
            'total_volume': total_volume,
            'net_flow': net_flow,
            'imbalance': np.clip(imbalance, -1.0, 1.0),
            'time': buys.index
        }).set_index('time')
        
        return ofi
    
    except Exception as e:
        print(f"Error in order flow calculation: {str(e)}")
        return pd.DataFrame(columns=['buy_volume', 'sell_volume', 'total_volume', 
                                   'net_flow', 'imbalance'])

def calculate_price_impact(tick_df, order_df):
    """Calculate price impact with error handling"""
    try:
        # Ensure numeric types
        tick_df['last_price'] = pd.to_numeric(tick_df['last_price'], errors='coerce')
        order_df['volume'] = pd.to_numeric(order_df['volume'], errors='coerce')
        
        # Merge with forward-looking prices
        merged = pd.merge_asof(
            order_df.sort_values('time'),
            tick_df[['time', 'last_price']].sort_values('time'),
            on='time',
            direction='forward',
            tolerance=pd.Timedelta('5s')  # Increased tolerance for sparse data
        ).dropna()
        
        # Calculate metrics
        merged['price_change'] = merged['last_price'].diff()
        merged['normalized_impact'] = merged['price_change'] / np.maximum(merged['volume'], 1)
        
        return merged.groupby('side').agg({
            'price_change': ['mean', 'std', 'count'],
            'normalized_impact': ['mean', 'std']
        })
    except Exception as e:
        print(f"Error in price impact calculation: {e}")
        return pd.DataFrame()

@dataclass
class RollingOFITFIProcessor:
    """Enhanced processor with 10-minute windows and improved stability"""
    max_updates: int = 10000  # Increased buffer size
    tfi_window_ms: int = 600000  # 10 minutes in milliseconds
    lob_buffer: Deque[Dict[str, Any]] = field(default_factory=lambda: deque(maxlen=10000))
    trade_buffer: Deque[Dict[str, Any]] = field(default_factory=lambda: deque(maxlen=10000))
    prev_bid_price: float = None
    prev_bid_size: float = None
    prev_ask_price: float = None
    prev_ask_size: float = None
    ofi_rolling: Deque[Dict[str, Any]] = field(default_factory=lambda: deque(maxlen=10000))
    tfi_rolling: Deque[Dict[str, Any]] = field(default_factory=lambda: deque(maxlen=10000))
    last_ofi_calc: pd.Timestamp = field(default_factory=lambda: pd.Timestamp.min)
    last_tfi_calc: pd.Timestamp = field(default_factory=lambda: pd.Timestamp.min)

    def process_lob_update(self, update: Dict[str, Any]) -> float:
        """Process limit order book update with timestamp validation"""
        try:
            t = pd.to_datetime(update['time'])
            if not isinstance(t, pd.Timestamp):
                return 0.0
                
            bid_p = float(update['bid_price'])
            bid_s = float(update['bid_size'])
            ask_p = float(update['ask_price'])
            ask_s = float(update['ask_size'])

            # Calculate OFI contribution
            bid_contrib = 0.0
            if self.prev_bid_price is not None:
                if bid_p > self.prev_bid_price:
                    bid_contrib = bid_s
                elif bid_p == self.prev_bid_price:
                    bid_contrib = bid_s - (self.prev_bid_size or 0.0)

            ask_contrib = 0.0
            if self.prev_ask_price is not None:
                if ask_p < self.prev_ask_price:
                    ask_contrib = -ask_s
                elif ask_p == self.prev_ask_price:
                    ask_contrib = -(ask_s - (self.prev_ask_size or 0.0))

            ofi_inc = bid_contrib + ask_contrib

            # Update state
            self.prev_bid_price = bid_p
            self.prev_bid_size = bid_s
            self.prev_ask_price = ask_p
            self.prev_ask_size = ask_s

            self.ofi_rolling.append({'time': t, 'ofi_inc': ofi_inc})
            self._push_lob({'time': t, 'bid_price': bid_p, 'bid_size': bid_s, 
                          'ask_price': ask_p, 'ask_size': ask_s})
            
            return ofi_inc
        except Exception as e:
            print(f"Error processing LOB update: {e}")
            return 0.0

    def process_trade(self, trade: Dict[str, Any]) -> float:
        """Process trade with timestamp validation"""
        try:
            t = pd.to_datetime(trade['time'])
            if not isinstance(t, pd.Timestamp):
                return 0.0
                
            side = trade['side'].upper()
            vol = float(trade['volume'])
            tfi_inc = vol if side == 'B' else -vol

            self.tfi_rolling.append({'time': t, 'tfi_inc': tfi_inc})
            self._push_trade({'time': t, 'side': side, 'volume': vol})
            
            return tfi_inc
        except Exception as e:
            print(f"Error processing trade: {e}")
            return 0.0

    def snapshot_features(self) -> Dict[str, float]:
        """Generate features with 10-minute rolling windows"""
        try:
            if not self.lob_buffer:
                return {'ofi': 0.0, 'tfi': 0.0, 'spread': 0.0, 'microprice': 0.0}

            current_time = pd.Timestamp.now(tz='UTC')
            ten_min_ago = current_time - pd.Timedelta(minutes=10)
            
            # Filter recent OFI data
            recent_ofi = [x for x in self.ofi_rolling 
                         if pd.to_datetime(x['time']) >= ten_min_ago]
            ofi_sum = sum(x['ofi_inc'] for x in recent_ofi)
            
            # Filter recent TFI data
            recent_tfi = [x for x in self.tfi_rolling 
                         if pd.to_datetime(x['time']) >= ten_min_ago]
            tfi_sum = sum(x['tfi_inc'] for x in recent_tfi)
            total_vol = sum(abs(x['tfi_inc']) for x in recent_tfi)
            
            # Get current LOB state
            last = self.lob_buffer[-1]
            spread = float(last['ask_price']) - float(last['bid_price'])
            bid_size = float(last['bid_size'])
            ask_size = float(last['ask_size'])
            total_depth = bid_size + ask_size
            
            # Calculate microprice
            microprice = (float(last['bid_price']) * ask_size + 
                         float(last['ask_price']) * bid_size) / max(total_depth, 1e-12)
            
            # Normalize OFI and TFI
            norm_ofi = ofi_sum / max(total_depth, 1.0)
            norm_tfi = tfi_sum / max(total_vol, 1.0)
            
            return {
                'ofi': np.clip(norm_ofi, -1.0, 1.0),
                'tfi': np.clip(norm_tfi, -1.0, 1.0),
                'spread': max(0.0, spread),
                'microprice': microprice,
                'timestamp': current_time.isoformat()
            }
        except Exception as e:
            print(f"Error generating features: {e}")
            return {
                'ofi': 0.0,
                'tfi': 0.0,
                'spread': 0.0,
                'microprice': 0.0,
                'timestamp': pd.Timestamp.now(tz='UTC').isoformat()
            }

    def _push_lob(self, update: Dict[str, Any]):
        """Safe LOB update storage"""
        try:
            self.lob_buffer.append(update)
        except Exception as e:
            print(f"Error storing LOB update: {e}")

    def _push_trade(self, trade: Dict[str, Any]):
        """Safe trade storage"""
        try:
            self.trade_buffer.append(trade)
        except Exception as e:
            print(f"Error storing trade: {e}")
            

def initialize_data(engine):
    """Initialize data with error handling and progress tracking"""
    try:
        print("Loading tick data...")
        tick_data = load_tick_data("2025-08-11", engine)
        print(f"Loaded {len(tick_data)} tick records")
        
        print("Loading order data...")
        order_data = load_order_data("2025-08-11", engine)
        print(f"Loaded {len(order_data)} order records")
        
        processor = RollingOFITFIProcessor(
            max_updates=20000,  # Increased buffer size
            tfi_window_ms=600000  # 10 minutes in milliseconds
        )
        
        print("Processing tick data...")
        for _, row in tick_data.iterrows():
            processor.process_lob_update({
                'time': row['time'],
                'bid_price': row['bid_price'],
                'bid_size': row['bid_volume'],
                'ask_price': row['ask_price'],
                'ask_size': row['ask_volume']
            })
            
        print("Processing order data...")
        for _, row in order_data.iterrows():
            processor.process_trade({
                'time': row['time'],
                'side': row['side'],
                'volume': row['volume']
            })
            
        print("Data initialization complete")
        return tick_data, order_data, processor
        
    except Exception as e:
        print(f"Error initializing data: {e}")
        raise
    
    
    
    
@dataclass
class HybridFlowAnalyzer:
    """Enhanced analyzer with better data validation and normalization"""
    short_window: timedelta = field(default_factory=lambda: timedelta(seconds=1))
    long_window: timedelta = field(default_factory=lambda: timedelta(minutes=10))
    
    lob_updates: Deque[Dict[str, Any]] = field(default_factory=lambda: deque(maxlen=100000))
    trades: Deque[Dict[str, Any]] = field(default_factory=lambda: deque(maxlen=100000))
    
    last_bid: Tuple[float, float] = (0.0, 0.0)
    last_ask: Tuple[float, float] = (0.0, 0.0)
    
    def _validate_and_convert(self, data: Dict[str, Any], required_fields: List[str]) -> Optional[Dict[str, Any]]:
        """Helper method to validate and convert input data"""
        try:
            if not all(field in data for field in required_fields):
                return None
                
            result = {'time': pd.to_datetime(data['time'], errors='coerce')}
            if pd.isna(result['time']):
                return None
                
            for field in required_fields:
                if field == 'time':
                    continue
                result[field] = float(data[field])
                
            return result
        except (ValueError, TypeError):
            return None
    
    def update_lob(self, update: Dict[str, Any]):
        """Process LOB update with enhanced validation"""
        validated = self._validate_and_convert(
            update, 
            ['time', 'bid_price', 'bid_size', 'ask_price', 'ask_size']
        )
        if not validated:
            return
            
        t = validated['time']
        bid_p = validated['bid_price']
        bid_s = validated['bid_size']
        ask_p = validated['ask_price']
        ask_s = validated['ask_size']
        
        # Calculate OFI contribution
        ofi_inc = 0.0
        if self.last_bid[0] > 0:  # Have previous data
            if bid_p > self.last_bid[0]:  # Price improved
                ofi_inc += bid_s
            elif bid_p == self.last_bid[0]:  # Price unchanged
                ofi_inc += (bid_s - self.last_bid[1])
                
        if self.last_ask[0] > 0:
            if ask_p < self.last_ask[0]:  # Price improved
                ofi_inc -= ask_s
            elif ask_p == self.last_ask[0]:  # Price unchanged
                ofi_inc -= (ask_s - self.last_ask[1])
        
        # Calculate microprice with protection against zero division
        total_size = bid_s + ask_s
        microprice = (
            (bid_p * ask_s + ask_p * bid_s) / total_size 
            if total_size > 0 
            else (bid_p + ask_p) / 2
        )
        
        # Store update
        self.lob_updates.append({
            'time': t,
            'bid_price': bid_p,
            'bid_size': bid_s,
            'ask_price': ask_p,
            'ask_size': ask_s,
            'ofi_inc': ofi_inc,
            'spread': ask_p - bid_p,
            'microprice': microprice
        })
        
        # Update state
        self.last_bid = (bid_p, bid_s)
        self.last_ask = (ask_p, ask_s)

    def process_trade(self, trade: Dict[str, Any]):
        """Process trade with enhanced validation"""
        validated = self._validate_and_convert(
            trade, 
            ['time', 'volume', 'side']
        )
        if not validated:
            return
            
        t = validated['time']
        vol = validated['volume']
        side = trade['side'].upper()  # Original string value
        
        if side not in ['B', 'S']:
            return
            
        self.trades.append({
            'time': t,
            'volume': vol,
            'side': side,
            'tfi_inc': vol if side == 'B' else -vol
        })

    def get_current_stats(self) -> Dict[str, float]:
        """Get statistics with improved normalization and validation"""
        now = pd.Timestamp.now(tz='UTC')
        stats = {
            'spread': 0.0,
            'microprice': 0.0,
            'ofi_1s': 0.0,
            'ofi_10min': 0.0,
            'tfi_1s': 0.0,
            'tfi_10min': 0.0,
            'timestamp': now.isoformat()
        }
        
        if not self.lob_updates:
            return stats
            
        # Get most recent valid LOB state
        last_lob = self.lob_updates[-1]
        stats['spread'] = max(0.0, last_lob['spread'])
        stats['microprice'] = last_lob['microprice']
        
        # Calculate OFI metrics with normalization
        def calculate_normalized_ofi(data):
            if not data:
                return 0.0
                
            total_ofi = sum(x['ofi_inc'] for x in data)
            total_depth = sum(x['bid_size'] + x['ask_size'] for x in data)
            return total_ofi / max(total_depth, 1.0)
        
        ofi_1s_data = [x for x in self.lob_updates 
                      if x['time'] >= now - self.short_window]
        ofi_10min_data = [x for x in self.lob_updates 
                         if x['time'] >= now - self.long_window]
        
        stats['ofi_1s'] = np.clip(calculate_normalized_ofi(ofi_1s_data), -1.0, 1.0)
        stats['ofi_10min'] = np.clip(calculate_normalized_ofi(ofi_10min_data), -1.0, 1.0)
        
        # Calculate TFI metrics with normalization
        def calculate_normalized_tfi(data):
            if not data:
                return 0.0
                
            total_tfi = sum(x['tfi_inc'] for x in data)
            total_vol = sum(abs(x['tfi_inc']) for x in data)
            return total_tfi / max(total_vol, 1.0)
        
        tfi_1s_data = [x for x in self.trades 
                      if x['time'] >= now - self.short_window]
        tfi_10min_data = [x for x in self.trades 
                         if x['time'] >= now - self.long_window]
        
        stats['tfi_1s'] = np.clip(calculate_normalized_tfi(tfi_1s_data), -1.0, 1.0)
        stats['tfi_10min'] = np.clip(calculate_normalized_tfi(tfi_10min_data), -1.0, 1.0)
        
        return stats