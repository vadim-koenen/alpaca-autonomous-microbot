"""SQLite schema and storage helpers for the advisory shadow learner."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "memory" / "shadow_learner.sqlite3"
ENV_DB_PATH = "SHADOW_LEARNER_DB"

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS shadow_feature_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    created_at_utc TEXT NOT NULL,
    broker TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    scan_id TEXT,
    price REAL,
    bid REAL,
    ask REAL,
    spread_pct REAL,
    quote_age_seconds REAL,
    bars_available INTEGER,
    market_session TEXT,
    market_data_status TEXT,
    skip_reason TEXT,
    risk_block_reason TEXT,
    features_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_shadow_snapshots_created
    ON shadow_feature_snapshots(created_at_utc);
CREATE INDEX IF NOT EXISTS idx_shadow_snapshots_symbol
    ON shadow_feature_snapshots(symbol);
CREATE INDEX IF NOT EXISTS idx_shadow_snapshots_strategy
    ON shadow_feature_snapshots(strategy);

CREATE TABLE IF NOT EXISTS shadow_predictions (
    prediction_id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    broker TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    prediction_type TEXT NOT NULL,
    prediction_value REAL NOT NULL,
    confidence REAL NOT NULL,
    horizon_minutes INTEGER NOT NULL,
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    feature_version TEXT NOT NULL,
    would_trade INTEGER NOT NULL DEFAULT 0,
    live_trade_taken INTEGER NOT NULL DEFAULT 0,
    reason_json TEXT NOT NULL,
    FOREIGN KEY(snapshot_id) REFERENCES shadow_feature_snapshots(snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_shadow_predictions_created
    ON shadow_predictions(created_at_utc);
CREATE INDEX IF NOT EXISTS idx_shadow_predictions_snapshot
    ON shadow_predictions(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_shadow_predictions_type
    ON shadow_predictions(prediction_type);
CREATE INDEX IF NOT EXISTS idx_shadow_predictions_horizon
    ON shadow_predictions(horizon_minutes);

CREATE TABLE IF NOT EXISTS shadow_outcomes (
    prediction_id TEXT PRIMARY KEY,
    labeled_at_utc TEXT NOT NULL,
    horizon_minutes INTEGER NOT NULL,
    future_return_pct REAL,
    max_favorable_excursion_pct REAL,
    max_adverse_excursion_pct REAL,
    hit_take_profit INTEGER,
    hit_stop_loss INTEGER,
    market_data_available INTEGER NOT NULL,
    outcome_status TEXT NOT NULL,
    outcome_json TEXT NOT NULL,
    FOREIGN KEY(prediction_id) REFERENCES shadow_predictions(prediction_id)
);

CREATE INDEX IF NOT EXISTS idx_shadow_outcomes_status
    ON shadow_outcomes(outcome_status);
CREATE INDEX IF NOT EXISTS idx_shadow_outcomes_horizon
    ON shadow_outcomes(horizon_minutes);

CREATE TABLE IF NOT EXISTS shadow_evaluation_runs (
    run_id TEXT PRIMARY KEY,
    created_at_utc TEXT NOT NULL,
    window_start_utc TEXT,
    window_end_utc TEXT,
    model_name TEXT,
    model_version TEXT,
    sample_count INTEGER NOT NULL,
    accuracy REAL,
    precision REAL,
    recall REAL,
    brier_score REAL,
    avg_return_when_positive REAL,
    notes_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_shadow_eval_created
    ON shadow_evaluation_runs(created_at_utc);

CREATE TABLE IF NOT EXISTS shadow_price_points (
    price_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    symbol TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL NOT NULL,
    volume REAL,
    timeframe TEXT NOT NULL,
    ingested_at_utc TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE(source, symbol, timeframe, timestamp_utc)
);

CREATE INDEX IF NOT EXISTS idx_shadow_price_symbol_time
    ON shadow_price_points(symbol, timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_shadow_price_source
    ON shadow_price_points(source);
CREATE INDEX IF NOT EXISTS idx_shadow_price_timeframe
    ON shadow_price_points(timeframe);

CREATE TABLE IF NOT EXISTS shadow_news_items (
    news_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_url TEXT,
    title TEXT NOT NULL,
    summary TEXT,
    published_at_utc TEXT,
    ingested_at_utc TEXT NOT NULL,
    raw_text_hash TEXT NOT NULL,
    symbols_json TEXT NOT NULL,
    sectors_json TEXT NOT NULL,
    themes_json TEXT NOT NULL,
    sentiment_score REAL NOT NULL,
    impact_score REAL NOT NULL,
    time_horizon TEXT NOT NULL,
    source_reliability REAL NOT NULL,
    duplicate_group_id TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_shadow_news_published
    ON shadow_news_items(published_at_utc);
CREATE INDEX IF NOT EXISTS idx_shadow_news_source
    ON shadow_news_items(source);
CREATE INDEX IF NOT EXISTS idx_shadow_news_duplicate
    ON shadow_news_items(duplicate_group_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_shadow_news_source_hash
    ON shadow_news_items(source, raw_text_hash);

CREATE TABLE IF NOT EXISTS shadow_news_signal_links (
    link_id TEXT PRIMARY KEY,
    news_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    theme TEXT NOT NULL,
    direction_hint TEXT NOT NULL,
    confidence REAL NOT NULL,
    reason_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    FOREIGN KEY(news_id) REFERENCES shadow_news_items(news_id)
);

CREATE INDEX IF NOT EXISTS idx_shadow_news_links_news
    ON shadow_news_signal_links(news_id);
CREATE INDEX IF NOT EXISTS idx_shadow_news_links_symbol
    ON shadow_news_signal_links(symbol);
CREATE INDEX IF NOT EXISTS idx_shadow_news_links_theme
    ON shadow_news_signal_links(theme);

CREATE TABLE IF NOT EXISTS shadow_news_outcomes (
    news_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    horizon_minutes INTEGER NOT NULL,
    labeled_at_utc TEXT NOT NULL,
    future_return_pct REAL,
    max_favorable_excursion_pct REAL,
    max_adverse_excursion_pct REAL,
    outcome_status TEXT NOT NULL,
    outcome_json TEXT NOT NULL,
    PRIMARY KEY(news_id, symbol, horizon_minutes),
    FOREIGN KEY(news_id) REFERENCES shadow_news_items(news_id)
);

CREATE INDEX IF NOT EXISTS idx_shadow_news_outcomes_status
    ON shadow_news_outcomes(outcome_status);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def resolve_db_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    configured = os.environ.get(ENV_DB_PATH, "").strip()
    if configured:
        return Path(configured)
    return DEFAULT_DB_PATH


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    db_path = resolve_db_path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: str | Path | None = None) -> Path:
    db_path = resolve_db_path(path)
    with connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
    return db_path


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def json_dumps(payload: dict[str, Any] | list[Any] | None) -> str:
    return json.dumps({} if payload is None else payload, sort_keys=True, default=str)


def bool_to_int(value: bool) -> int:
    return 1 if value else 0
