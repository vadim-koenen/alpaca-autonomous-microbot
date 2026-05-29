import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import shadow_learner.directional_coverage as directional_coverage
from shadow_learner.directional_coverage import (
    GATE_OPEN,
    GATE_BLOCKED_NO_DIRECTIONAL,
    build_directional_coverage,
)
from shadow_learner.feature_snapshot import FeatureSnapshot, record_feature_snapshot
from shadow_learner.outcome_labeler import write_outcome
from shadow_learner.prediction_journal import record_prediction

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


def _record_prediction(db, *, prediction_type="return_direction_15m", **snapshot_overrides):
    snapshot_id = record_feature_snapshot(_snapshot(**snapshot_overrides), db_path=db)
    return record_prediction(
        snapshot_id,
        {
            "prediction_type": prediction_type,
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


def test_directional_coverage_counts_prediction_types(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    pred_id = _record_prediction(db)
    _record_prediction(db, prediction_type="market_data_valid_probability")
    write_outcome(
        prediction_id=pred_id,
        horizon_minutes=15,
        outcome_status="labeled",
        future_return_pct=1.0,
        market_data_available=True,
        outcome_json={},
        db_path=db,
    )

    report = build_directional_coverage(db_path=db, since="2020-01-01")
    type_counts = {row["prediction_type"]: row["count"] for row in report["predictions_by_type"]}

    assert type_counts["return_direction_15m"] == 1
    assert type_counts["market_data_valid_probability"] == 1
    assert report["directional_counts"]["predictions"] == 1
    assert report["directional_counts"]["labeled"] == 1


def test_directional_coverage_identifies_symbols_with_no_directional_predictions(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _record_prediction(db, prediction_type="market_data_valid_probability", broker="alpaca", asset_class="equity", symbol="AAPL")

    report = build_directional_coverage(db_path=db, since="2020-01-01")

    assert {
        "broker": "alpaca",
        "symbol": "AAPL",
        "snapshot_count": 1,
    } in report["symbols_with_snapshots_no_directional"]
    assert report["evaluation_gate"]["status"] == GATE_BLOCKED_NO_DIRECTIONAL


def test_directional_coverage_identifies_missing_price_history(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    pred_id = _record_prediction(db)
    write_outcome(
        prediction_id=pred_id,
        horizon_minutes=15,
        outcome_status="insufficient_price_history",
        outcome_json={"reason": "missing_t0_price"},
        db_path=db,
    )

    report = build_directional_coverage(db_path=db, since="2020-01-01")

    assert report["directional_counts"]["insufficient_price_history"] == 1
    assert report["symbols_with_directional_insufficient_price_history"][0]["symbol"] == "BTC/USD"


def test_directional_gate_opens_when_thresholds_met_and_bias_is_reported(tmp_path, monkeypatch):
    db = tmp_path / "shadow.sqlite3"
    monkeypatch.setattr(directional_coverage, "MIN_DIRECTIONAL_LABELS_FOR_EVALUATION", 2)
    monkeypatch.setattr(directional_coverage, "MIN_SYMBOL_HORIZON_LABELS_FOR_EVALUATION", 2)
    first = _record_prediction(db)
    second = _record_prediction(db)
    missing = _record_prediction(db, symbol="ETH/USD")
    for pred_id in (first, second):
        write_outcome(
            prediction_id=pred_id,
            horizon_minutes=15,
            outcome_status="labeled",
            future_return_pct=1.0,
            market_data_available=True,
            outcome_json={},
            db_path=db,
        )
    write_outcome(
        prediction_id=missing,
        horizon_minutes=15,
        outcome_status="missing_data",
        outcome_json={"reason": "future_prices_do_not_reach_horizon"},
        db_path=db,
    )

    report = build_directional_coverage(db_path=db, since="2020-01-01")

    assert report["evaluation_gate"]["status"] == GATE_OPEN
    assert report["directional_counts"]["missing_data"] == 1
    assert any("directional price coverage gaps" in reason for reason in report["evaluation_gate"]["reasons"])


def test_directional_coverage_cli_reports_gate_status(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _record_prediction(db, prediction_type="market_data_valid_probability", broker="alpaca", asset_class="equity", symbol="AAPL")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_directional_coverage.py"),
            "--since",
            "2020-01-01",
            "--db",
            str(db),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "Evaluation gate status: EVALUATION_GATE_BLOCKED_NO_DIRECTIONAL_PREDICTIONS" in result.stdout
    assert "Recommendation: advisory only; not used for live trading" in result.stdout


def test_directional_coverage_script_does_not_modify_state_files(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _record_prediction(db)
    state_dir = tmp_path / "state" / "alpaca"
    state_dir.mkdir(parents=True)
    state_file = state_dir / "open_positions.json"
    state_file.write_text(json.dumps({"positions": {}}))
    before = state_file.read_text()

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_directional_coverage.py"),
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


def test_directional_coverage_does_not_import_execution_modules():
    combined = "\n".join(
        [
            (ROOT / "scripts" / "shadow_directional_coverage.py").read_text(),
            (ROOT / "shadow_learner" / "directional_coverage.py").read_text(),
        ]
    )

    assert "risk_manager" not in combined
    assert "order_manager" not in combined
    assert "broker_alpaca" not in combined
    assert "broker_coinbase" not in combined
