import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shadow_learner.feature_snapshot import FeatureSnapshot, record_feature_snapshot
from shadow_learner.price_history import PricePoint, record_price_points
from shadow_learner.prospective_predictions import (
    MODEL_MEAN_REVERSION,
    MODEL_MOMENTUM,
    MODEL_RANDOM,
    generate_prospective_predictions_for_snapshot,
)
from shadow_learner.schema import connect

ROOT = Path(__file__).resolve().parents[1]


def _snapshot(**overrides):
    data = dict(
        broker="coinbase",
        asset_class="crypto",
        symbol="BTC/USD",
        strategy="coinbase_probe",
        price=102.0,
        bid=101.9,
        ask=102.1,
        spread_pct=0.1,
        quote_age_seconds=1.0,
        bars_available=20,
        market_data_status="valid",
        created_at_utc="2020-01-01T00:10:00Z",
        features={"momentum_pct": 0.25},
    )
    data.update(overrides)
    return FeatureSnapshot(**data)


def _point(timestamp, close, *, symbol="BTC/USD"):
    return PricePoint(
        source="manual_test",
        symbol=symbol,
        asset_class="crypto" if "/" in symbol else "equity",
        timestamp_utc=timestamp,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1.0,
        timeframe="1m",
    )


def _prediction_rows(db):
    with connect(db) as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM shadow_predictions
                ORDER BY model_name, horizon_minutes
                """
            ).fetchall()
        ]


def _count_prospective(db):
    with sqlite3.connect(db) as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM shadow_predictions WHERE model_name LIKE 'prospective_%'"
            ).fetchone()[0]
        )


def _make_roots(tmp_path, *, coinbase_lines=None, alpaca_lines=None):
    logs = tmp_path / "logs"
    runtime = tmp_path / "runtime"
    state = tmp_path / "state"
    logs.mkdir()
    runtime.mkdir()
    (state / "alpaca").mkdir(parents=True)
    (state / "coinbase").mkdir(parents=True)
    (logs / "coinbase.launchd.out.log").write_text(
        "\n".join(coinbase_lines or []) + ("\n" if coinbase_lines else "")
    )
    (logs / "alpaca.launchd.out.log").write_text(
        "\n".join(alpaca_lines or []) + ("\n" if alpaca_lines else "")
    )
    (runtime / "alpaca_heartbeat.json").write_text("{}")
    (runtime / "coinbase_heartbeat.json").write_text("{}")
    (state / "alpaca" / "open_positions.json").write_text(
        '{"saved_at":"2020-01-01T06:00:00Z","state_namespace":"alpaca","positions":{}}'
    )
    (state / "coinbase" / "open_positions.json").write_text(
        '{"saved_at":"2020-01-01T06:00:00Z","state_namespace":"coinbase","positions":{}}'
    )
    return logs, runtime, state


def _run_ingest(db, logs, runtime, state, *, broker="coinbase", dry_run=False):
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "shadow_ingest_logs.py"),
        "--since",
        "2020-01-01",
        "--broker",
        broker,
        "--db",
        str(db),
        "--logs-root",
        str(logs),
        "--runtime-root",
        str(runtime),
        "--state-root",
        str(state),
    ]
    if dry_run:
        cmd.append("--dry-run")
    return subprocess.run(cmd, check=True, text=True, capture_output=True)


def test_prospective_generator_uses_only_t0_or_prior_price_data(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    snapshot_id = record_feature_snapshot(_snapshot(), db_path=db)
    record_price_points(
        [
            _point("2020-01-01T00:00:00Z", 100.0),
            _point("2020-01-01T00:05:00Z", 101.0),
            _point("2020-01-01T00:20:00Z", 999.0),
        ],
        db_path=db,
    )

    summary = generate_prospective_predictions_for_snapshot(snapshot_id, db_path=db)

    assert summary["inserted"] == 12
    rows = _prediction_rows(db)
    by_model = {row["model_name"]: row for row in rows if row["horizon_minutes"] == 15}
    assert by_model[MODEL_MOMENTUM]["prediction_value"] > 0.5
    assert by_model[MODEL_MEAN_REVERSION]["prediction_value"] < 0.5
    assert by_model[MODEL_RANDOM]["prediction_value"] == 0.5

    reason = json.loads(by_model[MODEL_MOMENTUM]["reason_json"])
    assert reason["prospective_shadow_generated"] is True
    assert reason["retrospective_generated"] is False
    assert reason["uses_only_t0_or_prior_data"] is True
    assert reason["no_live_trading_influence"] is True
    assert reason["max_price_timestamp_used"] == "2020-01-01T00:05:00Z"
    assert "999" not in by_model[MODEL_MOMENTUM]["reason_json"]


def test_prospective_generator_skips_without_t0_or_prior_price_context(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    snapshot_id = record_feature_snapshot(
        _snapshot(price=None, features={}, market_data_status="no_bars"),
        db_path=db,
    )

    summary = generate_prospective_predictions_for_snapshot(snapshot_id, db_path=db)

    assert summary["inserted"] == 0
    assert summary["skipped_no_price_context"] == 1
    assert _count_prospective(db) == 0


def test_prospective_generation_is_idempotent(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    snapshot_id = record_feature_snapshot(_snapshot(), db_path=db)
    record_price_points(
        [_point("2020-01-01T00:00:00Z", 100.0), _point("2020-01-01T00:05:00Z", 101.0)],
        db_path=db,
    )

    first = generate_prospective_predictions_for_snapshot(snapshot_id, db_path=db)
    second = generate_prospective_predictions_for_snapshot(snapshot_id, db_path=db)

    assert first["inserted"] == 12
    assert second["inserted"] == 0
    assert second["existing"] == 12
    assert _count_prospective(db) == 12


def test_prospective_dry_run_writes_nothing(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    snapshot_id = record_feature_snapshot(_snapshot(), db_path=db)

    summary = generate_prospective_predictions_for_snapshot(
        snapshot_id,
        db_path=db,
        dry_run=True,
    )

    assert summary["predictions_planned"] == 12
    assert summary["inserted"] == 0
    assert _count_prospective(db) == 0


def test_log_ingest_creates_prospective_predictions_for_new_price_snapshot(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    record_price_points(
        [
            _point("2020-01-01T06:00:00Z", 100.0),
            _point("2020-01-01T06:05:00Z", 101.0),
        ],
        db_path=db,
    )
    logs, runtime, state = _make_roots(
        tmp_path,
        coinbase_lines=[
            "2020-01-01 00:10:00 | INFO     | strategy.crypto | SIGNAL coinbase_probe BTC/USD | regime=dead_chop notional=$0.50 limit=102.00 conf=0.55 spread=0.000% rsi=36.7"
        ],
    )

    first = _run_ingest(db, logs, runtime, state)
    first_count = _count_prospective(db)
    second = _run_ingest(db, logs, runtime, state)

    assert "Created prospective shadow predictions: 12" in first.stdout
    assert first_count == 12
    assert _count_prospective(db) == first_count
    assert "Created prospective shadow predictions: 0" in second.stdout


def test_log_ingest_dry_run_does_not_write_prospective_predictions(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    logs, runtime, state = _make_roots(
        tmp_path,
        coinbase_lines=[
            "2020-01-01 00:10:00 | INFO     | strategy.crypto | SIGNAL coinbase_probe BTC/USD | regime=dead_chop notional=$0.50 limit=102.00 conf=0.55 spread=0.000% rsi=36.7"
        ],
    )

    result = _run_ingest(db, logs, runtime, state, dry_run=True)

    assert "Mode: dry-run" in result.stdout
    assert "Would create prospective shadow predictions: 12" in result.stdout
    assert not db.exists()


def test_bad_data_alpaca_snapshot_does_not_create_prospective_directional_predictions(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    logs, runtime, state = _make_roots(
        tmp_path,
        alpaca_lines=[
            "2020-01-01 00:10:00 | INFO     | strategy.equities | SCAN AAPL equity | no bars returned -- skipped"
        ],
    )

    result = _run_ingest(db, logs, runtime, state, broker="alpaca")

    assert "Created prospective shadow predictions: 0" in result.stdout
    assert "no_usable_t0_or_prior_price_context" in result.stdout
    assert _count_prospective(db) == 0


def test_prospective_module_and_ingest_do_not_import_execution_modules():
    combined = "\n".join(
        [
            (ROOT / "scripts" / "shadow_ingest_logs.py").read_text(),
            (ROOT / "shadow_learner" / "prospective_predictions.py").read_text(),
        ]
    )

    assert "risk_manager" not in combined
    assert "order_manager" not in combined
    assert "broker_alpaca" not in combined
    assert "broker_coinbase" not in combined
