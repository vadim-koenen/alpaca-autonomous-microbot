#!/usr/bin/env python3
"""
Read-only runtime status classifier for launchd, heartbeat, and lock state.

This script does not start, stop, load, unload, or signal bot processes. It is
for operator visibility only.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HEARTBEAT_FRESH_SECONDS = 180

BROKERS = {
    "alpaca": {
        "label": "com.vadim.alpaca-bot",
        "plist": "launchd/com.vadim.alpaca-bot.plist",
        "heartbeat": "runtime/alpaca_heartbeat.json",
        "lock": "runtime/alpaca.lock",
    },
    "coinbase": {
        "label": "com.vadim.coinbase-crypto-bot",
        "plist": "launchd/com.vadim.coinbase-crypto-bot.plist",
        "heartbeat": "runtime/coinbase_heartbeat.json",
        "lock": "runtime/coinbase.lock",
    },
}


@dataclass
class LaunchdInfo:
    status: str
    pid: int | None = None
    last_exit_status: str = "?"
    error: str = ""


def _safe_int(value: Any) -> int | None:
    try:
        return int(str(value).strip().strip(";"))
    except (TypeError, ValueError):
        return None


def pid_is_alive(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def read_plist_label(path: Path) -> str | None:
    try:
        with path.open("rb") as handle:
            payload = plistlib.load(handle)
    except (FileNotFoundError, OSError, plistlib.InvalidFileException):
        return None
    label = payload.get("Label")
    return str(label) if label else None


def parse_launchctl_detail(output: str) -> LaunchdInfo:
    pid: int | None = None
    last_exit = "?"

    for line in output.splitlines():
        stripped = line.strip().strip(";")
        if re.search(r'"?PID"?\s*=', stripped):
            pid = _safe_int(stripped.split("=", 1)[1])
        elif re.search(r'"?LastExitStatus"?\s*=', stripped):
            value = stripped.split("=", 1)[1].strip().strip('"')
            last_exit = value or "?"

    return LaunchdInfo(status="LOADED", pid=pid, last_exit_status=last_exit)


def parse_launchctl_table(output: str, label: str) -> LaunchdInfo:
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 3 or parts[-1] != label:
            continue
        pid = _safe_int(parts[0])
        last_exit = parts[1] if len(parts) >= 2 else "?"
        if parts[0] == "-":
            pid = None
        return LaunchdInfo(status="LOADED", pid=pid, last_exit_status=last_exit)
    return LaunchdInfo(status="NOT_LOADED")


def query_launchd(label: str) -> LaunchdInfo:
    try:
        detail = subprocess.run(
            ["launchctl", "list", label],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return LaunchdInfo(status="QUERY_ERROR", error=str(exc))

    if detail.returncode == 0:
        return parse_launchctl_detail(detail.stdout)

    try:
        table = subprocess.run(
            ["launchctl", "list"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return LaunchdInfo(status="QUERY_ERROR", error=str(exc))

    if table.returncode != 0:
        err = (table.stderr or detail.stderr or "").strip()
        return LaunchdInfo(status="QUERY_ERROR", error=err)

    return parse_launchctl_table(table.stdout, label)


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}


def read_lock_pid(path: Path) -> int | None:
    try:
        return _safe_int(path.read_text(encoding="utf-8").strip())
    except OSError:
        return None


def classify_effective_runtime(
    *,
    launchd_status: str,
    launchd_pid_alive: bool,
    heartbeat_present: bool,
    heartbeat_pid_alive: bool,
    heartbeat_fresh: bool,
    lock_present: bool,
    lock_pid_alive: bool,
    installed_plist_matches_expected: bool,
    label_mismatch: bool,
) -> str:
    if label_mismatch:
        return "LABEL_MISMATCH_MANUAL_REVIEW"

    if launchd_status == "LOADED":
        if launchd_pid_alive or (heartbeat_pid_alive and heartbeat_fresh):
            return "RUNNING_BY_LAUNCHD"
        if heartbeat_present and not heartbeat_fresh:
            return "LAUNCHD_LOADED_STALE_HEARTBEAT"
        return "LAUNCHD_LOADED_NOT_RUNNING"

    if heartbeat_pid_alive and heartbeat_fresh:
        if installed_plist_matches_expected:
            return "RUNNING_BY_HEARTBEAT_WITH_LAUNCHD_MISMATCH"
        return "RUNNING_DIRECT_OR_MANUAL"

    if heartbeat_present and not heartbeat_fresh:
        return "STALE_HEARTBEAT"

    if lock_present and lock_pid_alive:
        return "RUNNING_BY_LOCK_ONLY"

    if lock_present:
        return "STALE_LOCK"

    return "STOPPED_OR_NOT_STARTED"


def broker_runtime_report(root: Path, broker: str, home: Path | None = None) -> dict[str, Any]:
    info = BROKERS[broker]
    expected_label = info["label"]
    source_plist = root / info["plist"]
    installed_plist = (home or Path.home()) / "Library" / "LaunchAgents" / f"{expected_label}.plist"

    source_label = read_plist_label(source_plist)
    installed_label = read_plist_label(installed_plist)
    label_mismatch = any(
        label is not None and label != expected_label
        for label in (source_label, installed_label)
    )
    installed_plist_matches_expected = installed_label == expected_label

    launchd = query_launchd(expected_label)
    launchd_pid_alive = pid_is_alive(launchd.pid)

    heartbeat_path = root / info["heartbeat"]
    heartbeat = read_json(heartbeat_path)
    heartbeat_present = heartbeat_path.exists()
    heartbeat_pid = _safe_int(heartbeat.get("pid"))
    heartbeat_pid_alive = pid_is_alive(heartbeat_pid)
    heartbeat_time = parse_time(heartbeat.get("last_loop_time"))
    heartbeat_age_seconds: float | None = None
    heartbeat_fresh = False
    if heartbeat_time is not None:
        heartbeat_age_seconds = max(
            0.0,
            (datetime.now(timezone.utc) - heartbeat_time.astimezone(timezone.utc)).total_seconds(),
        )
        heartbeat_fresh = heartbeat_age_seconds < HEARTBEAT_FRESH_SECONDS

    lock_path = root / info["lock"]
    lock_present = lock_path.exists()
    lock_pid = read_lock_pid(lock_path)
    lock_pid_alive = pid_is_alive(lock_pid)

    effective = classify_effective_runtime(
        launchd_status=launchd.status,
        launchd_pid_alive=launchd_pid_alive,
        heartbeat_present=heartbeat_present,
        heartbeat_pid_alive=heartbeat_pid_alive,
        heartbeat_fresh=heartbeat_fresh,
        lock_present=lock_present,
        lock_pid_alive=lock_pid_alive,
        installed_plist_matches_expected=installed_plist_matches_expected,
        label_mismatch=label_mismatch,
    )

    return {
        "broker": broker,
        "expected_label": expected_label,
        "source_plist_label": source_label or "missing",
        "installed_plist_label": installed_label or "missing",
        "label_mismatch": label_mismatch,
        "launchd_status": launchd.status,
        "launchd_pid": launchd.pid,
        "launchd_pid_alive": launchd_pid_alive,
        "launchd_last_exit_status": launchd.last_exit_status,
        "launchd_error": launchd.error,
        "heartbeat_present": heartbeat_present,
        "heartbeat_pid": heartbeat_pid,
        "heartbeat_pid_alive": heartbeat_pid_alive,
        "heartbeat_fresh": heartbeat_fresh,
        "heartbeat_age_seconds": heartbeat_age_seconds,
        "lock_present": lock_present,
        "lock_pid": lock_pid,
        "lock_pid_alive": lock_pid_alive,
        "effective_runtime_status": effective,
    }


def _fmt_bool(value: bool) -> str:
    return str(bool(value)).lower()


def _fmt_pid(value: int | None) -> str:
    return str(value) if value is not None else "none"


def _fmt_age(value: float | None) -> str:
    return f"{value:.0f}s" if value is not None else "unknown"


def print_text(reports: list[dict[str, Any]]) -> None:
    print("--- Runtime supervisor ---")
    for report in reports:
        print(f"  {report['broker']}: effective_runtime_status={report['effective_runtime_status']}")
        print(
            f"          launchd_status={report['launchd_status']} "
            f"| expected_label={report['expected_label']} "
            f"| source_plist_label={report['source_plist_label']} "
            f"| installed_plist_label={report['installed_plist_label']} "
            f"| label_mismatch={_fmt_bool(report['label_mismatch'])}"
        )
        print(
            f"          launchd_pid={_fmt_pid(report['launchd_pid'])} "
            f"| launchd_pid_alive={_fmt_bool(report['launchd_pid_alive'])} "
            f"| last_exit={report['launchd_last_exit_status']}"
        )
        print(
            f"          heartbeat_pid={_fmt_pid(report['heartbeat_pid'])} "
            f"| heartbeat_pid_alive={_fmt_bool(report['heartbeat_pid_alive'])} "
            f"| heartbeat_fresh={_fmt_bool(report['heartbeat_fresh'])} "
            f"| heartbeat_age={_fmt_age(report['heartbeat_age_seconds'])}"
        )
        print(
            f"          lock_pid={_fmt_pid(report['lock_pid'])} "
            f"| lock_pid_alive={_fmt_bool(report['lock_pid_alive'])}"
        )
        if report["effective_runtime_status"] == "RUNNING_BY_HEARTBEAT_WITH_LAUNCHD_MISMATCH":
            print("          note=process is alive and fresh; launchd query/label visibility needs review")
        elif report["effective_runtime_status"] == "STALE_HEARTBEAT":
            print("          note=heartbeat exists but is stale; do not treat as healthy running")
        elif report["effective_runtime_status"] == "STALE_LOCK":
            print("          note=lock file exists but pid is not alive")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only bot runtime status")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    reports = [broker_runtime_report(root, broker) for broker in ("alpaca", "coinbase")]
    if args.json:
        print(json.dumps({"brokers": reports}, indent=2, sort_keys=True))
    else:
        print_text(reports)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
