#!/usr/bin/env python3
"""Offline dead-man and blocker watchdog with optional local file alerts."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

try:
    from scripts.bot_alerts import alert as write_alert
    from scripts.coinbase_manual_review_blocker_watchdog import (
        build_report as build_blocker_report,
        parse_process_snapshot,
        parse_time,
        pid_is_alive,
        read_json,
        read_lock_pid,
        resolve_paths as resolve_blocker_paths,
    )
except ModuleNotFoundError:
    from bot_alerts import alert as write_alert
    from coinbase_manual_review_blocker_watchdog import (
        build_report as build_blocker_report,
        parse_process_snapshot,
        parse_time,
        pid_is_alive,
        read_json,
        read_lock_pid,
        resolve_paths as resolve_blocker_paths,
    )


SCHEMA_VERSION = "1.0"


def _age_minutes(value: Any, now: datetime) -> Optional[float]:
    parsed = parse_time(value)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds() / 60)


def _event(level: str, code: str, message: str, context: Dict[str, Any]) -> Dict[str, Any]:
    return {"level": level, "code": code, "message": message, "context": context}


def build_report(
    *,
    repo_root: Path,
    process_snapshot: Optional[Path] = None,
    now: Optional[datetime] = None,
    alive_pids: Optional[set[int]] = None,
    emit_alerts: bool = False,
    reports_root: Optional[Path] = None,
    alert_writer: Callable[..., Dict[str, Any]] = write_alert,
    reconciler_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    args = argparse.Namespace(
        repo_root=str(repo_root),
        journal=None,
        open_positions=None,
        external_inventory=None,
        closed_positions=None,
    )
    paths = resolve_blocker_paths(args)
    blocker = build_blocker_report(
        paths=paths,
        process_snapshot=process_snapshot,
        now=now,
        alive_pids=alive_pids,
    )
    heartbeat_path = repo_root / "runtime" / "coinbase_heartbeat.json"
    heartbeat, heartbeat_error = read_json(heartbeat_path, {})
    heartbeat_age = _age_minutes(heartbeat.get("last_loop_time"), now)
    heartbeat_fresh = heartbeat_age is not None and heartbeat_age <= 10
    last_exit_age = _age_minutes(heartbeat.get("last_exit_at"), now)
    no_round_trip_24h = last_exit_age is None or last_exit_age > 24 * 60
    process_pids, _ = parse_process_snapshot(process_snapshot)
    live_process_running = bool(process_pids)
    lock_pid = read_lock_pid(paths["lock"])
    lock_active = pid_is_alive(lock_pid, alive_pids)
    stale_lock = paths["lock"].exists() and not lock_active
    valid_lock = lock_active and (not process_pids or lock_pid in process_pids)

    state_path = repo_root / "runtime" / "watchdog_state.json"
    watchdog_state = {}
    if state_path.exists():
        try:
            watchdog_state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    current_time = heartbeat.get("last_loop_time")
    current_count = heartbeat.get("loop_count")
    loop_not_advancing_alert = False
    if current_time and current_count is not None:
        prev_time = watchdog_state.get("last_loop_time")
        prev_count = watchdog_state.get("loop_count")
        if prev_time and prev_time != current_time and prev_count == current_count:
            loop_not_advancing_alert = True
        
        # Write back updated state only if no heartbeat error
        if not heartbeat_error:
            try:
                state_path.parent.mkdir(parents=True, exist_ok=True)
                state_path.write_text(json.dumps({
                    "last_loop_time": current_time,
                    "loop_count": current_count,
                    "updated_at": now.isoformat(),
                }, indent=2), encoding="utf-8")
            except Exception:
                pass

    lock_file_exists = paths["lock"].exists()
    lock_pid_missing = lock_file_exists and lock_pid is None
    lock_owner_mismatch = bool(lock_pid is not None and process_pids and lock_pid not in process_pids)

    # Reconciler hygiene: determine if we are clean enough to downgrade stale artifacts
    local_open_positions = set()
    broker_open_orders = []
    reconciler_clean = False
    if reconciler_report:
        local_open_positions = set(reconciler_report.get("local_open_positions", []))
        broker_open_orders = reconciler_report.get("broker_open_orders", [])
        
        # Clean requires:
        # 1. Broker query succeeded
        # 2. No reconciler reasons (which covers many things)
        # 3. Local heartbeat is fresh (calculated in this run)
        # 4. Lock health is OK (calculated in this run)
        # 5. File alerting was active in the reconciler's source report
        # 6. No local open positions
        # 7. No broker open orders
        # 8. No STOP_TRADING present
        reconciler_clean = (
            reconciler_report.get("broker_query_succeeded") is True
            and not reconciler_report.get("reasons")
            and heartbeat_fresh
            and (valid_lock or not live_process_running)
            and reconciler_report.get("heartbeat", {}).get("file_alerting_active") is True
            and not local_open_positions
            and not broker_open_orders
            and not reconciler_report.get("stop_trading_present")
        )

    events: List[Dict[str, Any]] = []
    if loop_not_advancing_alert:
        events.append(_event(
            "CRITICAL",
            "loop_not_advancing",
            "Trading loop is not advancing while heartbeat timestamp is updated.",
            {"last_loop_time": current_time, "loop_count": current_count}
        ))
    api_errors = heartbeat.get("api_errors_this_session", 0)
    if api_errors >= 5:
        events.append(_event(
            "HIGH",
            "repeated_errors_detected",
            f"API error count in session has crossed threshold: {api_errors}.",
            {"api_errors_this_session": api_errors, "last_error": heartbeat.get("last_error")}
        ))
    if lock_pid_missing:
        events.append(_event(
            "HIGH",
            "lock_pid_missing",
            "Lock file exists but does not contain a valid PID.",
            {"lock_path": str(paths["lock"])}
        ))
    if lock_owner_mismatch:
        events.append(_event(
            "CRITICAL",
            "lock_owner_mismatch",
            "Lock PID mismatch: lock PID does not match the running process PID.",
            {"lock_pid": lock_pid, "running_pids": process_pids}
        ))
    if blocker["duplicate_live_process_risk"]:
        events.append(_event(
            "CRITICAL",
            "duplicate_live_process",
            "More than one live Coinbase bot process is present.",
            {"pids": blocker["live_process_pids"]},
        ))
    if blocker["last_close_failure"]:
        failure = blocker["last_close_failure"]
        failure_symbol = failure.get("symbol")
        # Active if reconciler not clean OR symbol still in local open OR open broker orders
        failure_active = (
            not reconciler_clean
            or failure_symbol in local_open_positions
            or any(str(o.get("symbol")).upper() == str(failure_symbol).upper() for o in broker_open_orders)
        )
        events.append(_event(
            "CRITICAL" if failure_active else "INFO",
            "failed_close",
            "A failed close warning exists in the Coinbase journal.",
            failure,
        ))
    age_hours = blocker.get("blocker_age_hours")
    if age_hours is not None and age_hours >= 0.5:
        primary_symbol = blocker.get("primary_blocker_symbol")
        # Active if reconciler not clean OR primary symbol still in local open
        blocker_active = (
            not reconciler_clean
            or (primary_symbol and primary_symbol in local_open_positions)
        )
        events.append(_event(
            "CRITICAL" if blocker_active else "INFO",
            "manual_review_blocker",
            "Manual-review blocker has exceeded 30 minutes.",
            {"symbol": primary_symbol, "age_hours": age_hours},
        ))
    elif age_hours is not None and age_hours >= 0.25:
        events.append(_event(
            "HIGH",
            "entry_blocked_over_15_minutes",
            "Entry blocking has exceeded 15 minutes.",
            {"symbol": blocker["primary_blocker_symbol"], "age_hours": age_hours},
        ))
    if not heartbeat_fresh:
        events.append(_event(
            "CRITICAL",
            "heartbeat_stale",
            "Coinbase heartbeat is missing or older than 10 minutes.",
            {"heartbeat_age_minutes": heartbeat_age, "input_status": heartbeat_error or "loaded"},
        ))
    if no_round_trip_24h:
        level = "MEDIUM"
        if reconciler_clean and heartbeat.get("trades_today", 0) == 0:
            level = "INFO"
        events.append(_event(
            level,
            "no_round_trip_24h",
            "No completed round-trip exit is visible in the last 24 hours.",
            {"last_exit_age_minutes": last_exit_age},
        ))
    if blocker["kill_switch_present"] and live_process_running:
        events.append(_event(
            "CRITICAL",
            "stop_trading_process_still_running",
            "STOP_TRADING exists while a live process remains.",
            {"pids": process_pids},
        ))
    if live_process_running and (not valid_lock or not heartbeat_fresh):
        events.append(_event(
            "CRITICAL",
            "live_process_without_valid_lock_or_heartbeat",
            "Live process lacks a valid lock or fresh heartbeat.",
            {"pids": process_pids, "valid_lock": valid_lock, "heartbeat_fresh": heartbeat_fresh},
        ))
    if stale_lock:
        events.append(_event(
            "HIGH",
            "stale_runtime_lock",
            "Runtime lock exists but its PID is not alive.",
            {"lock_pid": lock_pid},
        ))

    emitted: List[Dict[str, Any]] = []
    if emit_alerts:
        for item in events:
            emitted.append(alert_writer(
                item["level"],
                item["message"],
                {"code": item["code"], **item["context"]},
                reports_root=reports_root,
                now=now,
            ))
        emitted.append(alert_writer(
            "INFO",
            "Coinbase heartbeat watchdog check completed.",
            {"event_count": len(events), "heartbeat_fresh": heartbeat_fresh},
            reports_root=reports_root,
            now=now,
        ))

    severity_order = {"INFO": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    highest = max((item["level"] for item in events), key=severity_order.get, default="INFO")
    file_alerting_active = bool(emit_alerts and emitted and all(
        item.get("file_alert_written") for item in emitted
    ))
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "report_class": "bot_heartbeat_watchdog",
        "highest_alert_level": highest,
        "heartbeat_present": heartbeat_path.exists(),
        "heartbeat_fresh": heartbeat_fresh,
        "heartbeat_age_minutes": heartbeat_age,
        "manual_review_blocker_age_hours": age_hours,
        "duplicate_live_process_risk": blocker["duplicate_live_process_risk"],
        "live_process_pids": blocker["live_process_pids"],
        "runtime_lock_pid": lock_pid,
        "runtime_lock_active": lock_active,
        "lock_health": "OK" if valid_lock or not live_process_running else "INVALID",
        "stale_runtime_lock": stale_lock,
        "lock_pid_missing": lock_pid_missing,
        "lock_owner_mismatch": lock_owner_mismatch,
        "loop_not_advancing_alert": loop_not_advancing_alert,
        "api_errors_this_session": api_errors,
        "no_completed_round_trip_24h": no_round_trip_24h,
        "failed_close_warning": blocker["last_close_failure"],
        "kill_switch_present_while_running": blocker["kill_switch_present"] and live_process_running,
        "live_process_without_valid_lock_or_heartbeat": (
            live_process_running and (not valid_lock or not heartbeat_fresh)
        ),
        "events": events,
        "alerts_emitted": len(emitted),
        "file_alerting_configured": True,
        "file_alerting_active": file_alerting_active,
        "email_status": "email_not_configured",
        "read_only_default": not emit_alerts,
        "process_kill_performed": False,
        "restart_performed": False,
        "state_mutation_performed": False,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--process-snapshot", type=Path)
    parser.add_argument("--now")
    parser.add_argument("--emit-alerts", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--reconciler-report", type=Path, help="Path to JSON reconciler report")
    args = parser.parse_args(argv)
    now = parse_time(args.now) if args.now else datetime.now(timezone.utc)

    reconciler_report = None
    if args.reconciler_report:
        reconciler_report, err = read_json(args.reconciler_report, None)
        if err:
            # If we fail to read it, we treat it as None (not clean)
            reconciler_report = None

    report = build_report(
        repo_root=args.repo_root.resolve(),
        process_snapshot=args.process_snapshot.resolve() if args.process_snapshot else None,
        now=now,
        emit_alerts=args.emit_alerts,
        reconciler_report=reconciler_report,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"highest_alert_level={report['highest_alert_level']}")
        print(f"heartbeat_fresh={str(report['heartbeat_fresh']).lower()}")
        print(f"duplicate_live_process_risk={str(report['duplicate_live_process_risk']).lower()}")
        print(f"lock_health={report['lock_health']}")
        print(f"events={len(report['events'])}")
        print(f"file_alerting_active={str(report['file_alerting_active']).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
