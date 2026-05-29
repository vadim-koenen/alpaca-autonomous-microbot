import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shadow_learner.feature_snapshot import FeatureSnapshot, record_feature_snapshot
from shadow_learner.outcome_labeler import (
    PriceObservation,
    classify_prediction_outcome,
    write_outcome,
)
from shadow_learner.prediction_journal import record_baseline_predictions_for_snapshot
from shadow_learner.schema import connect, init_db, json_dumps

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


def _prediction(db, **snapshot_overrides):
    snapshot_id = record_feature_snapshot(_snapshot(**snapshot_overrides), db_path=db)
    return record_baseline_predictions_for_snapshot(snapshot_id, db_path=db)[0]


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


def _outcome_count(db):
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT COUNT(*) FROM shadow_outcomes").fetchone()[0]


def test_pending_horizon_stays_pending(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    prediction_id = _prediction(db, created_at_utc="2020-01-01T00:00:00Z")
    row = _prediction_row(db, prediction_id)

    result = classify_prediction_outcome(
        row,
        [],
        now=datetime(2020, 1, 1, 0, 5, tzinfo=timezone.utc),
    )

    assert result["outcome_status"] == "pending_horizon"


def test_missing_future_data_becomes_missing_data(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    prediction_id = _prediction(db)
    row = _prediction_row(db, prediction_id)

    result = classify_prediction_outcome(
        row,
        [],
        now=datetime(2020, 1, 1, 1, 0, tzinfo=timezone.utc),
    )

    assert result["outcome_status"] == "missing_data"
    assert result["market_data_available"] is False


def test_matching_local_exit_can_create_labeled_outcome(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    prediction_id = _prediction(db)
    row = _prediction_row(db, prediction_id)
    obs = PriceObservation(
        symbol="BTC/USD",
        timestamp_utc="2020-01-01T00:10:00Z",
        price=101.0,
        source="log:coinbase.launchd.out.log",
        terminal=True,
    )

    result = classify_prediction_outcome(
        row,
        [obs],
        now=datetime(2020, 1, 1, 1, 0, tzinfo=timezone.utc),
    )

    assert result["outcome_status"] == "labeled"
    assert result["future_return_pct"] == 1.0
    assert result["hit_take_profit"] is True


def test_outcome_idempotency_prevents_duplicate_rows(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    prediction_id = _prediction(db)

    for _ in range(2):
        write_outcome(
            prediction_id=prediction_id,
            horizon_minutes=15,
            outcome_status="missing_data",
            outcome_json={"reason": "test"},
            db_path=db,
        )

    assert _outcome_count(db) == 1


def test_labeler_dry_run_writes_nothing(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _prediction(db)
    before = _outcome_count(db)

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_label_outcomes.py"),
            "--since",
            "2020-01-01",
            "--dry-run",
            "--db",
            str(db),
            "--logs-root",
            str(tmp_path / "logs"),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "Mode: dry-run" in result.stdout
    assert _outcome_count(db) == before


def test_unsupported_prediction_type_is_handled_safely(tmp_path):
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
                "pred_unsupported",
                snapshot_id,
                "2020-01-01T00:00:00Z",
                "coinbase",
                "crypto",
                "BTC/USD",
                "coinbase_probe",
                "mystery_signal",
                0.5,
                0.0,
                15,
                "test",
                "0",
                "test",
                0,
                0,
                json_dumps({}),
            ),
        )
    row = _prediction_row(db, "pred_unsupported")

    result = classify_prediction_outcome(
        row,
        [],
        now=datetime(2020, 1, 1, 1, 0, tzinfo=timezone.utc),
    )

    assert result["outcome_status"] == "unsupported_prediction_type"


def test_manual_price_file_can_label_simple_prediction(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _prediction(db)
    price_file = tmp_path / "prices.jsonl"
    price_file.write_text(
        json.dumps(
            {
                "source": "manual_test",
                "symbol": "BTC/USD",
                "timestamp_utc": "2020-01-01T00:00:00Z",
                "price": 100.0,
            }
        )
        + "\n"
        + json.dumps(
            {
                "source": "manual_test",
                "symbol": "BTC/USD",
                "timestamp_utc": "2020-01-01T00:15:00Z",
                "price": 102.0,
            }
        )
        + "\n"
    )

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_label_outcomes.py"),
            "--since",
            "2020-01-01",
            "--price-file",
            str(price_file),
            "--db",
            str(db),
            "--logs-root",
            str(tmp_path / "logs"),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "labeled:" in result.stdout
    assert _outcome_count(db) > 0


def test_bad_data_alpaca_snapshot_does_not_invent_outcome(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    prediction_id = _prediction(
        db,
        broker="alpaca",
        asset_class="equity",
        symbol="AAPL",
        strategy="scan_all",
        price=None,
        bid=150.0,
        ask=0.0,
        bars_available=0,
        market_data_status="invalid_quote",
        skip_reason="invalid_quote",
    )
    row = _prediction_row(db, prediction_id)

    result = classify_prediction_outcome(
        row,
        [PriceObservation(symbol="AAPL", timestamp_utc="2020-01-01T00:15:00Z", price=151.0)],
        now=datetime(2020, 1, 1, 1, 0, tzinfo=timezone.utc),
    )

    assert result["outcome_status"] == "insufficient_price_history"
    assert result["outcome_json"]["reason"] == "missing_t0_price"


def test_candle_timeframe_can_cover_horizon_boundary(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    prediction_id = _prediction(db, created_at_utc="2020-01-01T00:00:30Z")
    row = _prediction_row(db, prediction_id)

    result = classify_prediction_outcome(
        row,
        [
            PriceObservation(
                symbol="BTC/USD",
                timestamp_utc="2020-01-01T00:00:00Z",
                price=100.0,
                close=100.0,
                timeframe="60s",
            ),
            PriceObservation(
                symbol="BTC/USD",
                timestamp_utc="2020-01-01T00:15:00Z",
                price=102.0,
                close=102.0,
                high=103.0,
                low=99.0,
                timeframe="60s",
            ),
        ],
        now=datetime(2020, 1, 1, 1, 0, tzinfo=timezone.utc),
    )

    assert result["outcome_status"] == "labeled"


def test_manual_news_fixture_imports_successfully(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    fixture = ROOT / "data" / "manual_news" / "2026-05-28_coinbase_market_briefing.jsonl"

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_news_ingest.py"),
            "--input-file",
            str(fixture),
            "--skip-fetch",
            "--db",
            str(db),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "Inserted items: 6" in result.stdout


def test_news_report_nonzero_after_fixture_import(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    fixture = ROOT / "data" / "manual_news" / "2026-05-28_coinbase_market_briefing.jsonl"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_news_ingest.py"),
            "--input-file",
            str(fixture),
            "--skip-fetch",
            "--db",
            str(db),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    report = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_news_report.py"),
            "--since",
            "2026-05-28",
            "--db",
            str(db),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "Total news items: 6" in report.stdout
    assert "XLM: 1" in report.stdout
    assert "tokenization: 1" in report.stdout


def test_labeler_does_not_modify_open_position_state_files(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _prediction(db)
    state = tmp_path / "state" / "coinbase"
    state.mkdir(parents=True)
    state_file = state / "open_positions.json"
    state_file.write_text('{"positions":{}}')
    before = state_file.read_text()

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_label_outcomes.py"),
            "--since",
            "2020-01-01",
            "--db",
            str(db),
            "--logs-root",
            str(tmp_path / "logs"),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert state_file.read_text() == before


def test_labeler_scripts_do_not_import_execution_modules():
    combined = "\n".join(
        [
            (ROOT / "scripts" / "shadow_label_outcomes.py").read_text(),
            (ROOT / "scripts" / "shadow_import_prices.py").read_text(),
            (ROOT / "shadow_learner" / "outcome_labeler.py").read_text(),
            (ROOT / "shadow_learner" / "price_history.py").read_text(),
        ]
    )

    assert "risk_manager" not in combined
    assert "order_manager" not in combined
    assert "broker_alpaca" not in combined
    assert "broker_coinbase" not in combined


def test_labeler_redaction_protects_secret_like_strings():
    from scripts.shadow_label_outcomes import redact_for_output

    redacted = redact_for_output("account_id=123456 api_key=APCA1234567890ABCDE BTC price=75000 2026-05-28T15:00:00Z")

    assert "123456" not in redacted
    assert "APCA1234567890ABCDE" not in redacted
    assert "BTC" in redacted
    assert "75000" in redacted
    assert "2026-05-28T15:00:00Z" in redacted


def test_reports_clearly_state_advisory_only(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    learner = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_learner_report.py"),
            "--since",
            "2026-05-28",
            "--db",
            str(db),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    news = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_news_report.py"),
            "--since",
            "2026-05-28",
            "--db",
            str(db),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "Recommendation: advisory only; not used for live trading" in learner.stdout
    assert "Recommendation: advisory only; not used for live trading" in news.stdout
