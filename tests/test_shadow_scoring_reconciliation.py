import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shadow_learner.scoring_reconciliation import (
    ScoringReconciler,
    RECONCILED_NO_EDGE,
    RECONCILED_INSUFFICIENT_SAMPLE,
    RECONCILED_WEAK_SIGNAL_TRACK_ONLY,
    RECONCILED_READY_FOR_HUMAN_REVIEW_ONLY,
)
from shadow_learner.feature_snapshot import FeatureSnapshot, record_feature_snapshot
from shadow_learner.outcome_labeler import write_outcome
from shadow_learner.prediction_journal import record_prediction
from shadow_learner.schema import init_db

ROOT = Path(__file__).resolve().parents[1]

def _snapshot(**overrides):
    data = dict(
        broker="coinbase",
        asset_class="crypto",
        symbol="BTC/USD",
        strategy="coinbase_probe",
        price=100.0,
        bid=99.9,
        ask=100.1,
        spread_pct=0.1,
        quote_age_seconds=1.0,
        bars_available=20,
        market_data_status="valid",
        created_at_utc="2020-01-01T00:00:00Z",
        features={"momentum_pct": 0.2},
    )
    data.update(overrides)
    return FeatureSnapshot(**data)

def _prediction(
    db,
    *,
    model_name="prospective_mean_reversion_v0",
    model_version="0.1.0",
    probability=0.6,
    future_return_pct=1.0,
    status="labeled",
    retrospective=False,
    prospective=True,
    symbol="BTC/USD",
    broker="coinbase",
    horizon=15,
):
    snapshot_id = record_feature_snapshot(
        _snapshot(symbol=symbol, broker=broker, created_at_utc="2020-01-01T00:00:00Z"),
        db_path=db,
    )
    pred_id = record_prediction(
        snapshot_id,
        {
            "prediction_type": f"return_direction_{horizon}m",
            "prediction_value": probability,
            "confidence": abs(probability - 0.5) * 2,
            "horizon_minutes": horizon,
            "model_name": model_name,
            "model_version": model_version,
            "feature_version": "test",
            "reason": {
                "retrospective_generated": retrospective,
                "prospective_shadow_generated": prospective,
                "no_live_trading_influence": True,
                "uses_only_t0_or_prior_data": True,
            },
        },
        db_path=db,
    )
    write_outcome(
        prediction_id=pred_id,
        horizon_minutes=horizon,
        outcome_status=status,
        future_return_pct=future_return_pct if status == "labeled" else None,
        max_favorable_excursion_pct=2.0 if status == "labeled" else None,
        max_adverse_excursion_pct=-0.5 if status == "labeled" else None,
        market_data_available=status == "labeled",
        outcome_json={},
        db_path=db,
    )
    return pred_id

def test_reconciler_returns_insufficient_sample_for_empty_db(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    init_db(db)
    reconciler = ScoringReconciler(db_path=db)
    results = reconciler.reconcile(since="2020-01-01")
    
    assert results["conclusion"] == RECONCILED_INSUFFICIENT_SAMPLE

def test_reconciler_identifies_watchlist_bucket(tmp_path, monkeypatch):
    db = tmp_path / "shadow.sqlite3"
    init_db(db)
    
    # Mock thresholds to trigger watchlist with fewer samples
    import shadow_learner.evaluate as eval_mod
    monkeypatch.setattr(eval_mod, "MIN_DIRECTIONAL_LABELS_FOR_EVALUATION", 2)
    monkeypatch.setattr(eval_mod, "MIN_SYMBOL_HORIZON_LABELS_FOR_EVALUATION", 1)
    monkeypatch.setattr(eval_mod, "MIN_PROSPECTIVE_COLLECTION_DAYS", 0)

    # 1. Model that beats random
    _prediction(db, model_name="prospective_model_v1", probability=0.9, future_return_pct=1.0)
    _prediction(db, model_name="prospective_model_v1", probability=0.1, future_return_pct=-1.0)
    
    # 2. Random baseline
    _prediction(db, model_name="prospective_random_baseline_v0", probability=0.5, future_return_pct=1.0)
    _prediction(db, model_name="prospective_random_baseline_v0", probability=0.5, future_return_pct=-1.0)

    # Add 50 samples to meet the MIN_BUCKET_SAMPLES (actually I lowered it in logic for high deltas)
    # Let's just add enough to trigger the 20-sample rule in my logic
    for _ in range(10):
         _prediction(db, model_name="prospective_model_v1", probability=0.9, future_return_pct=1.0)
         _prediction(db, model_name="prospective_model_v1", probability=0.1, future_return_pct=-1.0)
         _prediction(db, model_name="prospective_random_baseline_v0", probability=0.5, future_return_pct=1.0)
         _prediction(db, model_name="prospective_random_baseline_v0", probability=0.5, future_return_pct=-1.0)

    reconciler = ScoringReconciler(db_path=db)
    results = reconciler.reconcile(since="2020-01-01")
    
    assert any(b["model"] == "prospective_model_v1" for b in results["watchlist"])
    assert results["conclusion"] == RECONCILED_READY_FOR_HUMAN_REVIEW_ONLY

def test_reconciler_identifies_reject_list_bucket(tmp_path, monkeypatch):
    db = tmp_path / "shadow.sqlite3"
    init_db(db)

    # 1. Model that underperforms random
    _prediction(db, model_name="prospective_bad_model_v1", probability=0.1, future_return_pct=1.0)
    _prediction(db, model_name="prospective_bad_model_v1", probability=0.9, future_return_pct=-1.0)
    
    # 2. Random baseline
    _prediction(db, model_name="prospective_random_baseline_v0", probability=0.5, future_return_pct=1.0)
    _prediction(db, model_name="prospective_random_baseline_v0", probability=0.5, future_return_pct=-1.0)

    reconciler = ScoringReconciler(db_path=db)
    results = reconciler.reconcile(since="2020-01-01")
    
    assert any(b["model"] == "prospective_bad_model_v1" for b in results["reject_list"])

def test_reconciliation_cli_smoke_test(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    init_db(db)
    _prediction(db)

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_scoring_reconciliation.py"),
            "--since",
            "2020-01-01",
            "--db",
            str(db),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "Shadow Scoring Reconciliation Report" in result.stdout
    assert "ADVISORY ONLY" in result.stdout
    assert "Conclusion:" in result.stdout
