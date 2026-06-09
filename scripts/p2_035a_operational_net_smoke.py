"""
Smoke test for P2-035A Operational Net Alerts.
Run with: ENABLE_MACOS_ALERTS=1 python3 scripts/p2_035a_operational_net_smoke.py
"""
import json
import os
import tempfile
import sys
from datetime import datetime, timezone
from pathlib import Path

# Setup paths
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.bot_heartbeat_watchdog import build_report, main as watchdog_main
from scripts.bot_alerts import _send_macos_notification, _redact

def test_redaction():
    print("=== Testing Redaction ===")
    assert _redact("12345678", "account_id") == "****5678"
    assert _redact("d4b97f68-9a92-5fc8-8a7f-b654af62059a") == "****059a"
    print("Redaction checks passed.\n")


def test_macos_notification():
    print("=== Testing macOS Notification (Dry Run & Live) ===")
    
    # Force dry run
    os.environ.pop("ENABLE_MACOS_ALERTS", None)
    res = _send_macos_notification("INFO", "Dry run smoke test")
    print(f"macOS dry-run result: {res}")
    assert res == "dry_run"

    # Live (only if explicitly enabled via P2_035A_SMOKE_SEND_MACOS_ALERTS)
    if os.environ.get("P2_035A_SMOKE_SEND_MACOS_ALERTS") == "1":
        os.environ["ENABLE_MACOS_ALERTS"] = "1"
        res = _send_macos_notification("INFO", "P2-035A Smoke Test Notification")
        print(f"Live run result: {res}")
        if res.startswith("failed"):
            print("Warning: osascript notification failed (expected if running headless/SSH).")
    else:
        print("Live notification test skipped by default.")

    print("macOS Notification checks completed.\n")


def test_watchdog_smoke():
    print("=== Testing Watchdog Smoke ===")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "runtime").mkdir()
        (tmp_path / "state" / "coinbase").mkdir(parents=True)
        
        # Stale heartbeat (older than 10 mins)
        (tmp_path / "runtime" / "coinbase_heartbeat.json").write_text(json.dumps({
            "last_loop_time": "2020-01-01T12:00:00Z",
            "trades_today": 0,
            "loop_count": 5
        }))

        # Mock process output
        (tmp_path / "runtime" / "coinbase.lock").write_text("12345")
        
        # Test full report
        reconciler_report = {
            "broker_query_succeeded": True,
            "reasons": [],
            "local_open_positions": [],
            "broker_open_orders": [],
            "stop_trading_present": False,
            "heartbeat": {"file_alerting_active": True}
        }
        
        now = datetime.now(timezone.utc)
        report = build_report(repo_root=tmp_path, now=now, reconciler_report=reconciler_report)
        
        print(f"Heartbeat Fresh: {report['heartbeat_fresh']}")
        print(f"Events Generated: {[e['code'] for e in report['events']]}")
        
        assert not report['heartbeat_fresh']
        assert any(e['code'] == 'heartbeat_stale' for e in report['events'])
        assert any(e['code'] == 'stale_runtime_lock' for e in report['events'])
        print("Watchdog Smoke completed.\n")


if __name__ == "__main__":
    test_redaction()
    test_macos_notification()
    test_watchdog_smoke()
    print("ALL SMOKE TESTS PASSED.")
