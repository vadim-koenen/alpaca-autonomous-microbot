import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("LIVE_TRADING", "false")

from shadow_learner.evaluate import evaluate_predictions
from shadow_learner.feature_snapshot import FeatureSnapshot, record_feature_snapshot
from shadow_learner.outcome_labeler import label_prediction, pending_prediction_ids
from shadow_learner.prediction_journal import (
    SUPPORTED_PREDICTION_TYPES,
    record_baseline_predictions_for_snapshot,
)
from shadow_learner.schema import init_db

ROOT = Path(__file__).resolve().parents[1]


def _sample_snapshot(**overrides):
    data = dict(
        broker="coinbase",
        asset_class="crypto",
        symbol="BTC/USD",
        strategy="coinbase_probe",
        scan_id="scan-1",
        price=100.0,
        bid=99.95,
        ask=100.05,
        spread_pct=0.10,
        quote_age_seconds=5.0,
        bars_available=20,
        market_session="continuous",
        market_data_status="ok",
        skip_reason="",
        risk_block_reason="",
        features={
            "momentum_pct": 0.20,
            "trend_score": 0.7,
            "realized_volatility_pct": 0.5,
        },
    )
    data.update(overrides)
    return FeatureSnapshot(**data)


def test_schema_tables_are_created(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    init_db(db)

    with sqlite3.connect(db) as conn:
        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

    assert "shadow_feature_snapshots" in tables
    assert "shadow_predictions" in tables
    assert "shadow_outcomes" in tables
    assert "shadow_evaluation_runs" in tables


def test_feature_snapshot_can_be_inserted(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    snapshot_id = record_feature_snapshot(_sample_snapshot(), db_path=db)

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM shadow_feature_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()

    assert row["symbol"] == "BTC/USD"
    assert row["strategy"] == "coinbase_probe"
    assert row["price"] == pytest.approx(100.0)


def test_predictions_can_be_inserted(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    snapshot_id = record_feature_snapshot(_sample_snapshot(), db_path=db)
    prediction_ids = record_baseline_predictions_for_snapshot(snapshot_id, db_path=db)

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM shadow_predictions").fetchall()

    assert len(prediction_ids) == len(rows)
    assert {row["prediction_type"] for row in rows}.issubset(SUPPORTED_PREDICTION_TYPES)
    assert {row["live_trade_taken"] for row in rows} == {0}


def test_outcomes_can_be_labeled(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    snapshot_id = record_feature_snapshot(_sample_snapshot(), db_path=db)
    prediction_id = record_baseline_predictions_for_snapshot(snapshot_id, db_path=db)[0]

    status = label_prediction(prediction_id, [100.2, 100.6, 101.1], db_path=db)

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM shadow_outcomes").fetchone()

    assert status == "labeled"
    assert row["outcome_status"] == "labeled"
    assert row["future_return_pct"] == pytest.approx(1.1)
    assert row["market_data_available"] == 1


def test_missing_future_data_is_handled_safely(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    snapshot_id = record_feature_snapshot(_sample_snapshot(), db_path=db)
    prediction_id = record_baseline_predictions_for_snapshot(snapshot_id, db_path=db)[0]

    status = label_prediction(prediction_id, [], db_path=db)

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM shadow_outcomes").fetchone()

    assert status == "missing_data"
    assert row["outcome_status"] == "missing_data"
    assert row["future_return_pct"] is None
    assert row["market_data_available"] == 0


def test_no_prediction_writes_order_risk_or_position_state(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    snapshot_id = record_feature_snapshot(_sample_snapshot(), db_path=db)
    record_baseline_predictions_for_snapshot(snapshot_id, db_path=db)

    with sqlite3.connect(db) as conn:
        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

    assert "orders" not in tables
    assert "risk_decisions" not in tables
    assert "positions" not in tables


def test_shadow_predictions_cannot_change_proposal_approval(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    snapshot_id = record_feature_snapshot(
        _sample_snapshot(spread_pct=12.0, market_data_status="spread_too_wide"),
        db_path=db,
    )
    prediction_ids = record_baseline_predictions_for_snapshot(snapshot_id, db_path=db)

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        predictions = conn.execute("SELECT * FROM shadow_predictions").fetchall()

    assert prediction_ids
    assert all("allowed" not in dict(row) for row in predictions)
    assert all("approved" not in dict(row) for row in predictions)
    assert all(row["would_trade"] == 0 for row in predictions)
    assert all(row["live_trade_taken"] == 0 for row in predictions)


def test_evaluation_records_metrics(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    snapshot_id = record_feature_snapshot(_sample_snapshot(), db_path=db)
    prediction_id = record_baseline_predictions_for_snapshot(snapshot_id, db_path=db)[0]
    label_prediction(prediction_id, [101.0], db_path=db)

    metrics = evaluate_predictions(db_path=db)

    assert metrics["sample_count"] == 1
    assert metrics["accuracy"] in {0.0, 1.0}
    assert metrics["run_id"].startswith("eval_")


def test_pending_prediction_ids_respect_horizon(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    snapshot_id = record_feature_snapshot(
        _sample_snapshot(created_at_utc="2026-05-28T00:00:00Z"),
        db_path=db,
    )
    record_baseline_predictions_for_snapshot(snapshot_id, db_path=db)

    due = pending_prediction_ids(db_path=db, now=__import__("datetime").datetime(2026, 5, 28, 2, 0, tzinfo=__import__("datetime").timezone.utc))

    assert due


def test_report_runs_with_empty_db(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_learner_report.py"),
            "--db",
            str(db),
            "--since",
            "2026-05-28",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "Snapshots: 0" in result.stdout
    assert "Recommendation: advisory only; not used for live trading" in result.stdout


def test_report_runs_with_sample_data(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    snapshot_id = record_feature_snapshot(_sample_snapshot(), db_path=db)
    prediction_id = record_baseline_predictions_for_snapshot(snapshot_id, db_path=db)[0]
    label_prediction(prediction_id, [101.0], db_path=db)

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_learner_report.py"),
            "--db",
            str(db),
            "--since",
            "2026-05-28",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "BTC/USD: 1" in result.stdout
    assert "Overall direction sample_count: 1" in result.stdout


def test_no_secret_values_are_printed(tmp_path, monkeypatch):
    db = tmp_path / "shadow.sqlite3"
    monkeypatch.setenv("ALPACA_SECRET_KEY", "DO_NOT_PRINT_ME")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_learner_report.py"),
            "--db",
            str(db),
            "--since",
            "2026-05-28",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "DO_NOT_PRINT_ME" not in result.stdout
    assert "ALPACA_SECRET_KEY" not in result.stdout


def test_no_strategy_or_risk_config_changed(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    watched = [
        ROOT / "risk_manager.py",
        ROOT / "order_manager.py",
        ROOT / "main.py",
        ROOT / "config.yaml",
        ROOT / "config_coinbase_crypto.yaml",
        ROOT / "config_alpaca_stocks.yaml",
    ]
    before = {path: path.read_bytes() for path in watched}

    snapshot_id = record_feature_snapshot(_sample_snapshot(), db_path=db)
    prediction_id = record_baseline_predictions_for_snapshot(snapshot_id, db_path=db)[0]
    label_prediction(prediction_id, [101.0], db_path=db)

    after = {path: path.read_bytes() for path in watched}
    assert after == before
