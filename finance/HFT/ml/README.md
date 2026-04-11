# ML/RL Adaptive Trading System — Documentation

## Overview

`finance/HFT/ml/` is a self-contained machine learning and reinforcement learning trading system built on top of the existing HFT backtest infrastructure. It learns from historical market data, trains a policy that maximises risk-adjusted returns, and deploys that policy to live market data via the Matriz WebSocket.

The system targets three instrument types:
- **DLR futures** (`rx_DDF_DLR_*`) — MatbaRofex USD futures, tick data + order flow
- **GGAL options** (`bm_MERV_GFGC*`) — equity options with Black-Scholes Greeks
- **Binance crypto** (`BTCUSDT`, `USDTARS`) — 1-minute OHLCV bars

---

## Architecture

```
Historical DB (ticks + orders)
        │
        ▼
┌─────────────────┐
│   features.py   │  ← shared by all components
│  extract_features│
│  (13 features)  │
└────────┬────────┘
         │
    ┌────┴────────────────────────────┐
    │                                 │
    ▼                                 ▼
┌──────────────┐             ┌──────────────────┐
│ supervised.py│             │     env.py        │
│  LightGBM    │             │  TradingEnv       │
│  BUY/SELL/   │             │  (Gymnasium)      │
│  HOLD labels │             │  wraps Backtester │
└──────┬───────┘             └────────┬─────────┘
       │ behavioral                   │
       │ cloning init                 │
       ▼                              ▼
┌──────────────────────────────────────────────┐
│                  rl_agent.py                  │
│   PPO (stable-baselines3)                     │
│   BC pre-train → RL fine-tune                 │
│   saves models/{date}/ppo_{instrument}.zip    │
└──────────────────┬───────────────────────────┘
                   │ load_policy()
                   ▼
┌──────────────────────────────────────────────┐
│              live_runner.py                   │
│   Matriz WebSocket → rolling 30-tick window   │
│   → features → policy.predict()              │
│   → PositionState filter                      │
│   → paper (DB log) or live (PPI order)        │
└──────────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│              monitoring.py                    │
│   Redis (TTL=300s) + Prometheus Pushgateway   │
└──────────────────────────────────────────────┘
```

---

## Module Reference

### `features.py` — Feature Extraction

**Entry point:** `extract_features(ticks_df, trades_df, greeks_df=None) → pd.DataFrame`

Returns one row per tick timestamp. Index is UTC timestamp. All NaN-safe.

| Feature | Description | Range |
|---------|-------------|-------|
| `spread_bps` | Bid-ask spread in basis points | 0 → ∞ (DLR typical: 10–50 bps) |
| `bid_ask_imbalance` | (bid_vol − ask_vol) / (bid_vol + ask_vol) | −1 to +1 |
| `ofi_imbalance` | Order Flow Imbalance over 1-min window (reuses `calcultions.py`) | −1 to +1 |
| `vwap_deviation` | (mid − VWAP) / VWAP | typically −0.01 to +0.01 |
| `vol_surge_ratio` | current tick volume / rolling 10-tick mean volume | 0 → ∞ (>1.5 = surge) |
| `price_momentum_5` | % price change over last 5 ticks | −0.05 to +0.05 |
| `price_momentum_20` | % price change over last 20 ticks | −0.10 to +0.10 |
| `delta` | Option delta (0 for non-option instruments) | 0 to 1 |
| `gamma` | Option gamma | 0 → small positive |
| `vega` | Option vega | 0 → positive |
| `theta` | Option theta (time decay, negative) | negative |
| `iv` | Implied volatility | 0 to 2+ |
| `underlying_mid` | GGAL equity mid-price at signal time | ARS price |

**Important:** `CORE_FEATURE_COLS` (the first 7) are always populated. Greeks are `NaN` for DLR/Binance and filled with `0.0` before training.

**Batch vs streaming difference:** `vwap_deviation` and `spread_bps` will differ between batch (full-day VWAP) and live (rolling 30-tick window). This is expected and correct — the live system cannot see future prices. Use `validate_features.py` to quantify this gap.

---

### `supervised.py` — LightGBM Baseline

**Purpose:** Trains a 3-class classifier to predict the direction of the next price move.

**Label generation:**
- Forward return = `price_momentum_5` shifted back 10 ticks
- `BUY (1)` if forward return > `label_threshold_bps` (default 10 bps)
- `SELL (−1)` if forward return < −`label_threshold_bps`
- `HOLD (0)` otherwise (most ticks — this is intentional, noise suppression)

**Training:**
```bash
# Train on all available contracts
PYTHONPATH=. python -m finance.HFT.ml.supervised --instrument DLR

# Train on specific contract only
PYTHONPATH=. python -m finance.HFT.ml.supervised --instrument DLR --contract OCT25

# Train with explicit version tag
PYTHONPATH=. python -m finance.HFT.ml.supervised --instrument DLR --model_version 2026-03-25
```

**Model artifacts:** `finance/HFT/ml/models/{YYYY-MM-DD}/lgbm_{instrument}.pkl`
`finance/HFT/ml/models/latest` → symlink to most recent training date

**Programmatic use:**
```python
from finance.HFT.ml.supervised import load_model, predict, predict_proba

model = load_model('DLR')                    # loads latest
model = load_model('DLR', '2026-03-25')      # loads specific version

action = predict(model, feature_vector)      # returns -1, 0, or 1
probs  = predict_proba(model, feature_vector) # returns [p_sell, p_hold, p_buy]
```

**Interpreting results:**
- Class imbalance is expected: ~90% HOLD, ~5% BUY, ~5% SELL
- `class_weight='balanced'` corrects for this during training
- Feature importances show which signals the model relies on most
- Validation accuracy of ~68% on DLR OCT25 is reasonable for HFT (random = 33%)

---

### `env.py` — Gymnasium Trading Environment

**Purpose:** Wraps `MarketDataBacktester` as a standard RL environment for training PPO.

**Spaces:**
- `observation_space`: `Box(−∞, +∞, shape=(13,), float32)` — the 13-feature vector
- `action_space`: `Discrete(3)` — 0=HOLD, 1=BUY, 2=SELL

**Reward:** Clipped P&L delta per step × 1e-5 (scaled to ~[−1, +1])
- Positive reward when position moves in your favour
- Negative reward on losses and commissions (0.5% per side)

**Episode:** One trading day. `reset()` picks a random date from available data.

**Smoke test:**
```bash
PYTHONPATH=. python -m finance.HFT.ml.env
# Output: Steps: 8819  Total reward: -20.17  Final value: -17,237
```

A negative reward with random actions is expected — the environment is realistic (commissions eat random traders).

**Programmatic use:**
```python
from finance.HFT.ml.env import TradingEnv

env = TradingEnv('DLR', initial_capital=2_000_000)
env = TradingEnv('GGAL')
env = TradingEnv('BTCUSDT')

# Custom date list
env = TradingEnv('DLR', dates=['2025-10-02', '2025-10-03'])

obs, info = env.reset()
obs, reward, done, truncated, info = env.step(1)  # BUY
print(info['portfolio_value'])
```

---

### `rl_agent.py` — PPO with Behavioral Cloning

**Purpose:** Trains a PPO agent that starts from the LightGBM policy (behavioral cloning) and fine-tunes via RL.

**Two-phase training:**

**Phase 1 — Behavioral Cloning (BC):**
- Rolls out the LightGBM model on `bc_episodes` (default 20) episodes
- Optionally enforces regime diversity: keeps sampling until ≥3 distinct (spread, volume, momentum) regime buckets are covered (`--bc_diversity`)
- Pre-trains PPO's neural network via cross-entropy loss on (obs, action) pairs
- Result: PPO starts with a policy that already knows the LightGBM heuristics

**Phase 2 — PPO Fine-tuning:**
- Standard PPO on `TradingEnv` for `ppo_timesteps` (default 100,000) steps
- Uses 4 parallel environments for faster sampling
- `EvalCallback` evaluates every 10,000 steps on a held-out env

**Training:**
```bash
# Full training (BC + PPO)
PYTHONPATH=. python -m finance.HFT.ml.rl_agent --instrument DLR --timesteps 100000

# With regime diversity enforcement
PYTHONPATH=. python -m finance.HFT.ml.rl_agent --instrument DLR --bc_diversity

# Quick test run
PYTHONPATH=. python -m finance.HFT.ml.rl_agent --instrument DLR --timesteps 10000

# Specific version tag
PYTHONPATH=. python -m finance.HFT.ml.rl_agent --instrument DLR --model_version 2026-03-26
```

**Model artifacts:** `finance/HFT/ml/models/{YYYY-MM-DD}/ppo_{instrument}.zip`

**Programmatic use:**
```python
from finance.HFT.ml.rl_agent import load_policy

policy = load_policy('DLR')               # loads latest
policy = load_policy('DLR', '2026-03-25') # loads specific version

action, _states = policy.predict(obs, deterministic=True)  # 0/1/2
```

---

### `live_runner.py` — Live Trading

**Purpose:** Connects to Matriz WebSocket, builds a rolling feature window, and fires signals via the trained PPO policy.

**Signal filtering (PositionState):**
- No duplicate signals (won't BUY if already long)
- Minimum cooldown between trades (default 5s, configurable)
- Maximum position size per instrument (default 100, configurable)
- Pending order flag (won't send new signal while waiting for fill confirmation)

**Paper mode** (default, safe):
- Signals logged to `bt_strategy_runs` with `strategy='ppo_live'`
- Metadata includes: `signal_price`, `simulated_fill_price` (±spread/2), `simulated_pnl`, `position_after_signal`, `regime`
- No real orders sent

**Live mode** (real orders via PPI):
- Calls `account_ppi.py` → `ppi.order.send()`
- On SIGINT: flattens open position, waits up to 5s for fill, logs final P&L as `ppo_live_shutdown`

**Running:**
```bash
# Paper trading (safe, no real orders)
PYTHONPATH=. python -m finance.HFT.ml.live_runner \
  --mode paper \
  --instrument DLR \
  --session-id YOUR_SESSION_ID \
  --conn-id YOUR_CONN_ID

# Live trading
PYTHONPATH=. python -m finance.HFT.ml.live_runner \
  --mode live \
  --instrument DLR \
  --max_position 2 \
  --cooldown_seconds 10 \
  --session-id YOUR_SESSION_ID \
  --conn-id YOUR_CONN_ID

# Use specific model version
PYTHONPATH=. python -m finance.HFT.ml.live_runner \
  --mode paper \
  --instrument DLR \
  --model_version 2026-03-25 \
  --session-id YOUR_SESSION_ID \
  --conn-id YOUR_CONN_ID
```

**Getting session credentials:** The Matriz session_id and conn_id are stored in the `cookies` table in PostgreSQL (refreshed by the scraper). Query:
```sql
SELECT session_id, conn_id FROM cookies ORDER BY created_at DESC LIMIT 1;
```

---

### `validate_features.py` — Feature Alignment Validator

**Purpose:** Verifies that the batch (backtest) and streaming (live) feature extraction paths produce consistent results. Run this before deploying a new model to live.

```bash
PYTHONPATH=. python -m finance.HFT.ml.validate_features --date 2025-10-03 --instrument DLR
```

**Output:**
- `PASS` — all features align within tolerance (1e-6)
- `FAIL` — lists each timestamp, feature, batch value, stream value, and delta

**Expected mismatches:** `vwap_deviation` will always differ slightly because batch uses full-day VWAP while streaming uses a rolling 30-tick window. This is correct behaviour, not a bug. The magnitude of the difference tells you how much the live model's VWAP signal diverges from what was trained on.

---

### `monitoring.py` — Metrics

**Purpose:** Pushes training and inference metrics to Redis (real-time) and Prometheus Pushgateway (Grafana).

**Redis keys** (TTL=300s unless noted):

| Key | Content | TTL |
|-----|---------|-----|
| `ml:training:{instrument}` | `{epoch, loss, accuracy}` | 5 min |
| `ml:rl_episode:{instrument}` | `{episode, reward, steps, regimes_covered}` | 5 min |
| `ml:rl_history:{instrument}` | List of last 100 episodes (JSON) | 24h |
| `ml:last_signal:{instrument}` | `{action, price, ts}` | 5 min |
| `ml:position:{instrument}` | `{position, pnl}` | 5 min |

**Query Redis directly:**
```bash
redis-cli get ml:training:DLR
redis-cli get ml:rl_episode:DLR
redis-cli lrange ml:rl_history:DLR 0 9    # last 10 episodes
redis-cli get ml:last_signal:rx_DDF_DLR_MAR26
redis-cli get ml:position:DLR
```

**Prometheus metrics** (scraped via Pushgateway at `localhost:9091`):

| Metric | Labels | Description |
|--------|--------|-------------|
| `algotrading_ml_training_loss` | `instrument` | LightGBM validation loss |
| `algotrading_ml_training_accuracy` | `instrument` | Validation accuracy |
| `algotrading_ml_training_epoch` | `instrument` | Number of boosting rounds |
| `algotrading_ml_rl_episode_reward` | `instrument` | Last episode cumulative reward |
| `algotrading_ml_rl_episode_steps` | `instrument` | Last episode length (ticks) |
| `algotrading_ml_rl_regimes_covered` | `instrument` | BC regime diversity count |
| `algotrading_ml_live_signal` | `instrument` | Last signal: 1=BUY, −1=SELL, 0=HOLD |
| `algotrading_ml_live_signal_price` | `instrument` | Price at last signal |
| `algotrading_ml_live_position` | `instrument` | Current open position size |
| `algotrading_ml_live_pnl` | `instrument` | Simulated running P&L (ARS) |

**Programmatic use:**
```python
from finance.HFT.ml.monitoring import MLMonitor

mon = MLMonitor('DLR')
mon.log_training_step(epoch=300, loss=0.797, accuracy=0.68)
mon.log_episode(episode=42, reward=0.15, steps=8819, regimes_covered=4)
mon.log_signal('BUY', 'rx_DDF_DLR_MAR26', 1502.5)
mon.log_position(position=1, pnl=1500.0)
```

---

## Configuration (`config.yaml`)

All tuneable parameters in one place:

```yaml
live:
  max_position: 100        # max contracts per instrument
  cooldown_seconds: 5      # min seconds between signals
  default_mode: paper      # paper | live
  flatten_on_shutdown: true # close position on SIGINT if live

training:
  label_threshold_bps: 10  # min return to label as BUY/SELL (noise filter)
  bc_episodes: 20          # LightGBM rollout episodes for BC init
  bc_diversity_required: true  # enforce regime coverage in BC
  ppo_timesteps: 100000    # PPO fine-tuning steps

features:
  rolling_window_size: 30  # ticks in live rolling window
  vwap_lookback_ticks: 20  # ticks for VWAP calculation
```

---

## End-to-End Usage Guide

### Step 1 — Install dependencies (once)
```bash
pip install lightgbm stable-baselines3 gymnasium torch imitation
```

### Step 2 — Train supervised baseline
```bash
PYTHONPATH=. python -m finance.HFT.ml.supervised --instrument DLR
```
Takes ~2–5 min. Prints classification report and feature importances.

### Step 3 — Validate feature alignment
```bash
PYTHONPATH=. python -m finance.HFT.ml.validate_features --date 2025-10-03 --instrument DLR
```
Expected: FAIL with ~600 mismatches on `vwap_deviation` only. If other features mismatch, investigate before proceeding.

### Step 4 — Train RL agent
```bash
PYTHONPATH=. python -m finance.HFT.ml.rl_agent --instrument DLR --timesteps 100000 --bc_diversity
```
Takes ~10–30 min. Watch the eval reward trend upward.

### Step 5 — Backtest the trained strategies
```bash
# Compare LightGBM vs PPO vs rule-based on same dates
PYTHONPATH=. python -m finance.HFT.backtest.run_strategies --strategy lgbm --contract OCT25
PYTHONPATH=. python -m finance.HFT.backtest.run_strategies --strategy ppo  --contract OCT25

# See comparative report
PYTHONPATH=. python -m finance.HFT.backtest.bt_report --best
```

### Step 6 — Paper trade live
```bash
SESSION=$(psql -h 100.112.16.115 -U postgres -d marketdata -t -c \
  "SELECT session_id FROM cookies ORDER BY created_at DESC LIMIT 1;")
CONN=$(psql -h 100.112.16.115 -U postgres -d marketdata -t -c \
  "SELECT conn_id FROM cookies ORDER BY created_at DESC LIMIT 1;")

PYTHONPATH=. python -m finance.HFT.ml.live_runner \
  --mode paper --instrument DLR \
  --session-id $SESSION --conn-id $CONN
```

### Step 7 — Monitor
```bash
# Real-time Redis
watch -n 2 'redis-cli get ml:last_signal:rx_DDF_DLR_MAR26'
watch -n 5 'redis-cli get ml:position:DLR'

# Paper trade history
psql -h 100.112.16.115 -U postgres -d marketdata -c \
  "SELECT date, metadata FROM bt_strategy_runs WHERE strategy='ppo_live' ORDER BY run_at DESC LIMIT 20;"
```

---

## Retraining Strategy

| Trigger | Action |
|---------|--------|
| New contract month | Retrain both LightGBM and PPO with `--model_version YYYY-MM-DD` |
| Sharpe drops below 0.5 in paper mode | Retrain PPO only (BC from existing LightGBM) |
| Feature importance shifts significantly | Retrain LightGBM first, then PPO |
| Market regime change (e.g. volatility spike) | Retrain with `--bc_diversity` to ensure regime coverage |

---

## Known Limitations

1. **VWAP batch/live gap** — live VWAP uses a 30-tick rolling window; batch uses full-day. The model was trained on batch features, so live `vwap_deviation` will be noisier. Mitigate by increasing `rolling_window_size` in `config.yaml`.

2. **DLR multiplier** — 1 contract = 1000 USD notional. At ARS 1500/USD, 1 contract ≈ ARS 1.5M. The default `initial_capital=2_000_000` only supports 1 contract at a time. Increase capital or reduce `max_position` accordingly.

3. **GGAL options Greeks** — Greeks are only populated when `greeks_df` is passed to `extract_features`. The live runner currently doesn't compute Greeks in real-time (it would need the Black-Scholes pipeline from `livedata/order_book.py` wired in). For now, options features fall back to the 7 core LOB features.

4. **Binance synthetic trades** — Binance data is 1-min OHLCV, not tick-level. Trades are synthesised (open+close per bar). OFI signal is weaker than for DLR where real order flow is available.
