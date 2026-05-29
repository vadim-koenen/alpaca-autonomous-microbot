import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shadow_learner.feature_snapshot import FeatureSnapshot, record_feature_snapshot
from shadow_learner.price_history import PricePoint, record_price_points
from shadow_learner.retrospective_predictions import (
    MODEL_MEAN_REVERSION,
    MODEL_MOMENTUM,
    MODEL_RANDOM,
    generate_retrospective_predictions,
)
from shadow_learner.schema import connect, init_db

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


def _count_predictions(db):
    with connect(db) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM shadow_predictions").fetchone()[0])


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


def test_retrospective_generator_uses_only_t0_or_prior_price_data(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    record_feature_snapshot(_snapshot(), db_path=db)
    record_price_points(
        [
            _point("2020-01-01T00:00:00Z", 100.0),
            _point("2020-01-01T00:05:00Z", 101.0),
            _point("2020-01-01T00:20:00Z", 999.0),
        ],
        db_path=db,
    )

    summary = generate_retrospective_predictions(db_path=db, since="2020-01-01")

    assert summary["inserted"] == 12
    rows = _prediction_rows(db)
    assert len(rows) == 12
    by_model = {row["model_name"]: row for row in rows if row["horizon_minutes"] == 15}
    assert by_model[MODEL_MOMENTUM]["prediction_value"] > 0.5
    assert by_model[MODEL_MEAN_REVERSION]["prediction_value"] < 0.5
    assert by_model[MODEL_RANDOM]["prediction_value"] == 0.5

    reason = json.loads(by_model[MODEL_MOMENTUM]["reason_json"])
    assert reason["uses_only_t0_or_prior_data"] is True
    assert reason["retrospective_generated"] is True
    assert reason["max_price_timestamp_used"] == "2020-01-01T00:05:00Z"
    assert "999" not in by_model[MODEL_MOMENTUM]["reason_json"]


def test_generator_skips_snapshot_without_t0_or_prior_price_context(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    record_feature_snapshot(
        _snapshot(price=None, features={}, market_data_status="no_bars"),
        db_path=db,
    )

    summary = generate_retrospective_predictions(db_path=db, since="2020-01-01")

    assert summary["inserted"] == 0
    assert summary["skipped_no_price_context"] == 1
    assert _count_predictions(db) == 0


def test_generator_can_use_prior_price_as_anchor_when_snapshot_price_missing(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    record_feature_snapshot(_snapshot(price=None), db_path=db)
    record_price_points([_point("2020-01-01T00:05:00Z", 101.0)], db_path=db)

    summary = generate_retrospective_predictions(db_path=db, since="2020-01-01")

    assert summary["inserted"] == 12
    rows = _prediction_rows(db)
    reason = json.loads(rows[0]["reason_json"])
    assert reason["anchor_source"] == "shadow_price_points"
    assert reason["uses_only_t0_or_prior_data"] is True


def test_retrospective_generation_is_idempotent(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    record_feature_snapshot(_snapshot(), db_path=db)
    record_price_points(
        [_point("2020-01-01T00:00:00Z", 100.0), _point("2020-01-01T00:05:00Z", 101.0)],
        db_path=db,
    )

    first = generate_retrospective_predictions(db_path=db, since="2020-01-01")
    second = generate_retrospective_predictions(db_path=db, since="2020-01-01")

    assert first["inserted"] == 12
    assert second["inserted"] == 0
    assert second["existing"] == 12
    assert _count_predictions(db) == 12


def test_dry_run_writes_nothing(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    record_feature_snapshot(_snapshot(), db_path=db)
    before = _count_predictions(db)

    summary = generate_retrospective_predictions(
        db_path=db,
        since="2020-01-01",
        dry_run=True,
    )

    assert summary["predictions_planned"] == 12
    assert summary["inserted"] == 0
    assert _count_predictions(db) == before


def test_cli_dry_run_reports_advisory_only(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    record_feature_snapshot(_snapshot(), db_path=db)

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_generate_retrospective_predictions.py"),
            "--since",
            "2020-01-01",
            "--dry-run",
            "--db",
            str(db),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "Mode: dry-run" in result.stdout
    assert "Predictions planned: 12" in result.stdout
    assert "Recommendation: advisory only; not used for live trading" in result.stdout
    assert _count_predictions(db) == 0


def test_existing_same_snapshot_symbol_horizon_model_is_not_duplicated(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    snapshot_id = record_feature_snapshot(_snapshot(), db_path=db)
    init_db(db)
    with connect(db) as conn:
        conn.execute(
            """
            INSERT INTO shadow_predictions (
                prediction_id, snapshot_id, created_at_utc, broker, asset_class,
                symbol, strategy, prediction_type, prediction_value, confidence,
                horizon_minutes, model_name, model_version, feature_version,
                would_trade, live_trade_taken, reason_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "existing",
                snapshot_id,
                "2020-01-01T00:10:00Z",
                "coinbase",
                "crypto",
                "BTC/USD",
                "coinbase_probe",
                "return_direction_15m",
                0.55,
                0.1,
                15,
                MODEL_MOMENTUM,
                "0.1.0",
                "test",
                0,
                0,
                "{}",
            ),
        )

    summary = generate_retrospective_predictions(db_path=db, since="2020-01-01")

    assert summary["existing"] == 1
    assert summary["inserted"] == 11
    assert _count_predictions(db) == 12


def test_retrospective_generator_does_not_import_execution_modules_or_outcomes():
    combined = "\n".join(
        [
            (ROOT / "scripts" / "shadow_generate_retrospective_predictions.py").read_text(),
            (ROOT / "shadow_learner" / "retrospective_predictions.py").read_text(),
        ]
    )

    assert "risk_manager" not in combined
    assert "order_manager" not in combined
    assert "broker_alpaca" not in combined
    assert "broker_coinbase" not in combined
    assert "shadow_outcomes" not in combined
