#!/usr/bin/env python3
"""
P2-021C - Offline human-approved Coinbase evidence capture checklist.

This script does not capture broker data. It reads an offline JSON request and
prints the exact human approval gates, required direct broker facts, and future
read-only method calls needed before captured payloads can be adapted by the
P2-021B adapter and resolved by the P2-021A profit evidence resolver.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


READY = "READY_FOR_HUMAN_APPROVED_READ_ONLY_CAPTURE"
BLOCKED = "BLOCKED"
ADAPTER_INPUT_PATH = "/tmp/coinbase_read_only_evidence_capture_payload.json"
ADAPTER_COMMAND = (
    "python3 scripts/coinbase_broker_evidence_adapter.py "
    f"--source-json {ADAPTER_INPUT_PATH} --json"
)
RESOLVER_COMMAND = (
    "python3 scripts/coinbase_profit_readout_evidence_resolver.py "
    f"--probe-json {ADAPTER_INPUT_PATH} --json"
)
REQUIRED_FIELDS = [
    "order_id",
    "trade_or_fill_id",
    "side",
    "product_id",
    "size",
    "price",
    "timestamp",
    "fee_or_commission",
    "filled_value_or_proceeds",
]
REDACTION_REQUIREMENTS = [
    "Remove API keys, passphrases, secrets, account IDs, and raw auth headers.",
    "Do not include .env contents or credential presence probes.",
    "Keep order_id, trade/fill_id, product_id, side, size, price, timestamp, fee/commission, and filled_value/proceeds.",
    "Save only sanitized JSON intended for offline adapter input.",
]
APPROVAL_CHECKLIST = [
    "Human explicitly approves a one-time read-only Coinbase evidence capture.",
    "Capture is limited to listed order IDs, product IDs, and date windows.",
    "No order, cancel, close, modify, risk, config, runtime, background, state, or log mutation is permitted.",
    "No secrets or .env contents may be printed, copied, committed, or stored in the capture file.",
    "Captured payload must be redacted before running the offline adapter.",
]


def _safe_load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_load_error": str(exc)}


def _as_list(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def _order_ids(cycle: Dict[str, Any]) -> Dict[str, Any]:
    ids = cycle.get("order_ids")
    if isinstance(ids, dict):
        return ids
    return {
        "entry": cycle.get("entry_order_id"),
        "exit": cycle.get("exit_order_id"),
    }


def _date_window(cycle: Dict[str, Any]) -> Dict[str, Any]:
    window = cycle.get("date_window")
    return window if isinstance(window, dict) else {}


def _cycles(request: Dict[str, Any]) -> List[Dict[str, Any]]:
    cycles = _as_list(request.get("cycles"))
    if cycles:
        return cycles
    if request:
        return [request]
    return []


def _missing_for_cycle(cycle: Dict[str, Any], index: int) -> List[str]:
    prefix = cycle.get("cycle_id") or f"cycle_{index + 1}"
    ids = _order_ids(cycle)
    window = _date_window(cycle)
    missing: List[str] = []
    if not _present(cycle.get("product_id")):
        missing.append(f"{prefix}.product_id")
    if not _present(ids.get("entry")):
        missing.append(f"{prefix}.order_ids.entry")
    if not _present(ids.get("exit")):
        missing.append(f"{prefix}.order_ids.exit")
    if not _present(window.get("start")):
        missing.append(f"{prefix}.date_window.start")
    if not _present(window.get("end")):
        missing.append(f"{prefix}.date_window.end")
    return missing


def _planned_method_calls(cycle: Dict[str, Any]) -> List[str]:
    product_id = cycle.get("product_id") or "<PRODUCT_ID>"
    ids = _order_ids(cycle)
    window = _date_window(cycle)
    start = window.get("start") or "<START_ISO8601>"
    end = window.get("end") or "<END_ISO8601>"
    calls: List[str] = []
    for leg in ("entry", "exit"):
        order_id = ids.get(leg) or f"<{leg.upper()}_ORDER_ID>"
        calls.append(
            "DO NOT RUN WITHOUT APPROVAL: "
            f"BrokerCoinbase.get_order_status(order_id='{order_id}')"
        )
        calls.append(
            "DO NOT RUN WITHOUT APPROVAL: "
            "BrokerCoinbase.get_historical_fills("
            f"product_id='{product_id}', order_id='{order_id}', start='{start}', end='{end}')"
        )
    return calls


def _slug(value: Any) -> str:
    text = str(value or "unknown").strip().replace("/", "-").replace(" ", "-")
    return "".join(ch for ch in text if ch.isalnum() or ch in ("-", "_"))[:80] or "unknown"


def _future_shell_commands(cycles: Sequence[Dict[str, Any]]) -> List[str]:
    commands: List[str] = []
    for cycle in cycles:
        product_id = cycle.get("product_id") or "<PRODUCT_ID>"
        ids = _order_ids(cycle)
        for leg in ("entry", "exit"):
            order_id = ids.get(leg) or f"<{leg.upper()}_ORDER_ID>"
            raw_path = f"/tmp/coinbase_read_only_evidence_capture_{_slug(cycle.get('cycle_id'))}_{leg}_raw.json"
            redacted_path = raw_path.replace("_raw.json", "_redacted.json")
            commands.append(
                "DO NOT RUN WITHOUT APPROVAL: "
                "python3 scripts/coinbase_read_only_broker_fact_probe.py "
                f"--live-read-only --json --order-id {order_id} --symbol {product_id} > {raw_path}"
            )
            commands.append(
                "OFFLINE REDACTION ONLY: "
                f"python3 scripts/redact_broker_payload.py --input {raw_path} --output {redacted_path}"
            )
    commands.extend([
        f"MANUAL OFFLINE ASSEMBLY ONLY: combine redacted order/fill facts into {ADAPTER_INPUT_PATH}",
        f"OFFLINE AFTER REDACTION ONLY: {ADAPTER_COMMAND}",
        f"OFFLINE AFTER ADAPTER PAYLOAD ONLY: {RESOLVER_COMMAND}",
    ])
    return commands


def build_checklist_report(request: Dict[str, Any], *, human_approved: bool, source_path: str) -> Dict[str, Any]:
    cycles = _cycles(request)
    missing: List[str] = []
    for index, cycle in enumerate(cycles):
        missing.extend(_missing_for_cycle(cycle, index))

    missing_approval = [] if human_approved else ["explicit_human_approval_flag"]
    readiness = READY if human_approved and cycles and not missing else BLOCKED
    planned_calls: List[str] = []
    for cycle in cycles:
        planned_calls.extend(_planned_method_calls(cycle))

    return {
        "verdict": readiness,
        "current_readiness_verdict": readiness,
        "human_approval_supplied": human_approved,
        "approval_required": not human_approved,
        "required_human_approval_checklist": APPROVAL_CHECKLIST,
        "required_order_ids_product_ids_date_windows": cycles,
        "missing_requirements": missing_approval + missing,
        "expected_read_only_broker_methods": [
            "BrokerCoinbase.get_order_status(order_id=...)",
            "BrokerCoinbase.get_historical_fills(product_id=..., order_id=..., start=..., end=...)",
        ],
        "planned_future_method_calls": planned_calls,
        "planned_future_shell_commands": _future_shell_commands(cycles),
        "required_fields": REQUIRED_FIELDS,
        "redaction_requirements": REDACTION_REQUIREMENTS,
        "expected_adapter_input_file_path": ADAPTER_INPUT_PATH,
        "expected_adapter_command": ADAPTER_COMMAND,
        "expected_resolver_command": RESOLVER_COMMAND,
        "next_required_action": (
            "Obtain explicit human approval before any read-only capture. Then collect only the listed "
            "order/fill facts, redact them, run the offline adapter, and run the offline resolver."
        ),
        "profit_readout_real_current": "unsafe_to_aggregate",
        "aggregation_allowed_real_current": False,
        "scaling_allowed": False,
        "risk_increase": "not_approved",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_path": source_path,
        "safety": {
            "offline_only": True,
            "broker_calls_made": False,
            "live_read_only_executed": False,
            "secrets_or_env_read": False,
            "orders_cancels_closes_modifications": False,
            "runtime_risk_config_background_changed": False,
            "state_or_log_mutation": False,
            "logs_coinbase_fills_written": False,
            "fill_logger_append_activation": False,
            "risk_increase": "not_approved",
        },
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Coinbase read-only evidence capture checklist")
    parser.add_argument("--request-json", required=True, type=Path, help="Offline capture request JSON")
    parser.add_argument(
        "--human-approved-read-only-capture",
        action="store_true",
        help="Declare that a human approved a future read-only capture. This script still performs no capture.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args(argv)

    request = _safe_load_json(args.request_json)
    report = build_checklist_report(
        request,
        human_approved=args.human_approved_read_only_capture,
        source_path=str(args.request_json),
    )
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("=== Coinbase Read-Only Evidence Capture Checklist (P2-021C) ===")
        print(f"Verdict: {report['verdict']}")
        print(f"Human approval supplied: {report['human_approval_supplied']}")
        print(f"Missing requirements: {', '.join(report['missing_requirements']) or 'none'}")
        print("Future commands:")
        for command in report["planned_future_shell_commands"]:
            print(f"- {command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
