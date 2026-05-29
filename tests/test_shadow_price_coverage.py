import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.shadow_label_outcomes import label_outcomes
from shadow_learner.feature_snapshot import FeatureSnapshot, record_feature_snapshot
from shadow_learner.outcome_labeler import PriceObservation, write_outcome
from shadow_learner.price_coverage import build_price_coverage
from shadow_learner.prediction_journal import record_prediction
from shadow_learner.schema import connect

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


def _direction_prediction(db, **snapshot_overrides):
    snapshot_id = record_feature_snapshot(_snapshot(**snapshot_overrides), db_path=db)
    return record_prediction(
        snapshot_id,
        {
            "prediction_type": "return_direction_15m",
            "prediction_value": 0.55,
            "confidence": 0.1,
            "horizon_minutes": 15,
            "model_name": "test_baseline",
            "model_version": "0",
            "feature_version": "test",
            "reason": {},
        },
        db_path=db,
    )


def _outcome_rows(db):
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT COUNT(*) FROM shadow_outcomes").fetchone()[0]


def test_coverage_planner_calculates_needed_windows_from_predictions(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _direction_prediction(db, created_at_utc="2020-01-01T00:00:00Z")
    _direction_prediction(db, symbol="ETH/USD", created_at_utc="2020-01-01T00:30:00Z")

    report = build_price_coverage(db_path=db, since="2020-01-01")
    windows = {row["symbol"]: row for row in report["needed_windows"]}

    assert windows["BTC/USD"]["earliest_needed_utc"] == "2020-01-01T00:00:00Z"
    assert windows["BTC/USD"]["latest_needed_utc"] == "2020-01-01T00:15:00Z"
    assert windows["ETH/USD"]["earliest_needed_utc"] == "2020-01-01T00:30:00Z"
    assert windows["ETH/USD"]["latest_needed_utc"] == "2020-01-01T00:45:00Z"


def test_coverage_planner_reports_insufficient_by_symbol_horizon(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    prediction_id = _direction_prediction(db)
    write_outcome(
        prediction_id=prediction_id,
        horizon_minutes=15,
        outcome_status="insufficient_price_history",
        outcome_json={"reason": "missing_t0_price"},
        db_path=db,
    )

    report = build_price_coverage(db_path=db, since="2020-01-01")

    assert report["label_counts"]["insufficient_price_history"] == 1
    assert {
        "symbol": "BTC/USD",
        "horizon_minutes": 15,
        "outcome_status": "insufficient_price_history",
        "count": 1,
    } in report["outcome_by_symbol_horizon"]


def test_coverage_planner_evaluation_gate_remains_blocked(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    prediction_id = _direction_prediction(db)
    write_outcome(
        prediction_id=prediction_id,
        horizon_minutes=15,
        outcome_status="labeled",
        future_return_pct=1.0,
        market_data_available=True,
        outcome_json={},
        db_path=db,
    )

    report = build_price_coverage(db_path=db, since="2020-01-01")

    assert report["evaluation_gate"]["status"] == "BLOCKED"
    assert any("directional labeled outcomes 1/100" in reason for reason in report["evaluation_gate"]["reasons"])


def test_coverage_cli_reports_advisory_warning_and_gate_status(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _direction_prediction(db)

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_price_coverage.py"),
            "--since",
            "2020-01-01",
            "--db",
            str(db),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "Evaluation gate: BLOCKED" in result.stdout
    assert "Recommended backfill commands:" in result.stdout
    assert "Recommendation: advisory only; not used for live trading" in result.stdout


def test_previously_insufficient_outcome_relabels_after_price_data_without_duplicate(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    prediction_id = _direction_prediction(db)
    write_outcome(
        prediction_id=prediction_id,
        horizon_minutes=15,
        outcome_status="insufficient_price_history",
        outcome_json={"reason": "missing_t0_price"},
        db_path=db,
    )
    before_rows = _outcome_rows(db)

    summary = label_outcomes(
        db_path=db,
        since_utc="2020-01-01T00:00:00Z",
        broker="all",
        observations=[
            PriceObservation(
                symbol="BTC/USD",
                timestamp_utc="2020-01-01T00:00:00Z",
                price=100.0,
                source="price_history:test",
                close=100.0,
                high=100.0,
                low=100.0,
            ),
            PriceObservation(
                symbol="BTC/USD",
                timestamp_utc="2020-01-01T00:15:00Z",
                price=102.0,
                source="price_history:test",
                close=102.0,
                high=103.0,
                low=99.0,
            ),
        ],
        dry_run=False,
    )

    assert summary["status_counts"]["labeled"] == 1
    assert _outcome_rows(db) == before_rows
    with connect(db) as conn:
        row = conn.execute(
            "SELECT outcome_status, outcome_json FROM shadow_outcomes WHERE prediction_id = ?",
            (prediction_id,),
        ).fetchone()
    payload = json.loads(row["outcome_json"])
    assert row["outcome_status"] == "labeled"
    assert payload["previous_status"] == "insufficient_price_history"
    assert payload["price_source_used"] == ["price_history:test"]


def test_coverage_script_does_not_modify_state_files(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _direction_prediction(db)
    state_dir = tmp_path / "state" / "coinbase"
    state_dir.mkdir(parents=True)
    state_file = state_dir / "open_positions.json"
    state_file.write_text('{"positions":{}}')
    before = state_file.read_text()

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_price_coverage.py"),
            "--since",
            "2020-01-01",
            "--db",
            str(db),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert state_file.read_text() == before


def test_coverage_and_backfill_scripts_do_not_import_execution_modules():
    combined = "\n".join(
        [
            (ROOT / "scripts" / "shadow_price_coverage.py").read_text(),
            (ROOT / "shadow_learner" / "price_coverage.py").read_text(),
            (ROOT / "scripts" / "shadow_backfill_prices.py").read_text(),
            (ROOT / "shadow_learner" / "public_price_backfill.py").read_text(),
        ]
    )

    assert "risk_manager" not in combined
    assert "order_manager" not in combined
    assert "broker_alpaca" not in combined
    assert "broker_coinbase" not in combined
