
import json
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bot_heartbeat_watchdog.py"

spec = importlib.util.spec_from_file_location("bot_heartbeat_watchdog", SCRIPT)
watchdog = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = watchdog
spec.loader.exec_module(watchdog)

def setup_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "runtime").mkdir()
    (repo / "state" / "coinbase").mkdir(parents=True)
    (repo / "journal_coinbase_crypto.csv").write_text("timestamp,symbol,action,reason\n")
    return repo

def test_p2_029f_stale_failed_close_downgrade(tmp_path):
    root = setup_repo(tmp_path)
    now = datetime(2026, 6, 7, 12, tzinfo=timezone.utc)
    
    # Fresh heartbeat
    (root / "runtime" / "coinbase_heartbeat.json").write_text(json.dumps({
        "last_loop_time": now.isoformat(),
        "trades_today": 0,
    }))
    
    # Failed close artifact
    (root / "journal_coinbase_crypto.csv").write_text(
        "timestamp,symbol,action,reason\n"
        f"{(now - timedelta(hours=2)).isoformat()},SOL/USD,CLOSE,failed_close_error\n"
    )

    # Clean reconciler report
    reconciler_report = {
        "broker_query_succeeded": True,
        "reasons": [],
        "local_open_positions": [],
        "broker_open_orders": [],
        "stop_trading_present": False,
        "heartbeat": {"file_alerting_active": True}
    }
    
    report = watchdog.build_report(repo_root=root, now=now, reconciler_report=reconciler_report)
    
    # Should be INFO
    failed_close_event = next(e for e in report["events"] if e["code"] == "failed_close")
    assert failed_close_event["level"] == "INFO"

def test_p2_029f_stale_manual_review_downgrade(tmp_path):
    root = setup_repo(tmp_path)
    now = datetime(2026, 6, 7, 12, tzinfo=timezone.utc)
    
    (root / "runtime" / "coinbase_heartbeat.json").write_text(json.dumps({
        "last_loop_time": now.isoformat(),
        "trades_today": 0,
    }))
    
    # Manual review artifact in journal
    (root / "journal_coinbase_crypto.csv").write_text(
        "timestamp,symbol,action,reason\n"
        f"{(now - timedelta(hours=1)).isoformat()},,BUY,ENTRY_BLOCKED reason=manual_review_position_open\n"
    )

    reconciler_report = {
        "broker_query_succeeded": True,
        "reasons": [],
        "local_open_positions": [],
        "broker_open_orders": [],
        "stop_trading_present": False,
        "heartbeat": {"file_alerting_active": True}
    }
    
    report = watchdog.build_report(repo_root=root, now=now, reconciler_report=reconciler_report)
    
    # Should be INFO
    manual_review_event = next(e for e in report["events"] if e["code"] == "manual_review_blocker")
    assert manual_review_event["level"] == "INFO"

def test_p2_029f_no_round_trip_24h_downgrade(tmp_path):
    root = setup_repo(tmp_path)
    now = datetime(2026, 6, 7, 12, tzinfo=timezone.utc)
    
    (root / "runtime" / "coinbase_heartbeat.json").write_text(json.dumps({
        "last_loop_time": now.isoformat(),
        "trades_today": 0,
        "last_exit_at": (now - timedelta(hours=25)).isoformat(),
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
    
    # Should be INFO
    no_round_trip_event = next(e for e in report["events"] if e["code"] == "no_round_trip_24h")
    assert no_round_trip_event["level"] == "INFO"

def test_p2_029f_active_failed_close_remains_critical(tmp_path):
    root = setup_repo(tmp_path)
    now = datetime(2026, 6, 7, 12, tzinfo=timezone.utc)
    
    (root / "runtime" / "coinbase_heartbeat.json").write_text(json.dumps({
        "last_loop_time": now.isoformat(),
        "trades_today": 0,
    }))
    
    (root / "journal_coinbase_crypto.csv").write_text(
        "timestamp,symbol,action,reason\n"
        f"{(now - timedelta(hours=2)).isoformat()},SOL/USD,CLOSE,failed_close_error\n"
    )

    # Reconciler not clean because of local open position
    reconciler_report = {
        "broker_query_succeeded": True,
        "reasons": ["ada_broker_exposure_or_open_order_still_present"], # Not empty reasons
        "local_open_positions": ["SOL/USD"],
        "broker_open_orders": [],
        "stop_trading_present": False,
        "heartbeat": {"file_alerting_active": True}
    }
    
    report = watchdog.build_report(repo_root=root, now=now, reconciler_report=reconciler_report)
    
    failed_close_event = next(e for e in report["events"] if e["code"] == "failed_close")
    assert failed_close_event["level"] == "CRITICAL"

def test_p2_029f_active_broker_order_remains_critical(tmp_path):
    root = setup_repo(tmp_path)
    now = datetime(2026, 6, 7, 12, tzinfo=timezone.utc)
    
    (root / "runtime" / "coinbase_heartbeat.json").write_text(json.dumps({
        "last_loop_time": now.isoformat(),
        "trades_today": 0,
    }))
    
    (root / "journal_coinbase_crypto.csv").write_text(
        "timestamp,symbol,action,reason\n"
        f"{(now - timedelta(hours=2)).isoformat()},SOL/USD,CLOSE,failed_close_error\n"
    )

    # Reconciler not clean because of broker open order
    reconciler_report = {
        "broker_query_succeeded": True,
        "reasons": ["open_broker_orders_exist"],
        "local_open_positions": [],
        "broker_open_orders": [{"symbol": "SOL/USD"}],
        "stop_trading_present": False,
        "heartbeat": {"file_alerting_active": True}
    }
    
    report = watchdog.build_report(repo_root=root, now=now, reconciler_report=reconciler_report)
    
    failed_close_event = next(e for e in report["events"] if e["code"] == "failed_close")
    assert failed_close_event["level"] == "CRITICAL"

def test_p2_029f_broker_query_failed_prevents_downgrade(tmp_path):
    root = setup_repo(tmp_path)
    now = datetime(2026, 6, 7, 12, tzinfo=timezone.utc)
    
    (root / "runtime" / "coinbase_heartbeat.json").write_text(json.dumps({
        "last_loop_time": now.isoformat(),
        "trades_today": 0,
    }))
    
    (root / "journal_coinbase_crypto.csv").write_text(
        "timestamp,symbol,action,reason\n"
        f"{(now - timedelta(hours=2)).isoformat()},SOL/USD,CLOSE,failed_close_error\n"
    )

    reconciler_report = {
        "broker_query_succeeded": False,
        "reasons": [],
        "local_open_positions": [],
        "broker_open_orders": [],
        "stop_trading_present": False,
        "heartbeat": {"file_alerting_active": True}
    }
    
    report = watchdog.build_report(repo_root=root, now=now, reconciler_report=reconciler_report)
    assert next(e for e in report["events"] if e["code"] == "failed_close")["level"] == "CRITICAL"

def test_p2_029f_reasons_nonempty_prevents_downgrade(tmp_path):
    root = setup_repo(tmp_path)
    now = datetime(2026, 6, 7, 12, tzinfo=timezone.utc)
    
    (root / "runtime" / "coinbase_heartbeat.json").write_text(json.dumps({
        "last_loop_time": now.isoformat(),
        "trades_today": 0,
    }))
    
    (root / "journal_coinbase_crypto.csv").write_text(
        "timestamp,symbol,action,reason\n"
        f"{(now - timedelta(hours=2)).isoformat()},SOL/USD,CLOSE,failed_close_error\n"
    )

    reconciler_report = {
        "broker_query_succeeded": True,
        "reasons": ["some_reason"],
        "local_open_positions": [],
        "broker_open_orders": [],
        "stop_trading_present": False,
        "heartbeat": {"file_alerting_active": True}
    }
    
    report = watchdog.build_report(repo_root=root, now=now, reconciler_report=reconciler_report)
    assert next(e for e in report["events"] if e["code"] == "failed_close")["level"] == "CRITICAL"

def test_p2_029f_heartbeat_stale_prevents_downgrade(tmp_path):
    root = setup_repo(tmp_path)
    now = datetime(2026, 6, 7, 12, tzinfo=timezone.utc)
    
    # Stale heartbeat (11 minutes)
    (root / "runtime" / "coinbase_heartbeat.json").write_text(json.dumps({
        "last_loop_time": (now - timedelta(minutes=11)).isoformat(),
        "trades_today": 0,
    }))
    
    (root / "journal_coinbase_crypto.csv").write_text(
        "timestamp,symbol,action,reason\n"
        f"{(now - timedelta(hours=2)).isoformat()},SOL/USD,CLOSE,failed_close_error\n"
    )

    reconciler_report = {
        "broker_query_succeeded": True,
        "reasons": [],
        "local_open_positions": [],
        "broker_open_orders": [],
        "stop_trading_present": False,
        "heartbeat": {"file_alerting_active": True}
    }
    
    report = watchdog.build_report(repo_root=root, now=now, reconciler_report=reconciler_report)
    assert next(e for e in report["events"] if e["code"] == "failed_close")["level"] == "CRITICAL"
    assert next(e for e in report["events"] if e["code"] == "heartbeat_stale")["level"] == "CRITICAL"

def test_p2_029f_lock_health_invalid_prevents_downgrade(tmp_path):
    root = setup_repo(tmp_path)
    now = datetime(2026, 6, 7, 12, tzinfo=timezone.utc)
    
    (root / "runtime" / "coinbase_heartbeat.json").write_text(json.dumps({
        "last_loop_time": now.isoformat(),
        "trades_today": 0,
    }))
    
    (root / "journal_coinbase_crypto.csv").write_text(
        "timestamp,symbol,action,reason\n"
        f"{(now - timedelta(hours=2)).isoformat()},SOL/USD,CLOSE,failed_close_error\n"
    )

    # Lock PID exists but not alive
    (root / "runtime" / "coinbase.lock").write_text("12345")
    
    # Process snapshot says a process IS running with a different PID
    snapshot = root / "snapshot.txt"
    snapshot.write_text("  67890 ?? S 0:01.00 python3 main.py --mode live\n")

    reconciler_report = {
        "broker_query_succeeded": True,
        "reasons": [],
        "local_open_positions": [],
        "broker_open_orders": [],
        "stop_trading_present": False,
        "heartbeat": {"file_alerting_active": True}
    }
    
    # alive_pids only contains 67890, so 12345 is not alive.
    report = watchdog.build_report(
        repo_root=root, 
        now=now, 
        reconciler_report=reconciler_report, 
        process_snapshot=snapshot,
        alive_pids={67890}
    )
    
    assert report["lock_health"] == "INVALID"
    # Stays CRITICAL because reconciler_clean will be False
    assert next(e for e in report["events"] if e["code"] == "failed_close")["level"] == "CRITICAL"

def test_p2_029f_file_alerting_inactive_prevents_downgrade(tmp_path):
    root = setup_repo(tmp_path)
    now = datetime(2026, 6, 7, 12, tzinfo=timezone.utc)
    
    (root / "runtime" / "coinbase_heartbeat.json").write_text(json.dumps({
        "last_loop_time": now.isoformat(),
        "trades_today": 0,
    }))
    
    (root / "journal_coinbase_crypto.csv").write_text(
        "timestamp,symbol,action,reason\n"
        f"{(now - timedelta(hours=2)).isoformat()},SOL/USD,CLOSE,failed_close_error\n"
    )

    reconciler_report = {
        "broker_query_succeeded": True,
        "reasons": [],
        "local_open_positions": [],
        "broker_open_orders": [],
        "stop_trading_present": False,
        "heartbeat": {"file_alerting_active": False} # Inactive
    }
    
    report = watchdog.build_report(repo_root=root, now=now, reconciler_report=reconciler_report)
    assert next(e for e in report["events"] if e["code"] == "failed_close")["level"] == "CRITICAL"
