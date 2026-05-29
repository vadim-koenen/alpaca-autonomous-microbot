import csv
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shadow_learner.feature_snapshot import FeatureSnapshot, record_feature_snapshot
from shadow_learner.outcome_labeler import PriceObservation, classify_prediction_outcome
from shadow_learner.price_history import (
    count_price_points,
    fetch_price_observations,
    read_price_file,
    record_price_points,
)
from shadow_learner.prediction_journal import record_baseline_predictions_for_snapshot
from shadow_learner.schema import connect, init_db

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


def _prediction_row(db, prediction_id):
    with connect(db) as conn:
        row = conn.execute(
            """
            SELECT p.*, s.price AS entry_price, s.created_at_utc AS snapshot_created_at_utc,
                   s.market_data_status AS snapshot_market_data_status,
                   s.skip_reason AS snapshot_skip_reason
            FROM shadow_predictions p
            JOIN shadow_feature_snapshots s ON s.snapshot_id = p.snapshot_id
            WHERE p.prediction_id = ?
            """,
            (prediction_id,),
        ).fetchone()
    return dict(row)


def _prediction(db, **snapshot_overrides):
    snapshot_id = record_feature_snapshot(_snapshot(**snapshot_overrides), db_path=db)
    return record_baseline_predictions_for_snapshot(snapshot_id, db_path=db)[0]


def _write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")


def _price_rows():
    return [
        {
            "source": "manual_test",
            "symbol": "BTC/USD",
            "asset_class": "crypto",
            "timestamp_utc": "2020-01-01T00:00:00Z",
            "open": 100.0,
            "high": 101.0,
            "low": 99.5,
            "close": 100.0,
            "volume": 1.0,
            "timeframe": "1m",
        },
        {
            "source": "manual_test",
            "symbol": "BTC/USD",
            "asset_class": "crypto",
            "timestamp_utc": "2020-01-01T00:15:00Z",
            "open": 100.0,
            "high": 103.0,
            "low": 98.0,
            "close": 102.0,
            "volume": 1.0,
            "timeframe": "1m",
        },
    ]


def test_price_table_schema_creation(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    init_db(db)

    with sqlite3.connect(db) as conn:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }

    assert "shadow_price_points" in tables


def test_manual_jsonl_price_import(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    price_file = tmp_path / "prices.jsonl"
    _write_jsonl(price_file, _price_rows())

    points, errors = read_price_file(price_file)
    summary = record_price_points(points, db_path=db)

    assert errors == []
    assert summary["inserted"] == 2
    assert count_price_points(db) == 2


def test_manual_csv_price_import(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    price_file = tmp_path / "prices.csv"
    with price_file.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_price_rows()[0].keys()))
        writer.writeheader()
        writer.writerows(_price_rows())

    points, errors = read_price_file(price_file)
    summary = record_price_points(points, db_path=db)

    assert errors == []
    assert summary["inserted"] == 2
    assert count_price_points(db) == 2


def test_idempotent_price_import(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    price_file = tmp_path / "prices.jsonl"
    _write_jsonl(price_file, _price_rows())
    points, _errors = read_price_file(price_file)

    first = record_price_points(points, db_path=db)
    second = record_price_points(points, db_path=db)

    assert first["inserted"] == 2
    assert second["existing"] == 2
    assert count_price_points(db) == 2


def test_import_dry_run_writes_nothing(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    price_file = tmp_path / "prices.jsonl"
    _write_jsonl(price_file, _price_rows())

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_import_prices.py"),
            "--input-file",
            str(price_file),
            "--dry-run",
            "--db",
            str(db),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "Mode: dry-run" in result.stdout
    assert not db.exists()


def test_invalid_rows_handled_safely(tmp_path):
    price_file = tmp_path / "prices.jsonl"
    _write_jsonl(
        price_file,
        [
            {"source": "manual", "symbol": "BTC/USD", "timestamp_utc": "2020-01-01T00:00:00Z", "close": 100.0},
            {"source": "manual", "symbol": "BTC/USD", "timestamp_utc": "bad-time", "close": 100.0},
            {"source": "manual", "timestamp_utc": "2020-01-01T00:00:00Z", "close": 100.0},
        ],
    )

    points, errors = read_price_file(price_file)

    assert len(points) == 1
    assert len(errors) == 2


def test_prediction_gets_labeled_when_price_history_covers_window(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    prediction_id = _prediction(db)
    points, _errors = read_price_file(_write_temp_price_file(tmp_path, _price_rows()))
    record_price_points(points, db_path=db)
    observations = fetch_price_observations(db_path=db, since_utc="2020-01-01T00:00:00Z")

    result = classify_prediction_outcome(
        _prediction_row(db, prediction_id),
        observations,
        now=datetime(2020, 1, 1, 1, 0, tzinfo=timezone.utc),
    )

    assert result["outcome_status"] == "labeled"
    assert result["future_return_pct"] == 2.0


def test_insufficient_price_history_when_t0_missing(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    prediction_id = _prediction(db)
    obs = [PriceObservation(symbol="BTC/USD", timestamp_utc="2020-01-01T00:15:00Z", price=102.0)]

    result = classify_prediction_outcome(
        _prediction_row(db, prediction_id),
        obs,
        now=datetime(2020, 1, 1, 1, 0, tzinfo=timezone.utc),
    )

    assert result["outcome_status"] == "insufficient_price_history"


def test_missing_data_when_future_horizon_missing(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    prediction_id = _prediction(db)
    obs = [
        PriceObservation(symbol="BTC/USD", timestamp_utc="2020-01-01T00:00:00Z", price=100.0),
        PriceObservation(symbol="BTC/USD", timestamp_utc="2020-01-01T00:05:00Z", price=101.0),
    ]

    result = classify_prediction_outcome(
        _prediction_row(db, prediction_id),
        obs,
        now=datetime(2020, 1, 1, 1, 0, tzinfo=timezone.utc),
    )

    assert result["outcome_status"] == "missing_data"
    assert result["outcome_json"]["reason"] == "future_prices_do_not_reach_horizon"


def test_pending_horizon_remains_pending(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    prediction_id = _prediction(db)
    obs = [PriceObservation(symbol="BTC/USD", timestamp_utc="2020-01-01T00:00:00Z", price=100.0)]

    result = classify_prediction_outcome(
        _prediction_row(db, prediction_id),
        obs,
        now=datetime(2020, 1, 1, 0, 5, tzinfo=timezone.utc),
    )

    assert result["outcome_status"] == "pending_horizon"


def test_mfe_mae_calculation(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    prediction_id = _prediction(db)
    obs = [
        PriceObservation(symbol="BTC/USD", timestamp_utc="2020-01-01T00:00:00Z", price=100.0, high=100.5, low=99.5, close=100.0),
        PriceObservation(symbol="BTC/USD", timestamp_utc="2020-01-01T00:15:00Z", price=101.0, high=104.0, low=97.0, close=101.0),
    ]

    result = classify_prediction_outcome(
        _prediction_row(db, prediction_id),
        obs,
        now=datetime(2020, 1, 1, 1, 0, tzinfo=timezone.utc),
    )

    assert result["max_favorable_excursion_pct"] == 4.0
    assert result["max_adverse_excursion_pct"] == -3.0


def test_price_import_scripts_do_not_import_execution_modules():
    combined = "\n".join(
        [
            (ROOT / "scripts" / "shadow_import_prices.py").read_text(),
            (ROOT / "shadow_learner" / "price_history.py").read_text(),
        ]
    )

    assert "risk_manager" not in combined
    assert "order_manager" not in combined
    assert "broker_alpaca" not in combined
    assert "broker_coinbase" not in combined


def test_price_import_does_not_modify_state_files(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    state_dir = tmp_path / "state" / "coinbase"
    state_dir.mkdir(parents=True)
    state_file = state_dir / "open_positions.json"
    state_file.write_text('{"positions":{}}')
    before = state_file.read_text()
    price_file = tmp_path / "prices.jsonl"
    _write_jsonl(price_file, _price_rows())

    subprocess.run(
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

    assert state_file.read_text() == before


def test_price_import_redacts_secret_like_strings(tmp_path):
    price_file = tmp_path / "prices.jsonl"
    _write_jsonl(
        price_file,
        [
            {"source": "manual", "symbol": "BTC/USD", "timestamp_utc": "bad", "close": "APCA1234567890ABCDE"}
        ],
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
    assert "BTC/USD" in result.stdout or "Invalid rows: 1" in result.stdout


def test_symbols_prices_timestamps_preserved(tmp_path):
    price_file = tmp_path / "prices.jsonl"
    _write_jsonl(price_file, _price_rows())

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

    assert "BTC/USD" in result.stdout
    assert "manual_test" in result.stdout
    assert "1m" in result.stdout


def test_report_includes_price_coverage_and_advisory_warning(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    points, _errors = read_price_file(_write_temp_price_file(tmp_path, _price_rows()))
    record_price_points(points, db_path=db)

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_learner_report.py"),
            "--since",
            "2020-01-01",
            "--db",
            str(db),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "Price points: 2" in result.stdout
    assert "Price symbols available:" in result.stdout
    assert "Recommendation: advisory only; not used for live trading" in result.stdout


def _write_temp_price_file(tmp_path, rows):
    price_file = tmp_path / "prices.jsonl"
    _write_jsonl(price_file, rows)
    return price_file
