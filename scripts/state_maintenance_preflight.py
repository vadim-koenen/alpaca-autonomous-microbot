#!/usr/bin/env python3
"""Read-only state maintenance preflight report.

This script inspects local state and runtime indicators only. It does not write
state files, call broker APIs, or control running processes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BROKERS = ("coinbase", "alpaca")
POSITION_KINDS = ("open", "closed")
BOT_OPEN_POSITION_SAFETY_DEFAULTS = {
    "counts_toward_exposure": True,
    "api_controllable": True,
    "bot_opened": True,
    "exit_evaluation_enabled": True,
    "user_action_required": False,
}
BROKER_RECOVERED_POSITION_SAFETY_FIELDS = {
    "api_controllable": False,
    "bot_opened": False,
    "exit_evaluation_enabled": False,
    "user_action_required": True,
}
HEARTBEAT_FRESH_SECONDS = 120
STATUS_RANK = {
    "OK": 0,
    "WARN": 1,
    "ACTION_REQUIRED": 2,
    "BLOCKED_MANUAL_REVIEW": 3,
}


@dataclass
class StateFileReport:
    broker: str
    kind: str
    path: Path
    status: str = "OK"
    valid: bool = True
    missing: bool = False
    error: str = ""
    positions: dict[str, Any] = field(default_factory=dict)
    broker_recovered: int = 0
    api_controllable_false: int = 0
    exit_evaluation_enabled_false: int = 0
    missing_counts_toward_exposure: int = 0


@dataclass
class RuntimeReport:
    broker: str
    status: str = "OK"
    running: bool = False
    lock_present: bool = False
    lock_pid: int | None = None
    lock_pid_alive: bool = False
    heartbeat_present: bool = False
    heartbeat_valid: bool = True
    heartbeat_pid: int | None = None
    heartbeat_pid_alive: bool = False
    heartbeat_fresh: bool = False
    heartbeat_age_seconds: float | None = None
    heartbeat_status: str | None = None
    error: str = ""


def root_dir() -> Path:
    override = os.environ.get("BOT_DIR_OVERRIDE")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[1]


def max_status(*statuses: str) -> str:
    return max(statuses, key=lambda value: STATUS_RANK[value])


def pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def read_pid(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    return int(digits) if digits else None


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_positions_report(root: Path, broker: str, kind: str) -> StateFileReport:
    path = root / "state" / broker / f"{kind}_positions.json"
    report = StateFileReport(broker=broker, kind=kind, path=path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        report.valid = False
        report.missing = True
        report.status = "WARN"
        report.error = "missing"
        return report
    except json.JSONDecodeError as exc:
        report.valid = False
        report.status = "BLOCKED_MANUAL_REVIEW"
        report.error = f"invalid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}"
        return report

    if payload == {}:
        positions = {}
    elif isinstance(payload, dict):
        positions = payload.get("positions")
    else:
        positions = None
    if not isinstance(positions, dict):
        report.valid = False
        report.status = "BLOCKED_MANUAL_REVIEW"
        report.error = "missing positions object"
        return report

    report.positions = positions
    for position in positions.values():
        if not isinstance(position, dict):
            report.status = max_status(report.status, "WARN")
            continue
        if position.get("order_status") == "broker_recovered":
            report.broker_recovered += 1
        if position.get("api_controllable") is False:
            report.api_controllable_false += 1
        if position.get("exit_evaluation_enabled") is False:
            report.exit_evaluation_enabled_false += 1
        if "counts_toward_exposure" not in position:
            report.missing_counts_toward_exposure += 1

    if kind == "open" and report.broker_recovered:
        report.status = max_status(report.status, "ACTION_REQUIRED")
    if kind == "open" and (
        report.api_controllable_false
        or report.exit_evaluation_enabled_false
        or report.missing_counts_toward_exposure
    ):
        report.status = max_status(report.status, "WARN")
    return report


def runtime_report(root: Path, broker: str) -> RuntimeReport:
    report = RuntimeReport(broker=broker)
    lock_path = root / "runtime" / f"{broker}.lock"
    heartbeat_path = root / "runtime" / f"{broker}_heartbeat.json"

    if lock_path.exists():
        report.lock_present = True
        report.lock_pid = read_pid(lock_path)
        if report.lock_pid is not None:
            report.lock_pid_alive = pid_is_alive(report.lock_pid)

    if heartbeat_path.exists():
        report.heartbeat_present = True
        try:
            heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            report.heartbeat_valid = False
            report.status = "WARN"
            report.error = f"invalid heartbeat JSON: {exc.msg}"
            heartbeat = {}

        heartbeat_pid = heartbeat.get("pid")
        if isinstance(heartbeat_pid, int):
            report.heartbeat_pid = heartbeat_pid
            report.heartbeat_pid_alive = pid_is_alive(heartbeat_pid)
        report.heartbeat_status = heartbeat.get("status")
        parsed = parse_time(heartbeat.get("last_loop_time"))
        if parsed is not None:
            age = (datetime.now(timezone.utc) - parsed).total_seconds()
            report.heartbeat_age_seconds = age
            report.heartbeat_fresh = age < HEARTBEAT_FRESH_SECONDS

    report.running = (
        report.lock_pid_alive
        or report.heartbeat_pid_alive
        or (report.heartbeat_status == "running" and report.heartbeat_fresh)
    )
    if report.running:
        report.status = max_status(report.status, "WARN")
    elif report.lock_present or report.heartbeat_present:
        report.status = max_status(report.status, "WARN")
    return report


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def suggested_clear_command(broker: str, position_key: str) -> str:
    return (
        "bash scripts/clear_recovered_position.sh "
        f"--broker {broker} "
        f"--key {shell_quote(position_key)} "
        f"--reason {shell_quote('<operator verified reason>')}"
    )


def is_non_controllable(position: Any) -> bool:
    if not isinstance(position, dict):
        return False
    return (
        position.get("api_controllable") is False
        or position.get("exit_evaluation_enabled") is False
    )


def print_file_report(root: Path, report: StateFileReport) -> None:
    rel_path = report.path.relative_to(root)
    print(
        f"- {rel_path}: status={report.status} valid={str(report.valid).lower()} "
        f"missing={str(report.missing).lower()} positions={len(report.positions)} "
        f"broker_recovered={report.broker_recovered} "
        f"api_controllable_false={report.api_controllable_false} "
        f"exit_evaluation_enabled_false={report.exit_evaluation_enabled_false} "
        f"missing_counts_toward_exposure={report.missing_counts_toward_exposure}"
    )
    if report.error:
        print(f"  error={report.error}")


def print_runtime_report(report: RuntimeReport) -> None:
    age = "unknown"
    if report.heartbeat_age_seconds is not None:
        age = f"{report.heartbeat_age_seconds:.0f}s"
    print(
        f"- {report.broker}: status={report.status} running={str(report.running).lower()} "
        f"lock_present={str(report.lock_present).lower()} "
        f"lock_pid={report.lock_pid if report.lock_pid is not None else 'none'} "
        f"lock_pid_alive={str(report.lock_pid_alive).lower()} "
        f"heartbeat_present={str(report.heartbeat_present).lower()} "
        f"heartbeat_pid={report.heartbeat_pid if report.heartbeat_pid is not None else 'none'} "
        f"heartbeat_pid_alive={str(report.heartbeat_pid_alive).lower()} "
        f"heartbeat_fresh={str(report.heartbeat_fresh).lower()} "
        f"heartbeat_age={age}"
    )
    if report.error:
        print(f"  error={report.error}")


def build_report(root: Path) -> tuple[str, list[RuntimeReport], list[StateFileReport]]:
    runtime_reports = [runtime_report(root, broker) for broker in BROKERS]
    state_reports: list[StateFileReport] = []
    for broker in BROKERS:
        for kind in POSITION_KINDS:
            state_reports.append(load_positions_report(root, broker, kind))

    overall = "OK"
    for report in [*runtime_reports, *state_reports]:
        overall = max_status(overall, report.status)

    running_by_broker = {report.broker: report.running for report in runtime_reports}
    for report in state_reports:
        if report.kind == "open" and report.broker_recovered and running_by_broker.get(report.broker):
            report.status = "BLOCKED_MANUAL_REVIEW"
            overall = max_status(overall, "BLOCKED_MANUAL_REVIEW")

    return overall, runtime_reports, state_reports


def suggested_cleanup_items(
    runtime_reports: list[RuntimeReport],
    state_reports: list[StateFileReport],
) -> list[dict[str, Any]]:
    running_by_broker = {report.broker: report.running for report in runtime_reports}
    items: list[dict[str, Any]] = []
    for report in state_reports:
        if report.kind != "open" or not report.valid:
            continue
        for position_key, position in report.positions.items():
            if not isinstance(position, dict):
                continue
            if position.get("order_status") != "broker_recovered":
                continue
            blocked = running_by_broker.get(report.broker, False)
            status = "BLOCKED_MANUAL_REVIEW" if blocked else "ACTION_REQUIRED"
            items.append(
                {
                    "broker": report.broker,
                    "position_key": position_key,
                    "status": status,
                    "command": suggested_clear_command(report.broker, position_key),
                    "blocked": blocked,
                    "reason": (
                        "bot appears to be running"
                        if blocked
                        else "broker_recovered open position requires operator review"
                    ),
                }
            )
    return items


def suggested_state_init_command() -> str:
    return "python3 scripts/state_maintenance_preflight.py --init-missing"


def suggested_state_normalization_command() -> str:
    return "python3 scripts/state_maintenance_preflight.py --normalize-state"


def is_broker_recovered_position(position: dict[str, Any]) -> bool:
    return (
        position.get("order_status") == "broker_recovered"
        or (
            not position.get("order_id", "")
            and position.get("strategy") == "recovered"
        )
    )


def normalize_position_safety_fields(position: dict[str, Any]) -> dict[str, Any]:
    pos = dict(position)
    if is_broker_recovered_position(pos):
        pos["order_status"] = "broker_recovered"
        pos.setdefault("recovery_source", "broker_position")
        pos.setdefault("reconciliable", False)
        for key, value in BROKER_RECOVERED_POSITION_SAFETY_FIELDS.items():
            pos[key] = value
        pos.setdefault("counts_toward_exposure", True)
        return pos

    for key, value in BOT_OPEN_POSITION_SAFETY_DEFAULTS.items():
        pos.setdefault(key, value)
    return pos


def state_normalization_items(
    root: Path,
    state_reports: list[StateFileReport],
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for report in state_reports:
        if report.kind != "open" or not report.valid:
            continue
        for position_key, position in report.positions.items():
            if not isinstance(position, dict):
                continue
            normalized = normalize_position_safety_fields(position)
            if normalized == position:
                continue
            fields = [
                field for field in BOT_OPEN_POSITION_SAFETY_DEFAULTS
                if field not in position
            ]
            if is_broker_recovered_position(position):
                fields.extend(
                    field for field, value in BROKER_RECOVERED_POSITION_SAFETY_FIELDS.items()
                    if position.get(field) != value
                )
            items.append(
                {
                    "broker": report.broker,
                    "position_key": position_key,
                    "path": relative_report_path(root, report),
                    "reason": "missing_or_inconsistent_safety_fields",
                    "fields": ",".join(sorted(set(fields))),
                }
            )
    return items


def missing_state_reports(state_reports: list[StateFileReport]) -> list[StateFileReport]:
    return [report for report in state_reports if report.missing]


def invalid_existing_state_reports(state_reports: list[StateFileReport]) -> list[StateFileReport]:
    return [report for report in state_reports if not report.valid and not report.missing]


def relative_report_path(root: Path, report: StateFileReport) -> str:
    try:
        return str(report.path.relative_to(root))
    except ValueError:
        return str(report.path)


def init_missing_state_files(
    root: Path,
    runtime_reports: list[RuntimeReport],
    state_reports: list[StateFileReport],
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    if any(report.running for report in runtime_reports):
        errors.append("refusing --init-missing because one or more bots appear to be running")

    invalid_reports = invalid_existing_state_reports(state_reports)
    for report in invalid_reports:
        errors.append(f"refusing --init-missing because {relative_report_path(root, report)} is invalid")

    if errors:
        return [], errors

    created: list[str] = []
    for report in missing_state_reports(state_reports):
        report.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with report.path.open("x", encoding="utf-8") as handle:
                handle.write("{}\n")
        except FileExistsError:
            continue
        created.append(relative_report_path(root, report))
    return created, []


def normalize_state_files(
    root: Path,
    runtime_reports: list[RuntimeReport],
    state_reports: list[StateFileReport],
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    if any(report.running for report in runtime_reports):
        errors.append("refusing --normalize-state because one or more bots appear to be running")

    invalid_reports = invalid_existing_state_reports(state_reports)
    for report in invalid_reports:
        errors.append(f"refusing --normalize-state because {relative_report_path(root, report)} is invalid")

    if errors:
        return [], errors

    changed_paths: list[str] = []
    for report in state_reports:
        if report.kind != "open" or not report.valid or report.missing:
            continue
        try:
            payload = json.loads(report.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            continue

        if payload == {}:
            positions = {}
        elif isinstance(payload, dict):
            positions = payload.get("positions", {})
        else:
            continue
        if not isinstance(positions, dict):
            continue

        normalized_positions = {
            key: normalize_position_safety_fields(value)
            if isinstance(value, dict)
            else value
            for key, value in positions.items()
        }
        if normalized_positions == positions:
            continue

        if payload == {}:
            payload = {"positions": normalized_positions}
        else:
            payload["positions"] = normalized_positions
        report.path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        changed_paths.append(relative_report_path(root, report))
    return changed_paths, []


def state_report_for(
    state_reports: list[StateFileReport],
    broker: str,
    kind: str,
) -> StateFileReport | None:
    for report in state_reports:
        if report.broker == broker and report.kind == kind:
            return report
    return None


def build_json_payload(
    root: Path,
    overall: str,
    runtime_reports: list[RuntimeReport],
    state_reports: list[StateFileReport],
) -> dict[str, Any]:
    warnings: list[str] = []
    for report in runtime_reports:
        if report.status != "OK":
            details = []
            if report.running:
                details.append("running")
            if report.error:
                details.append(report.error)
            suffix = f" ({', '.join(details)})" if details else ""
            warnings.append(f"{report.broker} runtime status={report.status}{suffix}")

    for report in state_reports:
        if report.status != "OK" or report.error:
            try:
                rel_path = str(report.path.relative_to(root))
            except ValueError:
                rel_path = str(report.path)
            details = report.error or f"status={report.status}"
            warnings.append(f"{rel_path}: {details}")

    cleanup_items = suggested_cleanup_items(runtime_reports, state_reports)
    missing_reports = missing_state_reports(state_reports)
    normalization_items = state_normalization_items(root, state_reports)
    action_required_items = [
        {
            "broker": item["broker"],
            "position_key": item["position_key"],
            "status": item["status"],
            "reason": item["reason"],
            "command": item["command"],
        }
        for item in cleanup_items
    ]

    brokers: dict[str, Any] = {}
    for broker in BROKERS:
        open_report = state_report_for(state_reports, broker, "open")
        closed_report = state_report_for(state_reports, broker, "closed")
        open_positions = open_report.positions if open_report else {}
        brokers[broker] = {
            "open_positions_count": len(open_positions),
            "closed_positions_count": len(closed_report.positions) if closed_report else 0,
            "broker_recovered_open_count": open_report.broker_recovered if open_report else 0,
            "non_controllable_open_count": sum(
                1 for position in open_positions.values() if is_non_controllable(position)
            ),
            "missing_counts_toward_exposure_count": (
                open_report.missing_counts_toward_exposure if open_report else 0
            ),
        }

    runtime = {
        report.broker: {
            "status": report.status,
            "running": report.running,
            "heartbeat_fresh": report.heartbeat_fresh,
            "heartbeat_age_seconds": report.heartbeat_age_seconds,
            "lock_present": report.lock_present,
        }
        for report in runtime_reports
    }

    return {
        "overall_status": overall,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "brokers": brokers,
        "runtime": runtime,
        "suggested_cleanup_commands": [item["command"] for item in cleanup_items],
        "suggested_state_init_commands": (
            [suggested_state_init_command()] if missing_reports else []
        ),
        "suggested_state_normalization_commands": (
            [suggested_state_normalization_command()] if normalization_items else []
        ),
        "missing_state_files": [
            relative_report_path(root, report) for report in missing_reports
        ],
        "state_normalization_items": normalization_items,
        "warnings": warnings,
        "action_required_items": action_required_items,
    }


def print_text_report(
    root: Path,
    overall: str,
    runtime_reports: list[RuntimeReport],
    state_reports: list[StateFileReport],
) -> None:
    print(f"STATE_MAINTENANCE_PREFLIGHT overall_status={overall}")
    print("Read-only report: no state files were modified.")
    print()

    print("Runtime indicators:")
    for report in runtime_reports:
        print_runtime_report(report)
    print()

    print("State files:")
    for report in state_reports:
        print_file_report(root, report)
    print()

    print("Suggested cleanup commands:")
    cleanup_items = suggested_cleanup_items(runtime_reports, state_reports)
    for item in cleanup_items:
        print(f"- {item['broker']} {item['position_key']}: status={item['status']}")
        if item["blocked"]:
            print("  Do not run while this bot appears to be running.")
        print(f"  {item['command']}")

    if not cleanup_items:
        print("- none")

    normalization_items = state_normalization_items(root, state_reports)
    print()
    print("Suggested state normalization:")
    if normalization_items:
        print("- open position(s) missing explicit safety field(s):")
        for item in normalization_items:
            print(
                f"  - {item['broker']} {item['position_key']} "
                f"fields={item['fields'] or 'inconsistent'}"
            )
        print(f"- suggested command: {suggested_state_normalization_command()}")
        print("- only run with bots stopped; explicit counts_toward_exposure=false is preserved")
    else:
        print("- none")

    missing_reports = missing_state_reports(state_reports)
    print()
    print("Suggested state file initialization:")
    if missing_reports:
        print("- missing expected state file(s):")
        for report in missing_reports:
            print(f"  - {relative_report_path(root, report)}")
        print(f"- suggested command: {suggested_state_init_command()}")
        print("- only run with bots stopped; existing files are never overwritten")
    else:
        print("- none")

    print()
    print("No cleanup was executed.")


def status_exit_code(overall: str) -> int:
    if overall == "BLOCKED_MANUAL_REVIEW":
        return 2
    if overall in {"WARN", "ACTION_REQUIRED"}:
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only state maintenance preflight report.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--init-missing",
        action="store_true",
        help="Create missing expected state files as empty JSON objects when bots are stopped.",
    )
    parser.add_argument(
        "--normalize-state",
        action="store_true",
        help="Backfill missing explicit position safety fields when bots are stopped.",
    )
    args = parser.parse_args()

    root = root_dir()
    overall, runtime_reports, state_reports = build_report(root)
    init_result: dict[str, Any] | None = None

    if args.init_missing:
        created, errors = init_missing_state_files(root, runtime_reports, state_reports)
        init_result = {
            "attempted": True,
            "created_files": created,
            "errors": errors,
            "blocked": bool(errors),
        }
        if not errors:
            overall, runtime_reports, state_reports = build_report(root)

    normalize_result: dict[str, Any] | None = None
    if args.normalize_state:
        changed, errors = normalize_state_files(root, runtime_reports, state_reports)
        normalize_result = {
            "attempted": True,
            "changed_files": changed,
            "errors": errors,
            "blocked": bool(errors),
        }
        if not errors:
            overall, runtime_reports, state_reports = build_report(root)

    if args.json:
        payload = build_json_payload(root, overall, runtime_reports, state_reports)
        if init_result is not None:
            payload["init_missing"] = init_result
        if normalize_result is not None:
            payload["normalize_state"] = normalize_result
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print_text_report(root, overall, runtime_reports, state_reports)
        if init_result is not None:
            print()
            print("Missing state initialization:")
            if init_result["errors"]:
                print("  blocked=true")
                for error in init_result["errors"]:
                    print(f"  error={error}")
            elif init_result["created_files"]:
                print("  created_files:")
                for path in init_result["created_files"]:
                    print(f"    - {path}")
            else:
                print("  created_files: none")
        if normalize_result is not None:
            print()
            print("State normalization:")
            if normalize_result["errors"]:
                print("  blocked=true")
                for error in normalize_result["errors"]:
                    print(f"  error={error}")
            elif normalize_result["changed_files"]:
                print("  changed_files:")
                for path in normalize_result["changed_files"]:
                    print(f"    - {path}")
            else:
                print("  changed_files: none")

    if init_result and init_result["errors"]:
        return 2
    if normalize_result and normalize_result["errors"]:
        return 2
    return status_exit_code(overall)


if __name__ == "__main__":
    sys.exit(main())
