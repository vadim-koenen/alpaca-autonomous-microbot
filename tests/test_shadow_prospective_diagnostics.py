"""Tests for Shadow Prospective Diagnostics."""

from __future__ import annotations

import json
import sqlite3
import pytest
from pathlib import Path

from shadow_learner.prospective_diagnostics import (
    ProspectiveAnalyzer,
    CONCLUSION_INSUFFICIENT,
    CONCLUSION_NO_EDGE,
    CONCLUSION_DATA_QUALITY,
    CONCLUSION_PROMISING,
    PROSPECTIVE_RANDOM_BASELINE,
)
from shadow_learner.schema import init_db, connect, json_dumps


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test_shadow_learner.sqlite3"
    init_db(db_path)
    return db_path


def test_analyzer_fetch_filtering(temp_db):
    analyzer = ProspectiveAnalyzer(db_path=temp_db)
    
    with connect(temp_db) as conn:
        # Prospective row
        conn.execute(
            "INSERT INTO shadow_predictions (prediction_id, snapshot_id, created_at_utc, broker, asset_class, symbol, strategy, prediction_type, prediction_value, confidence, horizon_minutes, model_name, model_version, feature_version, reason_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "pred_1", "snap_1", "2026-05-28T10:00:00Z", "alpaca", "equity", "AAPL", "trend", "return_direction_60m", 0.6, 0.2, 60, "model_a", "1.0", "1.0",
                json_dumps({"prospective_shadow_generated": True, "retrospective_generated": False, "no_live_trading_influence": True, "uses_only_t0_or_prior_data": True})
            )
        )
        # Retrospective row (should be filtered out)
        conn.execute(
            "INSERT INTO shadow_predictions (prediction_id, snapshot_id, created_at_utc, broker, asset_class, symbol, strategy, prediction_type, prediction_value, confidence, horizon_minutes, model_name, model_version, feature_version, reason_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "pred_2", "snap_2", "2026-05-28T10:00:00Z", "alpaca", "equity", "AAPL", "trend", "return_direction_60m", 0.6, 0.2, 60, "model_a", "1.0", "1.0",
                json_dumps({"prospective_shadow_generated": False, "retrospective_generated": True})
            )
        )
        conn.commit()

    rows = analyzer.fetch_data()
    assert len(rows) == 1
    assert rows[0]["prediction_id"] == "pred_1"


def test_diagnostics_insufficient_data(temp_db):
    analyzer = ProspectiveAnalyzer(db_path=temp_db)
    results = analyzer.run_diagnostics([])
    assert results["conclusion"] == CONCLUSION_INSUFFICIENT


def test_diagnostics_audit_failure(temp_db):
    analyzer = ProspectiveAnalyzer(db_path=temp_db)
    rows = [
        {
            "prediction_id": "p1",
            "prediction_value": 0.6,
            "confidence": 0.1,
            "reason_json": json_dumps({"prospective_shadow_generated": True, "uses_only_t0_or_prior_data": False}),
            "outcome_status": "labeled",
            "future_return_pct": 0.01,
            "model_name": "model_a",
            "symbol": "BTC/USD",
            "horizon_minutes": 60
        }
    ]
    results = analyzer.run_diagnostics(rows)
    assert results["conclusion"] == CONCLUSION_DATA_QUALITY


def test_diagnostics_promising_signal(temp_db):
    analyzer = ProspectiveAnalyzer(db_path=temp_db)
    
    # 25 samples for model_a (perfect accuracy) and 25 for baseline (0.5 accuracy)
    rows = []
    for i in range(25):
        rows.append({
            "prediction_id": f"p{i}",
            "prediction_value": 0.8,
            "confidence": 0.3,
            "reason_json": json_dumps({"prospective_shadow_generated": True, "retrospective_generated": False, "no_live_trading_influence": True, "uses_only_t0_or_prior_data": True}),
            "outcome_status": "labeled",
            "future_return_pct": 0.05,
            "model_name": "model_a",
            "symbol": "BTC/USD",
            "horizon_minutes": 60
        })
        rows.append({
            "prediction_id": f"b{i}",
            "prediction_value": 0.5,
            "confidence": 0.0,
            "reason_json": json_dumps({"prospective_shadow_generated": True, "retrospective_generated": False, "no_live_trading_influence": True, "uses_only_t0_or_prior_data": True}),
            "outcome_status": "labeled",
            "future_return_pct": 0.05 if i % 2 == 0 else -0.05,
            "model_name": PROSPECTIVE_RANDOM_BASELINE,
            "symbol": "BTC/USD",
            "horizon_minutes": 60
        })

    results = analyzer.run_diagnostics(rows)
    assert results["conclusion"] == CONCLUSION_PROMISING
    assert results["labeled_count"] == 50
    assert results["avg_acc_delta"] > 0.4
