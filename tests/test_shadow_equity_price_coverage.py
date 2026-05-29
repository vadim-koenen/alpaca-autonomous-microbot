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
from shadow_learner.price_history import count_price_points, fetch_price_observations, read_price_file, record_price_points
from shadow_learner.prediction_journal import record_prediction
from shadow_learner.schema import connect

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data" / "manual_prices" / "equity_sample_prices.jsonl"


def _snapshot(**overrides):
    data = dict(
        broker="alpaca",
        asset_class="equity",
        symbol="AAPL",
        strategy="scan_all",
        price=75.0,
        bid=74.9,
        ask=75.1,
        spread_pct=0.1,
        quote_age_seconds=1.0,
        bars_available=20,
        market_data_status="valid",
        created_at_utc="2020-01-01T14:30:00Z",
        features={"momentum_pct": 0.2},
    )
    data.update(overrides)
    return FeatureSnapshot(**data)


def _seed_equity_snapshots(db):
    for symbol in ("SPY", "QQQ", "AAPL", "MSFT", "NVDA"):
        record_feature_snapshot(_snapshot(symbol=symbol), db_path=db)


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


def _outcome_count(db):
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT COUNT(*) FROM shadow_outcomes").fetchone()[0]


def test_manual_equity_price_import_works(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _seed_equity_snapshots(db)

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_import_prices.py"),
            "--input-file",
            str(FIXTURE),
            "--db",
            str(db),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "manual_equity_prices" in result.stdout
    assert "Inserted price points: 10" in result.stdout
    assert count_price_points(db) == 10


def test_manual_equity_price_import_is_idempotent(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _seed_equity_snapshots(db)
    points, errors = read_price_file(FIXTURE)
    assert errors == []

    first = record_price_points(points, db_path=db)
    second = record_price_points(points, db_path=db)

    assert first["inserted"] == 10
    assert second["existing"] == 10
    assert count_price_points(db) == 10


def test_manual_equity_import_dry_run_writes_nothing(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _seed_equity_snapshots(db)
    before = count_price_points(db)

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_import_prices.py"),
            "--input-file",
            str(FIXTURE),
            "--dry-run",
            "--db",
            str(db),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "Mode: dry-run" in result.stdout
    assert count_price_points(db) == before


def test_import_skips_non_shadow_symbols_when_shadow_db_exists(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    record_feature_snapshot(_snapshot(symbol="SPY"), db_path=db)
    price_file = tmp_path / "prices.jsonl"
    price_file.write_text(
        json.dumps(
            {
                "source": "manual_equity_prices",
                "symbol": "SPY",
                "asset_class": "equity",
                "timestamp_utc": "2020-01-01T14:30:00Z",
                "close": 320.0,
            }
        )
        + "\n"
        + json.dumps(
            {
                "source": "manual_equity_prices",
                "symbol": "FAKE",
                "asset_class": "equity",
                "timestamp_utc": "2020-01-01T14:30:00Z",
                "close": 1.0,
            }
        )
        + "\n"
    )

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_import_prices.py"),
            "--input-file",
            str(price_file),
            "--db",
            str(db),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "Skipped non-shadow symbols: 1" in result.stdout
    assert count_price_points(db) == 1


def test_relabel_after_added_equity_prices_does_not_duplicate_outcomes(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    pred_id = _direction_prediction(db, symbol="AAPL")
    write_outcome(
        prediction_id=pred_id,
        horizon_minutes=15,
        outcome_status="insufficient_price_history",
        outcome_json={"reason": "missing_t0_price"},
        db_path=db,
    )
    points, _errors = read_price_file(FIXTURE)
    record_price_points(points, db_path=db)
    observations = fetch_price_observations(db_path=db, since_utc="2020-01-01T00:00:00Z")

    summary = label_outcomes(
        db_path=db,
        since_utc="2020-01-01T00:00:00Z",
        broker="all",
        observations=observations,
        dry_run=False,
    )

    assert summary["status_counts"]["labeled"] == 1
    assert _outcome_count(db) == 1
    with connect(db) as conn:
        row = conn.execute("SELECT outcome_status, outcome_json FROM shadow_outcomes WHERE prediction_id = ?", (pred_id,)).fetchone()
    payload = json.loads(row["outcome_json"])
    assert row["outcome_status"] == "labeled"
    assert payload["previous_status"] == "insufficient_price_history"
    assert payload["price_source_used"] == ["price_history:manual_equity_prices"]


def test_equity_import_redacts_secret_like_strings_and_preserves_context(tmp_path):
    price_file = tmp_path / "prices.jsonl"
    price_file.write_text(
        json.dumps(
            {
                "source": "manual_equity_prices",
                "symbol": "SPY",
                "timestamp_utc": "bad",
                "close": "APCA1234567890ABCDE",
            }
        )
        + "\n"
    )

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_import_prices.py"),
            "--input-file",
            str(price_file),
            "--dry-run",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "APCA1234567890ABCDE" not in result.stdout
    assert "Invalid rows: 1" in result.stdout


def test_equity_import_does_not_modify_state_files(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _seed_equity_snapshots(db)
    state_dir = tmp_path / "state" / "alpaca"
    state_dir.mkdir(parents=True)
    state_file = state_dir / "open_positions.json"
    state_file.write_text(json.dumps({"positions": {}}))
    before = state_file.read_text()

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_import_prices.py"),
            "--input-file",
            str(FIXTURE),
            "--db",
            str(db),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert state_file.read_text() == before
