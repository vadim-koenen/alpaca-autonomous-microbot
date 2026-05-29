"""Tests for read-only launchd/heartbeat/lock status classification."""

from __future__ import annotations

import json
import plistlib
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import runtime_status


def _write_plist(path: Path, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        plistlib.dump({"Label": label}, handle)


def test_launchd_detail_parser_handles_loaded_label():
    output = """
{
    "Label" = "com.vadim.alpaca-bot";
    "LastExitStatus" = 0;
    "PID" = 12345;
}
"""

    parsed = runtime_status.parse_launchctl_detail(output)

    assert parsed.status == "LOADED"
    assert parsed.pid == 12345
    assert parsed.last_exit_status == "0"


def test_launchd_table_parser_handles_loaded_label():
    output = """PID\tStatus\tLabel
12345\t0\tcom.vadim.alpaca-bot
-\t0\tcom.example.other
"""

    parsed = runtime_status.parse_launchctl_table(output, "com.vadim.alpaca-bot")

    assert parsed.status == "LOADED"
    assert parsed.pid == 12345
    assert parsed.last_exit_status == "0"


def test_not_loaded_label_but_live_heartbeat_reports_launchd_mismatch(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    home = tmp_path / "home"
    label = "com.vadim.alpaca-bot"
    _write_plist(root / "launchd" / "com.vadim.alpaca-bot.plist", label)
    _write_plist(home / "Library" / "LaunchAgents" / "com.vadim.alpaca-bot.plist", label)
    (root / "runtime").mkdir(parents=True)
    (root / "runtime" / "alpaca_heartbeat.json").write_text(
        json.dumps({
            "pid": 22222,
            "status": "running",
            "last_loop_time": datetime.now(timezone.utc).isoformat(),
        }),
        encoding="utf-8",
    )
    (root / "runtime" / "alpaca.lock").write_text("22222", encoding="utf-8")
    monkeypatch.setattr(
        runtime_status,
        "query_launchd",
        lambda _label: runtime_status.LaunchdInfo(status="NOT_LOADED"),
    )
    monkeypatch.setattr(runtime_status, "pid_is_alive", lambda pid: pid == 22222)

    report = runtime_status.broker_runtime_report(root, "alpaca", home=home)

    assert report["launchd_status"] == "NOT_LOADED"
    assert report["heartbeat_pid_alive"] is True
    assert report["heartbeat_fresh"] is True
    assert report["effective_runtime_status"] == "RUNNING_BY_HEARTBEAT_WITH_LAUNCHD_MISMATCH"


def test_label_mismatch_is_flagged(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    home = tmp_path / "home"
    _write_plist(root / "launchd" / "com.vadim.alpaca-bot.plist", "com.example.wrong-label")
    (root / "runtime").mkdir(parents=True)
    monkeypatch.setattr(
        runtime_status,
        "query_launchd",
        lambda _label: runtime_status.LaunchdInfo(status="NOT_LOADED"),
    )

    report = runtime_status.broker_runtime_report(root, "alpaca", home=home)

    assert report["label_mismatch"] is True
    assert report["effective_runtime_status"] == "LABEL_MISMATCH_MANUAL_REVIEW"


def test_process_alive_without_installed_plist_reports_direct_or_manual():
    status = runtime_status.classify_effective_runtime(
        launchd_status="NOT_LOADED",
        launchd_pid_alive=False,
        heartbeat_present=True,
        heartbeat_pid_alive=True,
        heartbeat_fresh=True,
        lock_present=True,
        lock_pid_alive=True,
        installed_plist_matches_expected=False,
        label_mismatch=False,
    )

    assert status == "RUNNING_DIRECT_OR_MANUAL"


def test_stale_heartbeat_does_not_report_healthy():
    status = runtime_status.classify_effective_runtime(
        launchd_status="NOT_LOADED",
        launchd_pid_alive=False,
        heartbeat_present=True,
        heartbeat_pid_alive=True,
        heartbeat_fresh=False,
        lock_present=False,
        lock_pid_alive=False,
        installed_plist_matches_expected=True,
        label_mismatch=False,
    )

    assert status == "STALE_HEARTBEAT"


def test_status_script_syntax_remains_valid():
    result = subprocess.run(
        ["bash", "-n", str(ROOT / "scripts" / "status.sh")],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
