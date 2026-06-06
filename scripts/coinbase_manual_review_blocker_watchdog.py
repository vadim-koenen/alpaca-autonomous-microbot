#!/usr/bin/env python3
"""Offline manual-review blocker detection and guarded local-state cleanup."""

from __future__ import annotations

import argparse
import copy
import csv
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


SCHEMA_VERSION = "1.0"
REPORT_CLASS = "manual_review_blocker_watchdog"
MANUAL_REVIEW_TOKENS = (
    "manual_review_position_open",
    "broker_close_capability_unconfirmed",
    "manual review",
)
RECOVERY_TOKENS = ("broker_recovered", "journal_reassociated", "journal_reassociated_order")
AUTHORIZATION_DEFAULTS = {
    "implementation_authorized": False,
    "strategy_change_authorized": False,
    "live_trading_unblock_authorized": False,
    "state_mutation_authorized": False,
    "broker_order_authorized": False,
    "paper_probe_authorized": False,
    "live_probe_authorized": False,
    "scaling_authorized": False,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def normalize_symbol(value: Any) -> str:
    text = str(value or "").strip().upper().replace("-", "/")
    if "/" not in text and text.endswith("USD") and len(text) > 3:
        text = f"{text[:-3]}/USD"
    return text


def safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "unknown"


def read_json(path: Path, default: Any) -> Tuple[Any, Optional[str]]:
    if not path.exists():
        return copy.deepcopy(default), "missing"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as exc:
        return copy.deepcopy(default), f"malformed: {exc}"


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, default=str)
            handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def extract_positions(payload: Any) -> Tuple[Dict[str, Dict[str, Any]], str]:
    if not isinstance(payload, dict):
        return {}, "invalid"
    if isinstance(payload.get("positions"), dict):
        return {
            str(key): value
            for key, value in payload["positions"].items()
            if isinstance(value, dict)
        }, "positions"
    return {
        str(key): value for key, value in payload.items() if isinstance(value, dict)
    }, "direct"


def replace_positions(
    payload: Dict[str, Any],
    positions: Dict[str, Dict[str, Any]],
    shape: str,
    now: datetime,
) -> Dict[str, Any]:
    if shape == "positions":
        result = copy.deepcopy(payload)
        result["positions"] = positions
        result["saved_at"] = iso_time(now)
        return result
    return copy.deepcopy(positions)


def position_symbol(key: str, position: Dict[str, Any]) -> str:
    return normalize_symbol(position.get("symbol") or position.get("product_id") or key)


def manual_review_reason(position: Dict[str, Any]) -> str:
    return str(
        position.get("manual_review_reason")
        or position.get("original_manual_review_reason")
        or position.get("reason")
        or ""
    ).strip()


def is_external_inventory(position: Dict[str, Any]) -> bool:
    classification = str(position.get("external_inventory_classification") or "").lower()
    return bool(
        position.get("staked_external_position") is True
        or position.get("external_staked_position") is True
        or "external_staked" in classification
        or (
            position.get("bot_inventory") is False
            and position.get("tradable_by_bot") is False
        )
    )


def is_manual_review_blocker(position: Dict[str, Any]) -> bool:
    reason = manual_review_reason(position).lower()
    recovery = str(position.get("recovery_source") or "").lower()
    evidence = bool(
        position.get("user_action_required") is True
        or position.get("api_controllable") is False
        or position.get("exit_evaluation_enabled") is False
        or any(token in reason for token in MANUAL_REVIEW_TOKENS)
        or any(token in recovery for token in RECOVERY_TOKENS)
    )
    return evidence and not is_external_inventory(position)


def position_time(position: Dict[str, Any]) -> Optional[datetime]:
    for key in (
        "manual_review_started_at",
        "reassociated_at",
        "entry_time",
        "opened_at",
        "timestamp",
        "created_at",
    ):
        parsed = parse_time(position.get(key))
        if parsed is not None:
            return parsed
    return None


def read_journal(path: Path) -> Tuple[List[Dict[str, str]], Optional[str]]:
    if not path.exists():
        return [], "missing"
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return [
                {
                    str(key or "").strip().lower().replace(" ", "_"): str(value or "").strip()
                    for key, value in row.items()
                }
                for row in csv.DictReader(handle)
            ], None
    except (OSError, csv.Error) as exc:
        return [], f"malformed: {exc}"


def row_text(row: Dict[str, str]) -> str:
    return " | ".join(str(value) for value in row.values()).lower()


def row_time(row: Dict[str, str]) -> Optional[datetime]:
    for key in ("timestamp", "time", "datetime", "created_at", "ts"):
        parsed = parse_time(row.get(key))
        if parsed is not None:
            return parsed
    return None


def row_symbol(row: Dict[str, str]) -> str:
    for key in ("symbol", "product_id", "product", "pair"):
        if row.get(key):
            return normalize_symbol(row[key])
    return ""


def summarize_journal(rows: Iterable[Dict[str, str]]) -> Dict[str, Any]:
    blocked: List[Dict[str, Any]] = []
    fills: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    reassociations: List[Dict[str, Any]] = []
    for row in rows:
        text = row_text(row)
        event = {"timestamp": row_time(row), "symbol": row_symbol(row), "text": text}
        if "entry_blocked" in text and any(token in text for token in MANUAL_REVIEW_TOKENS):
            blocked.append(event)
        if any(token in text for token in ("filled", "entry_filled", "buy_filled")):
            fills.append(event)
        if "close" in text and any(token in text for token in ("failed", "failure", "error")):
            failures.append(event)
        if any(token in text for token in ("re-associated", "reassociated", "journal_reassociated")):
            reassociations.append(event)

    def latest(events: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        timed = [event for event in events if event["timestamp"] is not None]
        if not timed:
            return None
        item = max(timed, key=lambda event: event["timestamp"])
        return {
            "timestamp": iso_time(item["timestamp"]),
            "symbol": item["symbol"] or None,
        }

    return {
        "recent_entry_blocked_count": len(blocked),
        "last_entry_or_fill_event": latest(fills),
        "last_close_failure": latest(failures),
        "last_broker_reassociated_warning": latest(reassociations),
        "first_blocked_at": (
            iso_time(min(event["timestamp"] for event in blocked if event["timestamp"] is not None))
            if any(event["timestamp"] is not None for event in blocked)
            else None
        ),
    }


def parse_process_snapshot(path: Optional[Path]) -> Tuple[List[int], Optional[str]]:
    if path is None:
        return [], "not_supplied"
    if not path.exists():
        return [], "missing"
    pids: List[int] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if "main.py" not in line or "--mode live" not in line:
                continue
            match = re.search(r"\b(\d{2,})\b", line)
            if match:
                pids.append(int(match.group(1)))
    except OSError as exc:
        return [], str(exc)
    return sorted(set(pids)), None


def read_lock_pid(path: Path) -> Optional[int]:
    if not path.exists():
        return None
    try:
        match = re.search(r"\d+", path.read_text(encoding="utf-8"))
    except OSError:
        return None
    return int(match.group(0)) if match else None


def pid_is_alive(pid: Optional[int], alive_pids: Optional[set[int]] = None) -> bool:
    if not pid:
        return False
    if alive_pids is not None:
        return pid in alive_pids
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def resolve_paths(args: argparse.Namespace) -> Dict[str, Path]:
    root = Path(args.repo_root).resolve()
    return {
        "root": root,
        "journal": Path(args.journal).resolve() if args.journal else root / "journal_coinbase_crypto.csv",
        "open_positions": (
            Path(args.open_positions).resolve()
            if args.open_positions
            else root / "state" / "coinbase" / "open_positions.json"
        ),
        "external_inventory": (
            Path(args.external_inventory).resolve()
            if args.external_inventory
            else root / "state" / "coinbase" / "external_inventory.json"
        ),
        "closed_positions": (
            Path(args.closed_positions).resolve()
            if args.closed_positions
            else root / "state" / "coinbase" / "closed_positions.json"
        ),
        "lock": root / "runtime" / "coinbase.lock",
        "stop": root / "runtime" / "STOP_TRADING",
        "backup_dir": root / "state" / "coinbase" / "backups",
        "audit_dir": root / "reports" / "blocker_remediation",
    }


def build_report(
    *,
    paths: Dict[str, Path],
    process_snapshot: Optional[Path] = None,
    now: Optional[datetime] = None,
    alive_pids: Optional[set[int]] = None,
) -> Dict[str, Any]:
    now = now or utc_now()
    open_payload, open_error = read_json(paths["open_positions"], {"positions": {}})
    external_payload, external_error = read_json(paths["external_inventory"], {})
    closed_payload, closed_error = read_json(paths["closed_positions"], {"positions": {}})
    journal_rows, journal_error = read_journal(paths["journal"])
    positions, _ = extract_positions(open_payload)
    external_positions, _ = extract_positions(
        external_payload.get("external_inventory", external_payload)
        if isinstance(external_payload, dict)
        else {}
    )
    blockers = [
        {
            "key": key,
            "symbol": position_symbol(key, position),
            "reason": manual_review_reason(position) or "manual_review_state_evidence",
            "started_at": iso_time(position_time(position)) if position_time(position) else None,
            "api_controllable": position.get("api_controllable"),
            "exit_evaluation_enabled": position.get("exit_evaluation_enabled"),
            "user_action_required": position.get("user_action_required"),
            "recovery_source": position.get("recovery_source"),
        }
        for key, position in positions.items()
        if is_manual_review_blocker(position)
    ]
    external_blockers = [
        position_symbol(key, position)
        for key, position in external_positions.items()
        if is_external_inventory(position)
        and (
            position.get("user_action_required") is True
            or position.get("api_controllable") is False
            or position.get("exit_evaluation_enabled") is False
            or manual_review_reason(position)
        )
    ]
    journal = summarize_journal(journal_rows)
    blocker_times = [
        parse_time(blocker["started_at"]) for blocker in blockers if blocker.get("started_at")
    ]
    first_blocked = parse_time(journal["first_blocked_at"])
    if first_blocked is not None:
        blocker_times.append(first_blocked)
    oldest = min((item for item in blocker_times if item is not None), default=None)
    age_hours = round(max(0.0, (now - oldest).total_seconds() / 3600), 3) if oldest else None

    process_pids, process_error = parse_process_snapshot(process_snapshot)
    lock_pid = read_lock_pid(paths["lock"])
    lock_active = pid_is_alive(lock_pid, alive_pids)
    running_pids = sorted(set(process_pids + ([lock_pid] if lock_active and lock_pid else [])))
    duplicate_risk = len(running_pids) > 1
    bot_running = bool(running_pids)
    stop_present = paths["stop"].exists()
    stop_not_verified = bool(stop_present and bot_running)
    blockers_detected = bool(blockers or journal["recent_entry_blocked_count"])

    alerts: List[str] = []
    if age_hours is not None and age_hours >= 0.5:
        alerts.append("manual_review_blocker_older_than_30_minutes")
    if age_hours is not None and age_hours >= 2:
        alerts.append("blocked_duration_exceeds_2_hours")
    if age_hours is not None and age_hours >= 24:
        alerts.append("blocked_duration_exceeds_24_hours")
    if duplicate_risk:
        alerts.append("duplicate_live_process_risk")
    if blockers_detected and bot_running:
        alerts.append("bot_blocked_but_still_running")
    if stop_not_verified:
        alerts.append("stop_all_did_not_stop_processes")

    if age_hours is not None and age_hours >= 24 or duplicate_risk or stop_not_verified:
        severity = "CRITICAL"
    elif blockers_detected and (age_hours is not None and age_hours >= 2 or bot_running):
        severity = "BLOCKED"
    elif blockers_detected:
        severity = "WARN"
    else:
        severity = "OK"

    if not blockers_detected:
        recommended = "No manual-review blocker detected. Continue normal offline monitoring."
    elif bot_running:
        recommended = (
            "Activate and retain STOP_TRADING, then use scripts/stop_all_verified.sh "
            "and verify every reported live PID has exited before any local cleanup."
        )
    else:
        recommended = (
            "Reconcile broker holdings and open orders through a separately approved read-only process. "
            "Only after explicit operator confirmation, use the guarded local-state clear mode."
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": iso_time(now),
        "report_class": REPORT_CLASS,
        "blockers_detected": blockers_detected,
        "active_blocker_count": len(blockers),
        "primary_blocker_symbol": blockers[0]["symbol"] if blockers else None,
        "blocker_age_hours": age_hours,
        "estimated_blocked_duration_hours": age_hours,
        "recent_entry_blocked_count": journal["recent_entry_blocked_count"],
        "missed_scan_cycles_due_to_blocker": journal["recent_entry_blocked_count"],
        "manual_review_blockers": blockers,
        "external_inventory_blocker_symbols": sorted(set(external_blockers)),
        "last_entry_or_fill_event": journal["last_entry_or_fill_event"],
        "last_close_failure": journal["last_close_failure"],
        "last_broker_reassociated_warning": journal["last_broker_reassociated_warning"],
        "live_process_pids": running_pids,
        "live_process_count": len(running_pids),
        "process_snapshot_status": process_error or "loaded",
        "duplicate_live_process_risk": duplicate_risk,
        "runtime_lock_pid": lock_pid,
        "runtime_lock_active": lock_active,
        "kill_switch_present": stop_present,
        "bot_blocked_but_still_running": blockers_detected and bot_running,
        "stop_verification_failed": stop_not_verified,
        "safe_to_clear_local_state": False,
        "broker_reconciliation_required": blockers_detected,
        "operator_attention_required": blockers_detected,
        "alert_severity": severity,
        "alert_flags": alerts,
        "recommended_action": recommended,
        "input_status": {
            "journal": journal_error or "loaded",
            "open_positions": open_error or "loaded",
            "external_inventory": external_error or "loaded",
            "closed_positions": closed_error or "loaded",
        },
        **AUTHORIZATION_DEFAULTS,
    }


def remediation_plan(report: Dict[str, Any], paths: Dict[str, Path]) -> List[str]:
    symbol = report.get("primary_blocker_symbol") or "ADA/USD"
    return [
        f"touch {paths['stop']}",
        "bash scripts/stop_all_verified.sh --wait-seconds 90",
        "Verify no Coinbase holdings or open orders for the symbol through a separately approved read-only check.",
        (
            "python3 scripts/coinbase_manual_review_blocker_watchdog.py "
            f"--repo-root {paths['root']} --process-snapshot /path/to/verified_process_snapshot.txt "
            f"--clear-local-stale-blocker --symbol {symbol} "
            '--operator-confirmed-no-broker-position --reason "operator verified no broker position or open order"'
        ),
    ]


def clear_local_stale_blocker(
    *,
    paths: Dict[str, Path],
    symbol: str,
    reason: str,
    operator_confirmed: bool,
    process_snapshot: Optional[Path],
    now: Optional[datetime] = None,
    alive_pids: Optional[set[int]] = None,
) -> Dict[str, Any]:
    now = now or utc_now()
    normalized_symbol = normalize_symbol(symbol)
    report = build_report(
        paths=paths,
        process_snapshot=process_snapshot,
        now=now,
        alive_pids=alive_pids,
    )
    refusal_reasons: List[str] = []
    if not paths["stop"].exists():
        refusal_reasons.append("stop_trading_kill_switch_required")
    if process_snapshot is None:
        refusal_reasons.append("verified_process_snapshot_required")
    if report["live_process_pids"]:
        refusal_reasons.append("live_bot_process_still_running")
    if report["duplicate_live_process_risk"]:
        refusal_reasons.append("duplicate_live_process_risk")
    if report["runtime_lock_active"]:
        refusal_reasons.append("runtime_lock_pid_still_active")
    if not operator_confirmed:
        refusal_reasons.append("operator_confirmation_required")
    if not reason.strip():
        refusal_reasons.append("nonempty_reason_required")

    open_payload, open_error = read_json(paths["open_positions"], {"positions": {}})
    if open_error:
        refusal_reasons.append(f"open_positions_{open_error}")
    positions, shape = extract_positions(open_payload)
    matching = [
        (key, position)
        for key, position in positions.items()
        if position_symbol(key, position) == normalized_symbol and is_manual_review_blocker(position)
    ]
    if len(matching) != 1:
        refusal_reasons.append("exactly_one_matching_manual_review_position_required")

    result = {
        **report,
        "remediation_requested": True,
        "remediation_symbol": normalized_symbol,
        "remediation_performed": False,
        "refusal_reasons": refusal_reasons,
    }
    if refusal_reasons:
        result["recommended_action"] = "Local-state cleanup refused. Resolve every refusal reason first."
        return result

    key, removed = matching[0]
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    backup_path = paths["backup_dir"] / f"open_positions_manual_review_clear_{stamp}.json"
    audit_path = paths["audit_dir"] / f"{stamp}_{safe_slug(normalized_symbol)}.json"
    atomic_write_json(
        backup_path,
        {
            "created_at_utc": iso_time(now),
            "source_path": str(paths["open_positions"]),
            "reason": "pre_remediation_backup",
            "payload": open_payload,
        },
    )

    positions_after = copy.deepcopy(positions)
    positions_after.pop(key)
    open_after = replace_positions(open_payload, positions_after, shape, now)
    closed_payload, _ = read_json(
        paths["closed_positions"],
        {
            "description": "Archive of positions removed after explicit operator review.",
            "state_namespace": "coinbase",
            "positions": {},
        },
    )
    if not isinstance(closed_payload, dict):
        closed_payload = {"state_namespace": "coinbase", "positions": {}}
    closed_positions = closed_payload.setdefault("positions", {})
    if not isinstance(closed_positions, dict):
        result["refusal_reasons"] = ["closed_positions_shape_invalid"]
        result["recommended_action"] = "Local-state cleanup refused. Repair closed_positions shape."
        return result
    archive_key = f"{key}_manual_review_clear_{stamp}"
    archived = copy.deepcopy(removed)
    archived.update(
        {
            "position_key": key,
            "status": "manually_cleared_local_stale_blocker",
            "cleared_at_utc": iso_time(now),
            "cleared_reason": reason.strip(),
            "operator_confirmed_no_broker_position": True,
            "broker_truth_claimed": False,
        }
    )
    closed_positions[archive_key] = archived
    closed_payload["saved_at"] = iso_time(now)

    atomic_write_json(paths["closed_positions"], closed_payload)
    atomic_write_json(paths["open_positions"], open_after)
    audit = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": iso_time(now),
        "action": "clear_local_stale_manual_review_blocker",
        "symbol": normalized_symbol,
        "reason": reason.strip(),
        "operator_confirmed_no_broker_position": True,
        "broker_reconciliation_source": "explicit_operator_assertion_only",
        "broker_calls_made": False,
        "broker_truth_claimed": False,
        "backup_path": str(backup_path),
        "state_files_changed": [
            str(paths["open_positions"]),
            str(paths["closed_positions"]),
        ],
        "unrelated_symbols_preserved": sorted(
            position_symbol(other_key, other)
            for other_key, other in positions_after.items()
        ),
    }
    atomic_write_json(audit_path, audit)

    result.update(
        {
            "remediation_performed": True,
            "safe_to_clear_local_state": True,
            "state_mutation_authorized": True,
            "backup_path": str(backup_path),
            "audit_path": str(audit_path),
            "cleared_position_key": key,
            "recommended_action": "Review backup and audit record. Do not restart or unblock trading without separate approval.",
            "refusal_reasons": [],
        }
    )
    return result


def render_text(report: Dict[str, Any]) -> str:
    lines = [
        "P2-029B Manual-Review Blocker Watchdog",
        f"severity={report['alert_severity']}",
        f"blockers_detected={str(report['blockers_detected']).lower()}",
        f"active_blocker_count={report['active_blocker_count']}",
        f"primary_blocker_symbol={report['primary_blocker_symbol']}",
        f"blocker_age_hours={report['blocker_age_hours']}",
        f"recent_entry_blocked_count={report['recent_entry_blocked_count']}",
        f"live_process_pids={report['live_process_pids']}",
        f"duplicate_live_process_risk={str(report['duplicate_live_process_risk']).lower()}",
        f"runtime_lock_active={str(report['runtime_lock_active']).lower()}",
        f"kill_switch_present={str(report['kill_switch_present']).lower()}",
        f"safe_to_clear_local_state={str(report['safe_to_clear_local_state']).lower()}",
        f"broker_reconciliation_required={str(report['broker_reconciliation_required']).lower()}",
        f"recommended_action={report['recommended_action']}",
    ]
    if report.get("remediation_plan"):
        lines.append("remediation_plan:")
        lines.extend(f"  {index}. {step}" for index, step in enumerate(report["remediation_plan"], 1))
    if report.get("refusal_reasons"):
        lines.append(f"refusal_reasons={report['refusal_reasons']}")
    return "\n".join(lines)


def parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[1]
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--repo-root", default=str(root))
    result.add_argument("--journal")
    result.add_argument("--open-positions")
    result.add_argument("--external-inventory")
    result.add_argument("--closed-positions")
    result.add_argument("--process-snapshot")
    result.add_argument("--now", help="ISO-8601 timestamp for deterministic offline verification")
    result.add_argument("--json", action="store_true")
    result.add_argument("--strict-exit-code", action="store_true")
    result.add_argument("--plan-remediation", action="store_true")
    result.add_argument("--clear-local-stale-blocker", action="store_true")
    result.add_argument("--symbol")
    result.add_argument("--operator-confirmed-no-broker-position", action="store_true")
    result.add_argument("--reason", default="")
    result.add_argument(
        "--broker-read-only-reconcile",
        action="store_true",
        help="Reserved for P2-029C; reports unavailable and performs no broker action.",
    )
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parser().parse_args(argv)
    paths = resolve_paths(args)
    now = parse_time(args.now) if args.now else utc_now()
    snapshot = Path(args.process_snapshot).resolve() if args.process_snapshot else None

    if args.broker_read_only_reconcile:
        report = build_report(paths=paths, process_snapshot=snapshot, now=now)
        report["broker_read_only_reconcile_status"] = "NOT_IMPLEMENTED_P2_029C_REQUIRED"
        report["recommended_action"] = (
            "Do not call broker services from this patch. Implement and review a separate read-only reconciler in P2-029C."
        )
    elif args.clear_local_stale_blocker:
        if not args.symbol:
            raise SystemExit("--symbol is required with --clear-local-stale-blocker")
        report = clear_local_stale_blocker(
            paths=paths,
            symbol=args.symbol,
            reason=args.reason,
            operator_confirmed=args.operator_confirmed_no_broker_position,
            process_snapshot=snapshot,
            now=now,
        )
    else:
        report = build_report(paths=paths, process_snapshot=snapshot, now=now)

    if args.plan_remediation:
        report["remediation_plan"] = remediation_plan(report, paths)

    print(json.dumps(report, indent=2, sort_keys=True) if args.json else render_text(report))
    if args.strict_exit_code and report["alert_severity"] in {"BLOCKED", "CRITICAL"}:
        return 2
    if args.clear_local_stale_blocker and not report.get("remediation_performed"):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
