#!/usr/bin/env python3
"""Offline diagnosis for Coinbase manual-review position blockers."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATHS = {
    "journal": ROOT / "journal_coinbase_crypto.csv",
    "open_positions": ROOT / "state" / "coinbase" / "open_positions.json",
    "external_inventory": ROOT / "state" / "coinbase" / "external_inventory.json",
    "closed_positions": ROOT / "state" / "coinbase" / "closed_positions.json",
}
MANUAL_REVIEW_TOKENS = (
    "manual_review_position_open",
    "broker_close_capability_unconfirmed",
    "manual_review",
)
ADA_ENTRY_TOKENS = ("buy", "entry", "filled")
FAILED_CLOSE_TOKENS = ("failed close attempts", "failed close", "unrecoverable")
REASSOCIATED_TOKENS = ("re-associated", "reassociated")


def _normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper().replace("-", "/")


def _safe_load_json(path: Path) -> tuple[Dict[str, Any], str]:
    if not path.exists():
        return {}, "missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, f"malformed: {exc}"
    if not isinstance(data, dict):
        return {}, "malformed: top-level JSON is not an object"
    return data, "ok"


def _records(data: Dict[str, Any], container_keys: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    for key in container_keys:
        nested = data.get(key)
        if isinstance(nested, dict):
            return {
                _normalize_symbol(symbol): dict(record)
                for symbol, record in nested.items()
                if isinstance(record, dict)
            }
    return {
        _normalize_symbol(symbol): dict(record)
        for symbol, record in data.items()
        if isinstance(record, dict)
    }


def _manual_reason(record: Dict[str, Any]) -> str:
    for key in ("manual_review_reason", "original_manual_review_reason", "reason"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    if record.get("user_action_required") is True:
        return "manual_review_position_open"
    return ""


def _is_manual_blocker(record: Dict[str, Any]) -> bool:
    reason = _manual_reason(record).lower()
    return bool(
        any(token in reason for token in MANUAL_REVIEW_TOKENS)
        or record.get("user_action_required") is True
        or record.get("api_controllable") is False
        or record.get("exit_evaluation_enabled") is False
    )


def _blocker_record(symbol: str, record: Dict[str, Any], source: str) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "source": source,
        "manual_review_reason": _manual_reason(record) or None,
        "user_action_required": record.get("user_action_required"),
        "api_controllable": record.get("api_controllable"),
        "exit_evaluation_enabled": record.get("exit_evaluation_enabled"),
        "external_inventory_classification": record.get("external_inventory_classification"),
        "staked_external_position": record.get("staked_external_position"),
        "bot_inventory": record.get("bot_inventory"),
        "tradable_by_bot": record.get("tradable_by_bot"),
        "manual_close_allowed": record.get("manual_close_allowed"),
    }


def _journal_rows(path: Path) -> tuple[List[Dict[str, str]], str]:
    if not path.exists():
        return [], "missing"
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return [
                {
                    str(key or "").strip().lower().replace(" ", "_"): str(value or "").strip()
                    for key, value in row.items()
                }
                for row in csv.DictReader(handle)
            ], "ok"
    except Exception as exc:
        return [], f"malformed: {exc}"


def _row_text(row: Dict[str, str]) -> str:
    return " ".join(str(value or "") for value in row.values()).lower()


def _journal_event(row: Dict[str, str]) -> Dict[str, Any]:
    reason = (
        row.get("reason")
        or row.get("error")
        or row.get("message")
        or row.get("notes")
        or ""
    )
    return {
        "timestamp": row.get("timestamp") or row.get("time") or row.get("datetime") or None,
        "symbol": _normalize_symbol(row.get("symbol") or row.get("product_id")),
        "side": row.get("side") or None,
        "action": row.get("action") or None,
        "decision": row.get("decision") or row.get("status") or None,
        "reason": reason or None,
        "order_id": row.get("order_id") or row.get("coinbase_order_id") or None,
        "price": row.get("price") or row.get("fill_price") or None,
        "quantity": row.get("quantity") or row.get("qty") or row.get("size") or None,
    }


def _latest(rows: Iterable[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    selected = list(rows)
    if not selected:
        return None
    selected.sort(key=lambda row: row.get("timestamp") or row.get("time") or "")
    return _journal_event(selected[-1])


def _journal_evidence(rows: List[Dict[str, str]]) -> Dict[str, Any]:
    ada_rows = [row for row in rows if _normalize_symbol(row.get("symbol") or row.get("product_id")) == "ADA/USD"]
    ada_entries = [
        row for row in ada_rows
        if any(token in _row_text(row) for token in ADA_ENTRY_TOKENS)
        and "skipped" not in _row_text(row)
    ]
    failed_close = [row for row in ada_rows if any(token in _row_text(row) for token in FAILED_CLOSE_TOKENS)]
    reassociated = [row for row in ada_rows if any(token in _row_text(row) for token in REASSOCIATED_TOKENS)]
    blocked = [
        row for row in rows
        if "entry_blocked" in _row_text(row)
        and "manual_review_position_open" in _row_text(row)
    ]
    blocked.sort(key=lambda row: row.get("timestamp") or row.get("time") or "")
    return {
        "most_recent_ada_entry_or_fill": _latest(ada_entries),
        "ada_failed_close_warning": _latest(failed_close),
        "ada_broker_reassociated_warning": _latest(reassociated),
        "recent_entry_blocked_rows": [_journal_event(row) for row in blocked[-10:]],
        "recent_entry_blocked_count": len(blocked),
    }


def _live_process_count(ps_text_path: Optional[Path]) -> int | str:
    if ps_text_path is None:
        return "not evaluated"
    try:
        lines = ps_text_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return "not evaluated"
    return sum(
        1
        for line in lines
        if "main.py" in line and "--mode live" in line and "grep" not in line
    )


def build_report(
    *,
    journal_path: Path = DEFAULT_PATHS["journal"],
    open_positions_path: Path = DEFAULT_PATHS["open_positions"],
    external_inventory_path: Path = DEFAULT_PATHS["external_inventory"],
    closed_positions_path: Path = DEFAULT_PATHS["closed_positions"],
    ps_text_path: Optional[Path] = None,
) -> Dict[str, Any]:
    open_data, open_status = _safe_load_json(open_positions_path)
    external_data, external_status = _safe_load_json(external_inventory_path)
    closed_data, closed_status = _safe_load_json(closed_positions_path)
    rows, journal_status = _journal_rows(journal_path)

    open_records = _records(open_data, ("positions", "open_positions"))
    external_records = _records(external_data, ("external_inventory", "inventory"))
    closed_records = _records(closed_data, ("positions", "closed_positions"))

    blockers = [
        _blocker_record(symbol, record, "open_positions")
        for symbol, record in sorted(open_records.items())
        if _is_manual_blocker(record)
    ]
    blockers.extend(
        _blocker_record(symbol, record, "external_inventory")
        for symbol, record in sorted(external_records.items())
        if _is_manual_blocker(record)
    )

    process_count = _live_process_count(ps_text_path)
    duplicate_risk: bool | str = (
        process_count > 1 if isinstance(process_count, int) else "not evaluated"
    )
    blocker_symbols = sorted({record["symbol"] for record in blockers})
    active_blocker = bool(blockers)

    return {
        "report_class": "manual_review_position_blocker_diagnostics",
        "verdict": "BLOCKED_MANUAL_REVIEW_POSITION" if active_blocker else "NO_MANUAL_REVIEW_BLOCKER_FOUND",
        "source_status": {
            "journal": journal_status,
            "open_positions": open_status,
            "external_inventory": external_status,
            "closed_positions": closed_status,
        },
        "live_process_count": process_count,
        "current_manual_review_blockers": blockers,
        "current_manual_review_blocker_symbols": blocker_symbols,
        "journal_evidence": _journal_evidence(rows),
        "closed_position_symbols_observed": sorted(closed_records),
        "blocker_classification": {
            "active_state_blocker": active_blocker,
            "duplicate_live_process_risk": duplicate_risk,
            "safe_to_auto_clear": False,
            "live_trading_unblock_authorized": False,
        },
        "recommended_next_action": [
            "Operator must manually confirm Coinbase balances for ADA, SOL, BTC, and ETH.",
            "Do not clear the blocker while duplicate live process risk exists.",
            "Prepare a separate remediation proposal only after manual balance confirmation.",
        ],
        "implementation_authorized": False,
        "state_mutation_authorized": False,
        "manual_review_clear_authorized": False,
        "live_trading_unblock_authorized": False,
        "paper_probe_authorized": False,
        "live_probe_authorized": False,
        "scaling_authorized": False,
        "safety": {
            "broker_calls_made": False,
            "network_calls_made": False,
            "state_files_mutated": False,
            "runtime_state_written": False,
            "default_output_only": True,
        },
    }


def render_text(report: Dict[str, Any]) -> str:
    lines = [
        "=== COINBASE MANUAL-REVIEW BLOCKER DIAGNOSTICS ===",
        f"verdict={report['verdict']}",
        f"live_process_count={report['live_process_count']}",
        f"active_state_blocker={str(report['blocker_classification']['active_state_blocker']).lower()}",
        f"duplicate_live_process_risk={str(report['blocker_classification']['duplicate_live_process_risk']).lower()}",
    ]
    for blocker in report["current_manual_review_blockers"]:
        lines.append(
            "blocker "
            f"symbol={blocker['symbol']} source={blocker['source']} "
            f"reason={blocker['manual_review_reason']}"
        )
    evidence = report["journal_evidence"]
    lines.extend(
        [
            f"ada_entry_or_fill_found={str(evidence['most_recent_ada_entry_or_fill'] is not None).lower()}",
            f"ada_failed_close_warning_found={str(evidence['ada_failed_close_warning'] is not None).lower()}",
            f"ada_reassociated_warning_found={str(evidence['ada_broker_reassociated_warning'] is not None).lower()}",
            f"recent_entry_blocked_count={evidence['recent_entry_blocked_count']}",
            "safe_to_auto_clear=false",
            "implementation_authorized=false",
            "state_mutation_authorized=false",
            "manual_review_clear_authorized=false",
            "live_trading_unblock_authorized=false",
            "paper_probe_authorized=false",
            "live_probe_authorized=false",
            "scaling_authorized=false",
            "next_action=manually confirm Coinbase balances for ADA, SOL, BTC, and ETH",
            "=== END DIAGNOSTICS ===",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, default=DEFAULT_PATHS["journal"])
    parser.add_argument("--open-positions", type=Path, default=DEFAULT_PATHS["open_positions"])
    parser.add_argument("--external-inventory", type=Path, default=DEFAULT_PATHS["external_inventory"])
    parser.add_argument("--closed-positions", type=Path, default=DEFAULT_PATHS["closed_positions"])
    parser.add_argument("--ps-text", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    report = build_report(
        journal_path=args.journal,
        open_positions_path=args.open_positions,
        external_inventory_path=args.external_inventory,
        closed_positions_path=args.closed_positions,
        ps_text_path=args.ps_text,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) if args.json else render_text(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
