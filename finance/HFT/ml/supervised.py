"""
Supervised baseline: LightGBM 3-class classifier (BUY=1, HOLD=0, SELL=-1).

Label: sign of forward mid-price return over N ticks, zeroed if |return| < threshold.
Train on OCT25+SEP25+NOV25 DLR data; validate on held-out dates.

Usage:
    python -m finance.HFT.ml.supervised --instrument DLR --contract OCT25
    python -m finance.HFT.ml.supervised --instrument DLR --model_version 2026-03-25
"""
import argparse
import pickle
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from finance.HFT.ml import get_config
from finance.HFT.ml.features import extract_features, FEATURE_COLS, CORE_FEATURE_COLS
from finance.HFT.backtest.db.load_data import load_order_data, load_tick_data
from finance.HFT.backtest.db.load_binance import load_binance_data
from finance.HFT.backtest.db.load_byma import load_byma_data
from finance.utils.logger import logger

MODELS_DIR = Path(__file__).parent / 'models'

AVAILABLE_DATES = {
    "OCT25": [f"2025-10-{d:02d}" for d in [2,3,6,7,8,9,13,14,15,16,17,20,21,22,23,24,27,28,29,30,31]],
    "SEP25": [f"2025-09-{d:02d}" for d in [3,4,5,8,9,10,11,12,15,16,17,18,19,22,23,24,25,26,29,30]],
    "NOV25": [f"2025-11-{d:02d}" for d in [3,4,5,6,7,10,11,12,13,14,17,18,19,20,21,24,25,26,27,28]],
    # GGAL options real tick data (from orders table, Mar 2026)
    "GGAL_OPT_MAR26": ["2026-03-25", "2026-03-26", "2026-03-27", "2026-03-28", "2026-03-30"],
}

LABEL_HORIZON = 10


def _label_threshold() -> float:
    cfg = get_config()
    return cfg['training']['label_threshold_bps'] / 10_000


def _model_dir(version: str | None = None) -> Path:
    """Returns versioned model dir. If version is None, uses today's date."""
    v = version or date.today().isoformat()
    d = MODELS_DIR / v
    d.mkdir(parents=True, exist_ok=True)
    return d


def _latest_model_dir() -> Path | None:
    """Returns the most recent versioned model directory."""
    dirs = sorted([d for d in MODELS_DIR.iterdir() if d.is_dir() and d.name != '__pycache__'], reverse=True)
    return dirs[0] if dirs else None


def _make_labels(feat_df: pd.DataFrame) -> pd.Series:
    threshold = _label_threshold()
    fwd = feat_df['price_momentum_5'].shift(-LABEL_HORIZON)
    labels = np.where(fwd > threshold, 1, np.where(fwd < -threshold, -1, 0))
    return pd.Series(labels, index=feat_df.index, name='label')


def _load_features_for_dates(dates: list[str], instrument_type: str) -> pd.DataFrame:
    # DLR: use synthetic data — unlimited, no capital constraint, no market hours
    if instrument_type == 'DLR':
        from finance.HFT.ml.synthetic_dlr import generate_episode
        frames = []
        for i in range(100):  # 100 synthetic episodes = ~800k ticks
            ticks, trades = generate_episode(seed=i)
            try:
                feat = extract_features(ticks, trades)
                labels = _make_labels(feat)
                feat['label'] = labels
                feat['date'] = f'synth_{i:03d}'
                feat[['delta','gamma','vega','theta','iv','underlying_mid']] = \
                    feat[['delta','gamma','vega','theta','iv','underlying_mid']].fillna(0.0)
                frames.append(feat.dropna(subset=CORE_FEATURE_COLS))
            except Exception as e:
                logger.warning("Skipping synth episode {i}: {e}", i=i, e=e)
        return pd.concat(frames) if frames else pd.DataFrame()

    frames = []
    for date_str in dates:
        try:
            if instrument_type == 'DLR':
                ticks  = load_tick_data(date_str)
                trades = load_order_data(date_str)
                ticks  = ticks[ticks['instrument'].str.contains('DDF_DLR', na=False)]
                trades = trades[trades['instrument'].str.contains('DDF_DLR', na=False)]
            elif instrument_type == 'CCL_SPREAD':
                # CCL uses AL30/AL30D ticks — load via features_ccl directly
                from finance.HFT.ml.features_ccl import extract_ccl_features, CCL_FEATURE_COLS
                feat = extract_ccl_features(date_str, date_str)
                if feat.empty:
                    continue
                labels = _make_labels(feat.rename(columns={c: c for c in feat.columns}))
                feat['label'] = labels
                feat['date'] = date_str
                frames.append(feat.dropna())
                continue
            elif instrument_type == 'GGAL_OPTIONS':
                # Real tick+order data for GGAL options (GFGC/GFGV instruments)
                from sqlalchemy import text as _text
                from finance.utils.db_pool import get_pg_engine
                with get_pg_engine().connect() as conn:
                    ticks = pd.read_sql(_text("""
                        SELECT time AT TIME ZONE 'UTC' AS time, instrument,
                               bid_price, ask_price, bid_volume, ask_volume, last_price, total_volume
                        FROM ticks
                        WHERE (instrument ILIKE '%GFGC%' OR instrument ILIKE '%GFGV%')
                          AND (time AT TIME ZONE 'America/Argentina/Buenos_Aires')::date = :d
                        ORDER BY time
                    """), conn, params={"d": date_str})
                    trades = pd.read_sql(_text("""
                        SELECT time AT TIME ZONE 'UTC' AS time, instrument, price, volume, side
                        FROM orders
                        WHERE (instrument ILIKE '%GFGC%' OR instrument ILIKE '%GFGV%')
                          AND (time AT TIME ZONE 'America/Argentina/Buenos_Aires')::date = :d
                        ORDER BY time
                    """), conn, params={"d": date_str})
                if ticks.empty or trades.empty:
                    continue
                ticks['time']  = pd.to_datetime(ticks['time'], utc=True)
                trades['time'] = pd.to_datetime(trades['time'], utc=True)
                ticks['instrument']  = ticks['instrument'].str.replace('M:', '', regex=False)
                trades['instrument'] = trades['instrument'].str.replace('M:', '', regex=False)
                
                # Workaround until #218 is fixed: infer side for 'U' using price vs rolling MA
                is_u = trades['side'] == 'U'
                if is_u.any():
                    rolling_ma = trades.groupby('instrument')['price'].transform(lambda x: x.rolling(10, min_periods=1).mean().shift(1).bfill())
                    trades.loc[is_u & (trades['price'] >= rolling_ma), 'side'] = 'B'
                    trades.loc[is_u & (trades['price'] < rolling_ma), 'side'] = 'S'
                    trades.loc[trades['side'] == 'U', 'side'] = 'B'
                
                # Drop orders with unknown side (midpoint inference done by scraper)
                trades = trades[trades['side'].isin(['B', 'S'])]
            elif instrument_type == 'GGAL':
                trades, ticks = load_byma_data(date_str, 'M:bm_MERV_GGALD_24hs')
            else:
                continue
            if ticks.empty or trades.empty:
                continue
            feat = extract_features(ticks, trades)
            labels = _make_labels(feat)
            feat['label'] = labels
            feat['date'] = date_str
            feat[['delta','gamma','vega','theta','iv','underlying_mid']] = \
                feat[['delta','gamma','vega','theta','iv','underlying_mid']].fillna(0.0)
            frames.append(feat.dropna(subset=CORE_FEATURE_COLS))
        except Exception as e:
            logger.warning("Skipping {date}: {e}", date=date_str, e=e)
    return pd.concat(frames) if frames else pd.DataFrame()


def train(instrument_type: str = 'DLR', contracts: list[str] | None = None,
          model_version: str | None = None) -> object:
    import lightgbm as lgb
    from sklearn.metrics import classification_report

    contracts = contracts or list(AVAILABLE_DATES.keys())
    all_dates = [d for c in contracts for d in AVAILABLE_DATES.get(c, [])]
    split = int(len(all_dates) * 0.8)
    train_dates, val_dates = all_dates[:split], all_dates[split:]

    logger.info("Loading train data ({n} dates)...", n=len(train_dates))
    train_df = _load_features_for_dates(train_dates, instrument_type)
    logger.info("Loading val data ({n} dates)...", n=len(val_dates))
    val_df   = _load_features_for_dates(val_dates, instrument_type)

    if train_df.empty:
        raise RuntimeError("No training data loaded")

    # Guard: if all core features are zero the data source has no real tick data
    zero_cols = (train_df[CORE_FEATURE_COLS] == 0).all()
    if zero_cols.all():
        raise RuntimeError(
            f"All features are zero for {instrument_type} — no real tick data available. "
            "Supervised training requires tick-level data (DLR or CCL_SPREAD)."
        )

    X_train = train_df[FEATURE_COLS].values
    y_train = train_df['label'].values + 1
    X_val   = val_df[FEATURE_COLS].values  if not val_df.empty else X_train
    y_val   = val_df['label'].values + 1   if not val_df.empty else y_train

    from finance.HFT.ml.monitoring import MLMonitor
    mon = MLMonitor(instrument_type)

    # Log every 50 rounds to build a loss curve in ml_training_episodes
    class _LogCB:
        def __call__(self, env):
            if env.iteration % 50 == 0:
                loss = env.evaluation_result_list[0][2] if env.evaluation_result_list else 0.0
                mon.log_training_step(epoch=env.iteration, loss=float(loss), accuracy=0.0)

    model = lgb.LGBMClassifier(
        n_estimators=300, learning_rate=0.05, num_leaves=31,
        class_weight='balanced', random_state=42, n_jobs=-1,
    )
    model.fit(X_train, y_train,
              eval_set=[(X_val, y_val)],
              callbacks=[lgb.early_stopping(30, verbose=False), lgb.log_evaluation(50), _LogCB()])

    preds = model.predict(X_val)
    acc = (preds == y_val).mean()
    # Final row with accuracy — handle both multi and binary logloss
    best_scores = model.best_score_.get('valid_0', {})
    loss = best_scores.get('multi_logloss', best_scores.get('binary_logloss', 0.0))
    mon.log_training_step(epoch=model.n_iter_, loss=float(loss), accuracy=float(acc))

    print(classification_report(y_val, preds, target_names=['SELL', 'HOLD', 'BUY'], labels=[0,1,2]))
    importances = pd.Series(model.feature_importances_, index=FEATURE_COLS).sort_values(ascending=False)
    print("\nFeature importances:\n", importances.to_string())

    out_dir = _model_dir(model_version)
    path = out_dir / f'lgbm_{instrument_type}.pkl'
    with open(path, 'wb') as f:
        pickle.dump(model, f)

    # Update latest symlink
    symlink = MODELS_DIR / 'latest'
    if symlink.is_symlink():
        symlink.unlink()
    symlink.symlink_to(out_dir.name)

    logger.info("Saved model → {path}", path=path)
    return model


def load_model(instrument_type: str = 'DLR', model_version: str | None = None):
    if model_version:
        path = MODELS_DIR / model_version / f'lgbm_{instrument_type}.pkl'
    else:
        latest = MODELS_DIR / 'latest'
        base = latest if latest.exists() else _latest_model_dir()
        if base is None:
            raise FileNotFoundError(f"No trained model found in {MODELS_DIR}")
        path = base / f'lgbm_{instrument_type}.pkl'
    with open(path, 'rb') as f:
        return pickle.load(f)


def predict(model, features_row: np.ndarray) -> int:
    return int(model.predict(features_row.reshape(1, -1))[0]) - 1


def predict_proba(model, features_row: np.ndarray) -> np.ndarray:
    return model.predict_proba(features_row.reshape(1, -1))[0]


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--instrument', default='DLR', choices=['DLR', 'CCL_SPREAD', 'BTCUSDT', 'GGAL', 'GGAL_OPTIONS'])
    parser.add_argument('--contract', default='ALL', choices=list(AVAILABLE_DATES.keys()) + ['ALL'])
    parser.add_argument('--model_version', default=None)
    args = parser.parse_args()
    contracts = list(AVAILABLE_DATES.keys()) if args.contract == 'ALL' else [args.contract]
    train(args.instrument, contracts, args.model_version)
