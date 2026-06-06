import importlib.util
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bot_heartbeat_watchdog.py"
ALERT_SCRIPT = ROOT / "scripts" / "bot_alerts.py"
FIXTURE = ROOT / "tests" / "fixtures" / "coinbase_manual_review_blocker_watchdog"

spec = importlib.util.spec_from_file_location("bot_heartbeat_watchdog", SCRIPT)
watchdog = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = watchdog
spec.loader.exec_module(watchdog)

alert_spec = importlib.util.spec_from_file_location("bot_alerts_direct", ALERT_SCRIPT)
alerts = importlib.util.module_from_spec(alert_spec)
sys.modules[alert_spec.name] = alerts
alert_spec.loader.exec_module(alerts)


def copy_root(tmp_path: Path) -> Path:
    target = tmp_path / "repo"
    shutil.copytree(FIXTURE, target)
    return target


def test_stale_heartbeat_manual_blocker_failed_close_and_duplicate_alerts(tmp_path):
    root = copy_root(tmp_path)
    (root / "runtime" / "coinbase_heartbeat.json").write_text(
        json.dumps({
            "last_loop_time": "2026-06-05T10:00:00+00:00",
            "last_exit_at": None,
            "pid": 34222,
        }),
        encoding="utf-8",
    )
    report = watchdog.build_report(
        repo_root=root,
        process_snapshot=root / "process_snapshot.txt",
        now=datetime(2026, 6, 6, 12, tzinfo=timezone.utc),
        alive_pids={99999999},
    )
    codes = {event["code"] for event in report["events"]}
    assert report["heartbeat_fresh"] is False
    assert "heartbeat_stale" in codes
    assert "manual_review_blocker" in codes
    assert "failed_close" in codes
    assert "duplicate_live_process" in codes
    assert "no_round_trip_24h" in codes


def test_alerts_jsonl_and_text_are_written_and_email_is_optional(tmp_path):
    result = alerts.alert(
        "CRITICAL",
        "failed close token=do-not-print",
        {"api_key": "hidden", "symbol": "ADA/USD"},
        reports_root=tmp_path,
        now=datetime(2026, 6, 6, 12, tzinfo=timezone.utc),
    )
    assert result["file_alert_written"] is True
    assert result["email_status"] == "email_not_configured"
    json_text = (tmp_path / "alerts" / "alerts.jsonl").read_text(encoding="utf-8")
    human_text = (tmp_path / "alerts" / "alerts.log").read_text(encoding="utf-8")
    assert "hidden" not in json_text
    assert "do-not-print" not in json_text
    assert "<REDACTED>" in json_text
    assert "ADA/USD" in human_text


def test_emit_alerts_activates_file_based_heartbeat(tmp_path):
    root = copy_root(tmp_path)
    report = watchdog.build_report(
        repo_root=root,
        process_snapshot=root / "process_snapshot.txt",
        now=datetime(2026, 6, 6, 12, tzinfo=timezone.utc),
        alive_pids={99999999},
        emit_alerts=True,
        reports_root=tmp_path / "reports",
    )
    assert report["file_alerting_active"] is True
    assert report["alerts_emitted"] == len(report["events"]) + 1
    assert (tmp_path / "reports" / "alerts" / "alerts.jsonl").exists()


def test_default_watchdog_is_read_only(tmp_path):
    root = copy_root(tmp_path)
    before = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    report = watchdog.build_report(
        repo_root=root,
        process_snapshot=root / "process_snapshot.txt",
        now=datetime(2026, 6, 6, 12, tzinfo=timezone.utc),
        alive_pids={99999999},
    )
    after = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert report["read_only_default"] is True
    assert before == after


def test_live_process_without_valid_lock_or_heartbeat_is_critical(tmp_path):
    root = copy_root(tmp_path)
    report = watchdog.build_report(
        repo_root=root,
        process_snapshot=root / "process_snapshot.txt",
        now=datetime(2026, 6, 6, 12, tzinfo=timezone.utc),
        alive_pids=set(),
    )
    assert report["live_process_without_valid_lock_or_heartbeat"] is True
    assert report["highest_alert_level"] == "CRITICAL"


def test_scripts_have_no_process_control_or_broker_hooks():
    combined = SCRIPT.read_text(encoding="utf-8") + ALERT_SCRIPT.read_text(encoding="utf-8")
    for token in (
        "subprocess.",
        "os.kill",
        "launchctl",
        "BrokerCoinbase",
        "create_order",
        "place_order",
        "cancel_order",
        "close_position",
    ):
        assert token not in combined
