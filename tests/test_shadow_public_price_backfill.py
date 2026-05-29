import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shadow_learner.feature_snapshot import FeatureSnapshot, record_feature_snapshot
from shadow_learner.outcome_labeler import classify_prediction_outcome
from shadow_learner.price_history import count_price_points, fetch_price_observations
from shadow_learner.prediction_journal import record_baseline_predictions_for_snapshot
from shadow_learner.public_price_backfill import (
    backfill_public_prices,
    backfill_public_prices_for_symbols,
    build_coinbase_candles_url,
    infer_shadow_crypto_symbols,
    normalize_coinbase_candles,
    product_id_for_symbol,
    symbol_for_product_id,
)
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


def _fake_candles(product_id, *, start, end, granularity, timeout_seconds):
    del product_id, granularity, timeout_seconds
    t0 = int(start.timestamp())
    t15 = int((start + timedelta(minutes=15)).timestamp())
    tend = int(end.timestamp())
    return [
        [t0, 99.0, 101.0, 100.0, 100.0, 1.0],
        [t15, 100.0, 103.0, 100.0, 102.0, 2.0],
        [tend, 101.0, 104.0, 102.0, 103.0, 3.0],
    ], ""


def test_public_candle_response_parsing():
    candles = [[1577836800, 99.0, 103.0, 100.0, 102.0, 12.5]]

    points, errors = normalize_coinbase_candles(candles, symbol="BTC/USD", granularity=60)

    assert errors == []
    assert len(points) == 1
    assert points[0].timestamp_utc == "2020-01-01T00:00:00Z"
    assert points[0].open == 100.0
    assert points[0].high == 103.0
    assert points[0].low == 99.0
    assert points[0].close == 102.0
    assert points[0].timeframe == "60s"


def test_btc_usd_product_mapping():
    assert product_id_for_symbol("BTC/USD") == "BTC-USD"
    assert product_id_for_symbol("ETH/USD") == "ETH-USD"
    assert product_id_for_symbol("SOL/USD") == "SOL-USD"
    assert symbol_for_product_id("BTC-USD") == "BTC/USD"


def test_public_url_uses_product_candles_without_auth_material():
    url = build_coinbase_candles_url(
        "BTC-USD",
        start=datetime(2020, 1, 1, tzinfo=timezone.utc),
        end=datetime(2020, 1, 1, 0, 15, tzinfo=timezone.utc),
        granularity=60,
    )

    assert "/products/BTC-USD/candles" in url
    assert "granularity=60" in url
    assert "key" not in url.lower()
    assert "secret" not in url.lower()
    assert "token" not in url.lower()


def test_candle_normalization_into_shadow_price_points(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _prediction(db)

    summary = backfill_public_prices(
        symbol="BTC/USD",
        since_utc="2020-01-01T00:00:00Z",
        granularity=60,
        db_path=db,
        fetcher=_fake_candles,
    )

    assert summary["inserted"] == 3
    assert count_price_points(db) == 3


def test_idempotent_backfill(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _prediction(db)

    first = backfill_public_prices(
        symbol="BTC/USD",
        since_utc="2020-01-01T00:00:00Z",
        granularity=60,
        db_path=db,
        fetcher=_fake_candles,
    )
    second = backfill_public_prices(
        symbol="BTC/USD",
        since_utc="2020-01-01T00:00:00Z",
        granularity=60,
        db_path=db,
        fetcher=_fake_candles,
    )

    assert first["inserted"] == 3
    assert second["existing"] == 3
    assert count_price_points(db) == 3


def test_from_predictions_infers_only_shadow_crypto_symbols(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _prediction(db, symbol="BTC/USD", asset_class="crypto")
    _prediction(db, symbol="ETH/USD", asset_class="crypto")
    _prediction(db, symbol="AAPL", asset_class="equity", broker="alpaca")

    symbols = infer_shadow_crypto_symbols(since_utc="2020-01-01T00:00:00Z", db_path=db)

    assert symbols == ["BTC/USD", "ETH/USD"]


def test_multi_symbol_backfill_idempotency(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _prediction(db, symbol="BTC/USD", asset_class="crypto")
    _prediction(db, symbol="ETH/USD", asset_class="crypto")

    first = backfill_public_prices_for_symbols(
        symbols=["BTC/USD", "ETH/USD"],
        since_utc="2020-01-01T00:00:00Z",
        granularity=60,
        db_path=db,
        fetcher=_fake_candles,
    )
    second = backfill_public_prices_for_symbols(
        symbols=["BTC/USD", "ETH/USD"],
        since_utc="2020-01-01T00:00:00Z",
        granularity=60,
        db_path=db,
        fetcher=_fake_candles,
    )

    assert first["totals"]["inserted"] == 6
    assert second["totals"]["existing"] == 6
    assert count_price_points(db) == 6


def test_backfill_dry_run_writes_nothing(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _prediction(db)

    before = count_price_points(db)
    summary = backfill_public_prices_for_symbols(
        symbols=["BTC/USD"],
        since_utc="2020-01-01T00:00:00Z",
        granularity=60,
        db_path=db,
        dry_run=True,
        fetcher=_fake_candles,
    )

    assert summary["dry_run"] is True
    assert summary["totals"]["normalized_points"] > 0
    assert count_price_points(db) == before


def test_network_failure_produces_warning_not_crash(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _prediction(db)

    def failing_fetcher(product_id, *, start, end, granularity, timeout_seconds):
        del product_id, start, end, granularity, timeout_seconds
        return [], "URLError: network down"

    summary = backfill_public_prices(
        symbol="BTC/USD",
        since_utc="2020-01-01T00:00:00Z",
        granularity=60,
        db_path=db,
        fetcher=failing_fetcher,
    )

    assert summary["inserted"] == 0
    assert summary["errors"] == ["URLError: network down"]


def test_network_failure_for_one_symbol_does_not_stop_other_symbols(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _prediction(db, symbol="BTC/USD", asset_class="crypto")
    _prediction(db, symbol="ETH/USD", asset_class="crypto")

    def mixed_fetcher(product_id, *, start, end, granularity, timeout_seconds):
        if product_id == "ETH-USD":
            return [], "URLError: ETH down"
        return _fake_candles(product_id, start=start, end=end, granularity=granularity, timeout_seconds=timeout_seconds)

    summary = backfill_public_prices_for_symbols(
        symbols=["BTC/USD", "ETH/USD"],
        since_utc="2020-01-01T00:00:00Z",
        granularity=60,
        db_path=db,
        fetcher=mixed_fetcher,
    )

    assert summary["totals"]["inserted"] == 3
    assert count_price_points(db) == 3
    assert any("ETH/USD" in warning for result in summary["results"] for warning in [f"{result['symbol']}: {error}" for error in result["errors"]])


def test_authenticated_endpoint_or_execution_modules_are_not_used():
    combined = "\n".join(
        [
            (ROOT / "shadow_learner" / "public_price_backfill.py").read_text(),
            (ROOT / "scripts" / "shadow_backfill_prices.py").read_text(),
        ]
    )

    assert "Authorization" not in combined
    assert "CB-ACCESS" not in combined
    assert "API_KEY" not in combined
    assert ".env" not in combined
    assert "risk_manager" not in combined
    assert "order_manager" not in combined
    assert "broker_alpaca" not in combined
    assert "broker_coinbase" not in combined


def test_labeler_can_label_prediction_after_imported_public_candles(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    prediction_id = _prediction(db)

    before = classify_prediction_outcome(
        _prediction_row(db, prediction_id),
        [],
        now=datetime(2020, 1, 1, 1, 0, tzinfo=timezone.utc),
    )
    backfill_public_prices(
        symbol="BTC/USD",
        since_utc="2020-01-01T00:00:00Z",
        granularity=60,
        db_path=db,
        fetcher=_fake_candles,
    )
    observations = fetch_price_observations(db_path=db, since_utc="2020-01-01T00:00:00Z")
    after = classify_prediction_outcome(
        _prediction_row(db, prediction_id),
        observations,
        now=datetime(2020, 1, 1, 1, 0, tzinfo=timezone.utc),
    )

    assert before["outcome_status"] == "missing_data"
    assert after["outcome_status"] == "labeled"


def test_backfill_does_not_modify_state_files(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    state_dir = tmp_path / "state" / "coinbase"
    state_dir.mkdir(parents=True)
    state_file = state_dir / "open_positions.json"
    state_file.write_text('{"positions":{}}')
    before = state_file.read_text()

    backfill_public_prices(
        symbol="BTC/USD",
        since_utc="2020-01-01T00:00:00Z",
        granularity=60,
        db_path=db,
        fetcher=_fake_candles,
    )

    assert state_file.read_text() == before


def test_backfill_output_redacts_secret_like_strings():
    from scripts.shadow_backfill_prices import build_output

    output = build_output(
        {
            "dry_run": True,
            "symbol": "BTC/USD",
            "product_id": "BTC-USD",
            "granularity": 60,
            "window": {
                "start_utc": "2026-05-28T00:00:00Z",
                "end_utc": "2026-05-28T01:00:00Z",
            },
            "fetched_candles": 10,
            "normalized_points": 10,
            "inserted": 0,
            "existing": 0,
            "errors": ["account_id=123456 api_key=APCA1234567890ABCDE price=75000"],
        }
    )

    assert "123456" not in output
    assert "APCA1234567890ABCDE" not in output
    assert "BTC/USD" in output
    assert "75000" in output
    assert "2026-05-28T00:00:00Z" in output


def test_report_shows_price_coverage_and_advisory_only(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    backfill_public_prices(
        symbol="BTC/USD",
        since_utc="2020-01-01T00:00:00Z",
        granularity=60,
        db_path=db,
        fetcher=_fake_candles,
    )

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

    assert "Price coverage:" in result.stdout
    assert "BTC/USD: 2020-01-01T00:00:00Z" in result.stdout
    assert "Recommendation: advisory only; not used for live trading" in result.stdout
