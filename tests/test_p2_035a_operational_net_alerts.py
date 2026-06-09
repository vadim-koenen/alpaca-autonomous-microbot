import json
import os
import shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.bot_alerts as bot_alerts
import scripts.bot_heartbeat_watchdog as watchdog


def setup_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "runtime").mkdir()
    (repo / "state" / "coinbase").mkdir(parents=True)
    (repo / "journal_coinbase_crypto.csv").write_text("timestamp,symbol,action,reason\n")
    return repo


def test_redact_account_ids_and_uuids():
    # Test key redaction
    assert bot_alerts._redact("val", "account_id") == "[REDACTED_ACCOUNT]"  # string <= 4 is replaced completely
    assert bot_alerts._redact("12345678", "account_id") == "****5678"
    assert bot_alerts._redact(12345, "account_id") == "[REDACTED_ACCOUNT]"
    assert bot_alerts._redact(None, "account_id") is None

    # Test UUID redaction inside string
    raw_msg = "error on account d4b97f68-9a92-5fc8-8a7f-b654af62059a details"
    redacted_msg = bot_alerts._redact(raw_msg)
    assert "d4b97f68-9a92-5fc8-8a7f-b654af62059a" not in redacted_msg
    assert "****059a" in redacted_msg

    # Test secrets redaction
    secret_msg = "api_key=mysecretpw123"
    assert bot_alerts._redact(secret_msg) == "api_key=<REDACTED>"


def test_dry_run_macos_notification_does_not_send_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_MACOS_ALERTS", raising=False)
    status = bot_alerts._send_macos_notification("CRITICAL", "Test notification message")
    assert status == "dry_run"


def test_stale_heartbeat_triggers_alert(tmp_path):
    root = setup_repo(tmp_path)
    now = datetime(2026, 6, 7, 12, tzinfo=timezone.utc)
    
    # 11 minutes old heartbeat
    (root / "runtime" / "coinbase_heartbeat.json").write_text(json.dumps({
        "last_loop_time": (now - timedelta(minutes=11)).isoformat(),
        "trades_today": 0,
        "loop_count": 42
    }))
    
    reconciler_report = {
        "broker_query_succeeded": True,
        "reasons": [],
        "local_open_positions": [],
        "broker_open_orders": [],
        "stop_trading_present": False,
        "heartbeat": {"file_alerting_active": True}
    }
    
    report = watchdog.build_report(repo_root=root, now=now, reconciler_report=reconciler_report)
    assert report["heartbeat_fresh"] is False
    assert any(e["code"] == "heartbeat_stale" for e in report["events"])


def test_fresh_advancing_heartbeat_does_not_alert(tmp_path):
    root = setup_repo(tmp_path)
    now = datetime(2026, 6, 7, 12, tzinfo=timezone.utc)
    
    # Fresh heartbeat
    (root / "runtime" / "coinbase_heartbeat.json").write_text(json.dumps({
        "last_loop_time": now.isoformat(),
        "trades_today": 0,
        "loop_count": 42
    }))
    
    reconciler_report = {
        "broker_query_succeeded": True,
        "reasons": [],
        "local_open_positions": [],
        "broker_open_orders": [],
        "stop_trading_present": False,
        "heartbeat": {"file_alerting_active": True}
    }
    
    # Run once to set the watchdog_state.json cache
    watchdog.build_report(repo_root=root, now=now, reconciler_report=reconciler_report)
    
    # Run again with advancing heartbeat (timestamp changes, count advances)
    later_now = now + timedelta(minutes=1)
    (root / "runtime" / "coinbase_heartbeat.json").write_text(json.dumps({
        "last_loop_time": later_now.isoformat(),
        "trades_today": 0,
        "loop_count": 43
    }))
    
    report = watchdog.build_report(repo_root=root, now=later_now, reconciler_report=reconciler_report)
    assert report["heartbeat_fresh"] is True
    assert not any(e["code"] == "heartbeat_stale" for e in report["events"])
    assert not any(e["code"] == "loop_not_advancing" for e in report["events"])


def test_loop_not_advancing_condition_triggers_alert(tmp_path):
    root = setup_repo(tmp_path)
    now = datetime(2026, 6, 7, 12, tzinfo=timezone.utc)
    
    # Write initial state cache
    state_file = root / "runtime" / "watchdog_state.json"
    state_file.write_text(json.dumps({
        "last_loop_time": now.isoformat(),
        "loop_count": 42,
        "updated_at": now.isoformat()
    }))
    
    # Heatbeat timestamp changed but loop count did not change!
    later_now = now + timedelta(minutes=1)
    (root / "runtime" / "coinbase_heartbeat.json").write_text(json.dumps({
        "last_loop_time": later_now.isoformat(),
        "trades_today": 0,
        "loop_count": 42
    }))
    
    reconciler_report = {
        "broker_query_succeeded": True,
        "reasons": [],
        "local_open_positions": [],
        "broker_open_orders": [],
        "stop_trading_present": False,
        "heartbeat": {"file_alerting_active": True}
    }
    
    report = watchdog.build_report(repo_root=root, now=later_now, reconciler_report=reconciler_report)
    assert report["loop_not_advancing_alert"] is True
    assert any(e["code"] == "loop_not_advancing" for e in report["events"])


def test_repeated_errors_threshold_triggers_alert(tmp_path):
    root = setup_repo(tmp_path)
    now = datetime(2026, 6, 7, 12, tzinfo=timezone.utc)
    
    (root / "runtime" / "coinbase_heartbeat.json").write_text(json.dumps({
        "last_loop_time": now.isoformat(),
        "trades_today": 0,
        "loop_count": 42,
        "api_errors_this_session": 5,
        "last_error": "TimeoutError"
    }))
    
    reconciler_report = {
        "broker_query_succeeded": True,
        "reasons": [],
        "local_open_positions": [],
        "broker_open_orders": [],
        "stop_trading_present": False,
        "heartbeat": {"file_alerting_active": True}
    }
    
    report = watchdog.build_report(repo_root=root, now=now, reconciler_report=reconciler_report)
    assert report["api_errors_this_session"] == 5
    assert any(e["code"] == "repeated_errors_detected" for e in report["events"])


def test_lock_diagnostics_alert_on_missing_pid_and_mismatch(tmp_path):
    root = setup_repo(tmp_path)
    now = datetime(2026, 6, 7, 12, tzinfo=timezone.utc)
    
    (root / "runtime" / "coinbase_heartbeat.json").write_text(json.dumps({
        "last_loop_time": now.isoformat(),
        "trades_today": 0,
        "loop_count": 42
    }))
    
    # 1. Lock file with missing / empty PID
    (root / "runtime" / "coinbase.lock").write_text("")
    reconciler_report = {
        "broker_query_succeeded": True,
        "reasons": [],
        "local_open_positions": [],
        "broker_open_orders": [],
        "stop_trading_present": False,
        "heartbeat": {"file_alerting_active": True}
    }
    
    report = watchdog.build_report(repo_root=root, now=now, reconciler_report=reconciler_report)
    assert report["lock_pid_missing"] is True
    assert any(e["code"] == "lock_pid_missing" for e in report["events"])
    
    # 2. Lock file with PID but mismatched with running process PIDs
    (root / "runtime" / "coinbase.lock").write_text("11111")
    snapshot = root / "snapshot.txt"
    snapshot.write_text("  22222 ?? S 0:01.00 python3 main.py --mode live\n")
    
    # alive_pids has 11111 so the lock is considered active/alive, but doesn't match the live snapshot pid (22222)
    report = watchdog.build_report(
        repo_root=root,
        now=now,
        reconciler_report=reconciler_report,
        process_snapshot=snapshot,
        alive_pids={11111, 22222}
    )
    assert report["lock_owner_mismatch"] is True
    assert any(e["code"] == "lock_owner_mismatch" for e in report["events"])


def test_duplicate_process_detection(tmp_path):
    root = setup_repo(tmp_path)
    now = datetime(2026, 6, 7, 12, tzinfo=timezone.utc)
    
    (root / "runtime" / "coinbase_heartbeat.json").write_text(json.dumps({
        "last_loop_time": now.isoformat(),
        "trades_today": 0,
        "loop_count": 42
    }))
    
    (root / "runtime" / "coinbase.lock").write_text("22222")
    
    # Snapshot contains two processes
    snapshot = root / "snapshot.txt"
    snapshot.write_text(
        "  22222 ?? S 0:01.00 python3 main.py --mode live\n"
        "  33333 ?? S 0:01.00 python3 main.py --mode live\n"
    )
    
    reconciler_report = {
        "broker_query_succeeded": True,
        "reasons": [],
        "local_open_positions": [],
        "broker_open_orders": [],
        "stop_trading_present": False,
        "heartbeat": {"file_alerting_active": True}
    }
    
    report = watchdog.build_report(
        repo_root=root,
        now=now,
        reconciler_report=reconciler_report,
        process_snapshot=snapshot,
        alive_pids={22222, 33333}
    )
    
    assert report["duplicate_live_process_risk"] is True
    assert any(e["code"] == "duplicate_live_process" for e in report["events"])
