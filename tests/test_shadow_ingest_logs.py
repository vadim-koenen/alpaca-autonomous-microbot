import os
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.shadow_ingest_logs import redact_for_output

ROOT = Path(__file__).resolve().parents[1]


def _make_roots(tmp_path, *, alpaca_lines=None, coinbase_lines=None):
    logs = tmp_path / "logs"
    runtime = tmp_path / "runtime"
    state = tmp_path / "state"
    logs.mkdir()
    runtime.mkdir()
    (state / "alpaca").mkdir(parents=True)
    (state / "coinbase").mkdir(parents=True)
    (logs / "alpaca.launchd.out.log").write_text("\n".join(alpaca_lines or []) + ("\n" if alpaca_lines else ""))
    (logs / "coinbase.launchd.out.log").write_text("\n".join(coinbase_lines or []) + ("\n" if coinbase_lines else ""))
    (runtime / "alpaca_heartbeat.json").write_text("{}")
    (runtime / "coinbase_heartbeat.json").write_text("{}")
    (state / "alpaca" / "open_positions.json").write_text(
        '{"saved_at":"2026-05-28T14:00:00Z","state_namespace":"alpaca","positions":{}}'
    )
    (state / "coinbase" / "open_positions.json").write_text(
        '{"saved_at":"2026-05-28T14:00:00Z","state_namespace":"coinbase","positions":{}}'
    )
    return logs, runtime, state


def _run_ingest(tmp_path, *, broker="all", dry_run=False, alpaca_lines=None, coinbase_lines=None):
    logs, runtime, state = _make_roots(
        tmp_path,
        alpaca_lines=alpaca_lines,
        coinbase_lines=coinbase_lines,
    )
    db = tmp_path / "shadow.sqlite3"
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "shadow_ingest_logs.py"),
        "--since",
        "2026-05-28",
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
    result = subprocess.run(cmd, check=True, text=True, capture_output=True)
    return db, result, logs, runtime, state


def _count(db, table):
    with sqlite3.connect(db) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _snapshot_row(db):
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM shadow_feature_snapshots").fetchone()


def test_alpaca_invalid_quote_line_creates_snapshot(tmp_path):
    db, _result, *_ = _run_ingest(
        tmp_path,
        broker="alpaca",
        alpaca_lines=[
            "2026-05-28 09:00:01 | INFO     | strategy.equities | SCAN AAPL equity | invalid quote bid=0 ask=0 — skipped"
        ],
    )

    row = _snapshot_row(db)
    assert _count(db, "shadow_feature_snapshots") == 1
    assert row["broker"] == "alpaca"
    assert row["symbol"] == "AAPL"
    assert row["market_data_status"] == "invalid_quote"


def test_alpaca_stale_quote_line_creates_snapshot(tmp_path):
    db, _result, *_ = _run_ingest(
        tmp_path,
        broker="alpaca",
        alpaca_lines=[
            "2026-05-28 09:00:02 | INFO     | strategy.equities | SCAN NVDA equity | stale quote quote_time=2026-05-28T13:58:00Z age=121s — skipped"
        ],
    )

    row = _snapshot_row(db)
    assert row["symbol"] == "NVDA"
    assert row["market_data_status"] == "stale_quote"
    assert row["quote_age_seconds"] == 121.0


def test_alpaca_no_bars_line_creates_snapshot(tmp_path):
    db, _result, *_ = _run_ingest(
        tmp_path,
        broker="alpaca",
        alpaca_lines=[
            "2026-05-28 09:00:03 | INFO     | strategy.equities | SCAN MSFT equity | no bars returned — skipped"
        ],
    )

    row = _snapshot_row(db)
    assert row["symbol"] == "MSFT"
    assert row["market_data_status"] == "no_bars"
    assert row["bars_available"] == 0


def test_alpaca_spread_too_wide_line_creates_snapshot_with_spread(tmp_path):
    db, _result, *_ = _run_ingest(
        tmp_path,
        broker="alpaca",
        alpaca_lines=[
            "2026-05-28 09:00:04 | INFO     | strategy.equities | SCAN SPY equity | spread too wide 0.707% > max=0.100% — skipped"
        ],
    )

    row = _snapshot_row(db)
    assert row["symbol"] == "SPY"
    assert row["market_data_status"] == "spread_too_wide"
    assert row["spread_pct"] == 0.707


def test_strategy_scan_complete_line_is_parsed_without_crashing(tmp_path):
    db, result, *_ = _run_ingest(
        tmp_path,
        broker="alpaca",
        alpaca_lines=[
            "2026-05-28 09:00:05 | INFO     | strategy_router | Strategy scan complete: 0 proposal(s) across all asset classes"
        ],
    )

    assert "Parsed snapshots: 0" in result.stdout
    assert _count(db, "shadow_feature_snapshots") == 0


def test_coinbase_probe_fill_and_exit_lines_are_parsed(tmp_path):
    db, _result, *_ = _run_ingest(
        tmp_path,
        broker="coinbase",
        coinbase_lines=[
            "2026-05-28 08:30:23 | INFO     | strategy.crypto | SIGNAL coinbase_probe BTC/USD | regime=dead_chop notional=$0.50 limit=72952.75000000 conf=0.55 spread=0.000% rsi=36.7",
            "2026-05-28 08:47:51 | INFO     | broker_coinbase | MARKET ORDER PLACED: broker_order_id=c836e22c-f654-4def-8e07-b69b5dff47d4 client_order_id=cb-position_manager-BTCUSD-sell-20260528T134751Z-exit-6cef | SELL BTC/USD | fee≈$0.0000",
            "2026-05-28 08:47:51 | INFO     | position_manager | EXIT triggered: BTC/USD | max hold time 90min exceeded (91.1min held) | entry=73262.2100 exit=72735.2650 qty=0.000007",
        ],
    )

    assert _count(db, "shadow_feature_snapshots") == 3
    assert _count(db, "shadow_predictions") > 0
    with sqlite3.connect(db) as conn:
        live_meta = conn.execute(
            "SELECT COUNT(*) FROM shadow_predictions WHERE live_trade_taken = 1"
        ).fetchone()[0]
    assert live_meta > 0


def test_idempotency_same_log_twice_does_not_duplicate(tmp_path):
    line = "2026-05-28 09:00:06 | INFO     | strategy.equities | SCAN AAPL equity | spread too wide 0.500% > max=0.100% — skipped"
    db, _result, logs, runtime, state = _run_ingest(
        tmp_path,
        broker="alpaca",
        alpaca_lines=[line],
    )
    first_snapshots = _count(db, "shadow_feature_snapshots")
    first_predictions = _count(db, "shadow_predictions")

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_ingest_logs.py"),
            "--since",
            "2026-05-28",
            "--broker",
            "alpaca",
            "--db",
            str(db),
            "--logs-root",
            str(logs),
            "--runtime-root",
            str(runtime),
            "--state-root",
            str(state),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert _count(db, "shadow_feature_snapshots") == first_snapshots
    assert _count(db, "shadow_predictions") == first_predictions


def test_dry_run_does_not_write_db(tmp_path):
    db, result, *_ = _run_ingest(
        tmp_path,
        broker="alpaca",
        dry_run=True,
        alpaca_lines=[
            "2026-05-28 09:00:07 | INFO     | strategy.equities | SCAN AAPL equity | no bars returned — skipped"
        ],
    )

    assert "Mode: dry-run" in result.stdout
    assert "Parsed snapshots: 1" in result.stdout
    assert not db.exists()


def test_redaction_removes_sensitive_values_from_output(tmp_path):
    db, result, *_ = _run_ingest(
        tmp_path,
        broker="coinbase",
        dry_run=True,
        coinbase_lines=[
            "2026-05-28 08:30:23 | INFO     | strategy.crypto | SIGNAL coinbase_probe BTC/USD | regime=dead_chop notional=$0.50 limit=100.00 conf=0.55 spread=0.000% rsi=36.7 account_id=123456789 broker_order_id=c836e22c-f654-4def-8e07-b69b5dff47d4 api_key=APCA1234567890ABCDE"
        ],
    )

    assert not db.exists()
    assert "123456789" not in result.stdout
    assert "c836e22c-f654-4def-8e07-b69b5dff47d4" not in result.stdout
    assert "APCA1234567890ABCDE" not in result.stdout
    assert "[REDACTED" in result.stdout


def test_symbols_are_not_redacted():
    redacted = redact_for_output("BTC/USD SPY AAPL MSFT NVDA Account: 123456789")

    assert "BTC/USD" in redacted
    assert "SPY" in redacted
    assert "AAPL" in redacted
    assert "MSFT" in redacted
    assert "NVDA" in redacted
    assert "123456789" not in redacted


def test_numeric_trading_context_remains_visible_after_redaction():
    text = "2026-05-28 08:30:23 notional=$0.50 limit=100.00 spread=0.000% account_id=123456"
    redacted = redact_for_output(text)

    assert "2026-05-28 08:30:23" in redacted
    assert "$0.50" in redacted
    assert "100.00" in redacted
    assert "0.000%" in redacted
    assert "123456" not in redacted


def test_ingest_does_not_write_order_risk_or_position_state_files(tmp_path):
    line = "2026-05-28 09:00:08 | INFO     | strategy.equities | SCAN AAPL equity | no bars returned — skipped"
    db, _result, _logs, _runtime, state = _run_ingest(
        tmp_path,
        broker="alpaca",
        alpaca_lines=[line],
    )
    watched = [
        state / "alpaca" / "open_positions.json",
        state / "coinbase" / "open_positions.json",
    ]
    before = {path: path.read_text() for path in watched}

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_ingest_logs.py"),
            "--since",
            "2026-05-28",
            "--broker",
            "alpaca",
            "--db",
            str(db),
            "--logs-root",
            str(tmp_path / "logs"),
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--state-root",
            str(state),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert {path: path.read_text() for path in watched} == before


def test_ingest_script_does_not_import_execution_modules():
    source = (ROOT / "scripts" / "shadow_ingest_logs.py").read_text()

    assert "risk_manager" not in source
    assert "order_manager" not in source
    assert "broker_alpaca" not in source
    assert "broker_coinbase" not in source


def test_empty_logs_produce_clean_zero_count_report(tmp_path):
    db, _result, logs, runtime, state = _run_ingest(tmp_path)
    report = subprocess.run(
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

    assert logs.exists()
    assert runtime.exists()
    assert state.exists()
    assert "Snapshots: 0" in report.stdout
    assert "Predictions: 0" in report.stdout


def test_report_shows_advisory_only_warning(tmp_path):
    db, _result, *_ = _run_ingest(
        tmp_path,
        broker="alpaca",
        alpaca_lines=[
            "2026-05-28 09:00:09 | INFO     | strategy.equities | SCAN NVDA equity | no bars returned — skipped"
        ],
    )
    report = subprocess.run(
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

    assert "Sample count by broker:" in report.stdout
    assert "Ingestion source summary:" in report.stdout
    assert "Recommendation: advisory only; not used for live trading" in report.stdout
