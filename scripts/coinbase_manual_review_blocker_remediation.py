#!/usr/bin/env python3
"""
P2-021C3 - Offline Coinbase manual-review blocker remediation.

Default mode is dry-run. The script reads local state only and can prepare an
operator-approved normalization plan for a stale manual-review blocker when the
position is explicitly proven to be external/staked/non-bot-tradable inventory.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


UNSAFE_READOUT = "unsafe_to_aggregate"
SAFE_REASON = "external_staked_non_bot_inventory"
DEFAULT_ALLOWED_SYMBOL = "SOL/USD"
MANUAL_REVIEW_REASONS = (
    "broker_close_capability_unconfirmed",
    "manual_review_position_open",
    "external_staked_position",
)
PENDING_EXIT_KEYS = (
    "pending_close",
    "pending_exit",
    "exit_pending",
    "close_pending",
    "pending_cancel",
    "pending_cancel_id",
    "close_order_id",
    "exit_order_id",
    "unreconciled_exit",
)
PENDING_EXIT_STATUSES = {
    "pending_close",
    "close_pending",
    "submitted_close",
    "pending_cancel",
    "exit_pending",
    "sell_pending",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp_for_path(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ")


def _iso(now: datetime) -> str:
    return now.isoformat()


def _safe_load_json(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if not path.exists():
        return None, "missing"
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"malformed: {exc}"
    if not isinstance(loaded, dict):
        return None, "malformed: top-level JSON is not an object"
    return loaded, None


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _normalize_symbol(symbol: Any) -> str:
    text = str(symbol or "").strip().upper().replace("-", "/")
    if text == "SOL":
        return DEFAULT_ALLOWED_SYMBOL
    return text


def _bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "1", "yes", "y"):
            return True
        if text in ("false", "0", "no", "n"):
            return False
    return None


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def _state_paths(state_root: Path) -> Dict[str, Path]:
    coinbase_dir = state_root / "state" / "coinbase"
    return {
        "coinbase_dir": coinbase_dir,
        "open_positions": coinbase_dir / "open_positions.json",
        "external_inventory": coinbase_dir / "external_inventory.json",
        "backups_dir": coinbase_dir / "backups",
        "heartbeat": state_root / "runtime" / "coinbase_heartbeat.json",
        "journal": state_root / "journal_coinbase_crypto.csv",
    }


def _extract_positions(open_state: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], str]:
    if isinstance(open_state.get("positions"), dict):
        return {
            str(symbol): dict(position)
            for symbol, position in open_state["positions"].items()
            if isinstance(position, dict)
        }, "positions"
    return {
        str(symbol): dict(position)
        for symbol, position in open_state.items()
        if isinstance(position, dict)
    }, "direct"


def _replace_positions(open_state: Dict[str, Any], positions: Dict[str, Dict[str, Any]], shape: str, now: datetime) -> Dict[str, Any]:
    updated = dict(open_state)
    if shape == "positions":
        updated["positions"] = positions
        updated["saved_at"] = _iso(now)
    else:
        updated = dict(positions)
    return updated


def _manual_review_reason(position: Dict[str, Any]) -> str:
    reason = str(position.get("manual_review_reason") or position.get("reason") or "").strip()
    if reason:
        return reason
    if position.get("user_action_required") is True:
        return "manual_review_position_open"
    return ""


def _is_manual_review_blocker(position: Dict[str, Any]) -> bool:
    reason = _manual_review_reason(position).lower()
    return bool(
        position.get("user_action_required") is True
        or position.get("api_controllable") is False
        or position.get("exit_evaluation_enabled") is False
        or any(token in reason for token in MANUAL_REVIEW_REASONS)
    )


def _has_pending_exit_activity(position: Dict[str, Any]) -> bool:
    for key in PENDING_EXIT_KEYS:
        value = position.get(key)
        if value is True:
            return True
        if isinstance(value, str) and value.strip():
            return True
    status = str(position.get("order_status") or position.get("status") or "").strip().lower()
    return status in PENDING_EXIT_STATUSES


def _is_external_staked_evidence(payload: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    classification = str(payload.get("external_inventory_classification") or "").strip().lower()
    staked = _bool(payload.get("staked_external_position")) is True or _bool(payload.get("external_staked_position")) is True
    tradable_false = _bool(payload.get("tradable_by_bot")) is False
    manual_close_false = _bool(payload.get("manual_close_allowed")) is False
    bot_inventory_false = _bool(payload.get("bot_inventory")) is False
    symbol_matches = not payload.get("symbol") or _normalize_symbol(payload.get("symbol")) == symbol
    classification_external = "external" in classification and "staked" in classification
    evidence = bool(symbol_matches and (staked or classification_external) and tradable_false and manual_close_false and bot_inventory_false)
    return {
        "present": evidence,
        "symbol_matches": symbol_matches,
        "staked_external_position": staked,
        "external_inventory_classification": classification or None,
        "tradable_by_bot_false": tradable_false,
        "manual_close_allowed_false": manual_close_false,
        "bot_inventory_false": bot_inventory_false,
    }


def _load_assertion(path: Optional[Path]) -> Tuple[Dict[str, Any], Optional[str]]:
    if path is None:
        return {}, None
    data, error = _safe_load_json(path)
    if error:
        return {}, error
    return data or {}, None


def _current_counts_toward_exposure(position: Dict[str, Any]) -> bool:
    return position.get("counts_toward_exposure", True) is not False


def _build_external_record(symbol: str, position: Dict[str, Any], reason: str, now: datetime) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "qty": position.get("qty") or position.get("quantity") or position.get("filled_qty") or position.get("size"),
        "notional": position.get("notional") or position.get("market_value"),
        "original_order_id": position.get("order_id"),
        "original_client_order_id": position.get("client_order_id"),
        "original_entry_time": position.get("entry_time") or position.get("timestamp") or position.get("opened_at"),
        "original_manual_review_reason": reason,
        "normalization_time": _iso(now),
        "operator_approved": True,
        "no_pnl_inference": True,
        "no_close_attempted": True,
        "staked_external_position": True,
        "external_inventory_classification": "external_staked_position",
        "tradable_by_bot": False,
        "manual_close_allowed": False,
        "bot_inventory": False,
        "blocks_new_entries": False,
        "source": "p2_021c3_manual_review_blocker_remediation",
    }


def _normalized_state_preview(symbol: str, positions: Dict[str, Dict[str, Any]], external_record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "open_positions_after": sorted(sym for sym in positions if _normalize_symbol(sym) != symbol),
        "external_inventory_record": external_record,
    }


def _load_external_inventory(path: Path) -> Dict[str, Any]:
    data, error = _safe_load_json(path)
    if error:
        return {"external_inventory": {}}
    if isinstance(data.get("external_inventory"), dict):
        return data
    if isinstance(data.get("inventory"), dict):
        return {"external_inventory": data["inventory"]}
    return {"external_inventory": data if isinstance(data, dict) else {}}


def _backup_payload(open_path: Path, external_path: Path, open_state: Dict[str, Any], external_state: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    return {
        "created_at": _iso(now),
        "open_positions_path": str(open_path),
        "external_inventory_path": str(external_path),
        "open_positions": open_state,
        "external_inventory": external_state,
    }


def build_report(
    *,
    state_root: Path,
    assertion_json: Optional[Path] = None,
    allow_symbol: str = DEFAULT_ALLOWED_SYMBOL,
    apply: bool = False,
    operator_approved: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    now = now or _utc_now()
    paths = _state_paths(state_root)
    allowed_symbol = _normalize_symbol(allow_symbol)
    open_state, open_error = _safe_load_json(paths["open_positions"])
    assertion, assertion_error = _load_assertion(assertion_json)
    backup_path = paths["backups_dir"] / f"open_positions_external_inventory_normalization_{_timestamp_for_path(now)}.json"

    base = {
        "verdict": "NOT_SAFE_TO_NORMALIZE",
        "blocker_symbol": None,
        "blocker_reason": None,
        "bot_opened": None,
        "api_controllable": None,
        "user_action_required": None,
        "exit_evaluation_enabled": None,
        "current_counts_toward_exposure": None,
        "detected_external_inventory_evidence": False,
        "detected_staked_evidence": False,
        "safe_to_normalize": False,
        "apply_required": False,
        "backup_path_preview": str(backup_path),
        "normalized_state_preview": None,
        "trading_block_would_clear": False,
        "profit_readout": UNSAFE_READOUT,
        "next_required_action": "Inspect local state and provide explicit external/staked evidence before normalization.",
        "refusal_reasons": [],
        "state_paths": {key: str(path) for key, path in paths.items() if key != "coinbase_dir"},
        "safety": {
            "offline_only": True,
            "broker_calls_made": False,
            "live_read_only_executed": False,
            "secrets_or_env_read": False,
            "orders_cancels_closes_modifications": False,
            "state_or_log_mutation": False,
            "risk_increase": "not_approved",
        },
        "generated_at": _iso(now),
    }

    if open_error:
        base["refusal_reasons"].append(f"state_file_{open_error}")
        base["next_required_action"] = "Restore or repair state/coinbase/open_positions.json before normalization."
        return base
    if assertion_error:
        base["refusal_reasons"].append(f"assertion_json_{assertion_error}")
        return base

    positions, shape = _extract_positions(open_state or {})
    blockers = {
        symbol: position
        for symbol, position in positions.items()
        if _is_manual_review_blocker(position)
    }
    if len(blockers) != 1:
        base["refusal_reasons"].append("exactly_one_blocking_manual_review_position_required")
        base["next_required_action"] = "Normalize only after exactly one stale manual-review blocker is isolated."
        return base

    raw_symbol, position = next(iter(blockers.items()))
    symbol = _normalize_symbol(position.get("symbol") or raw_symbol)
    reason = _manual_review_reason(position)
    base.update({
        "blocker_symbol": symbol,
        "blocker_reason": reason,
        "bot_opened": position.get("bot_opened"),
        "api_controllable": position.get("api_controllable"),
        "user_action_required": position.get("user_action_required"),
        "exit_evaluation_enabled": position.get("exit_evaluation_enabled"),
        "current_counts_toward_exposure": _current_counts_toward_exposure(position),
    })

    refusal_reasons = base["refusal_reasons"]
    if symbol != allowed_symbol:
        refusal_reasons.append("symbol_not_allowed_without_explicit_allow_symbol")
    if position.get("api_controllable") is True:
        refusal_reasons.append("api_controllable_position_refuses_normalization")
    if position.get("user_action_required") is not True:
        refusal_reasons.append("user_action_required_true_required")
    if position.get("exit_evaluation_enabled") is not False:
        refusal_reasons.append("exit_evaluation_enabled_false_required")
    if not any(token in reason.lower() for token in MANUAL_REVIEW_REASONS):
        refusal_reasons.append("manual_review_reason_not_equivalent_to_broker_close_capability_unconfirmed")
    if _bool(position.get("tradable_by_bot")) is True or _bool(assertion.get("tradable_by_bot")) is True:
        refusal_reasons.append("position_appears_tradable_by_bot")
    if _has_pending_exit_activity(position):
        refusal_reasons.append("pending_close_or_exit_activity_unreconciled")

    state_evidence = _is_external_staked_evidence(position, symbol)
    assertion_evidence = _is_external_staked_evidence(assertion, symbol) if assertion else {"present": False}
    detected_external = bool(state_evidence["present"] or assertion_evidence["present"])
    detected_staked = bool(state_evidence.get("staked_external_position") or assertion_evidence.get("staked_external_position"))
    base["detected_external_inventory_evidence"] = detected_external
    base["detected_staked_evidence"] = detected_staked
    base["external_inventory_evidence_sources"] = {
        "state": state_evidence,
        "assertion": assertion_evidence,
    }
    if not detected_external:
        refusal_reasons.append("external_staked_non_bot_inventory_evidence_missing")

    positions_after = {
        existing_symbol: existing_position
        for existing_symbol, existing_position in positions.items()
        if _normalize_symbol(existing_position.get("symbol") or existing_symbol) != symbol
    }
    external_record = _build_external_record(symbol, position, reason, now)
    preview = _normalized_state_preview(symbol, positions, external_record)
    base["normalized_state_preview"] = preview
    base["trading_block_would_clear"] = len([
        p for p in positions_after.values() if _is_manual_review_blocker(p)
    ]) == 0

    if refusal_reasons:
        base["next_required_action"] = "Refused. Resolve refusal_reasons before considering operator-approved normalization."
        return base

    base["safe_to_normalize"] = True
    base["apply_required"] = not apply
    if not apply:
        base["verdict"] = "DRY_RUN_READY_FOR_OPERATOR_APPROVAL"
        base["next_required_action"] = (
            "Review the preview. To normalize local state only, rerun with "
            "--apply --operator-approved-external-inventory-normalization."
        )
        return base

    if not operator_approved:
        base["verdict"] = "NOT_SAFE_TO_NORMALIZE"
        base["safe_to_normalize"] = False
        base["apply_required"] = False
        base["refusal_reasons"] = ["operator_approval_flag_missing_during_apply"]
        base["next_required_action"] = "Apply refused until the explicit operator approval flag is supplied."
        return base

    external_state = _load_external_inventory(paths["external_inventory"])
    _write_json(backup_path, _backup_payload(paths["open_positions"], paths["external_inventory"], open_state or {}, external_state, now))
    open_after = _replace_positions(open_state or {}, positions_after, shape, now)
    external_records = dict(external_state.get("external_inventory") or {})
    external_records[symbol] = external_record
    external_after = {
        "updated_at": _iso(now),
        "external_inventory": external_records,
    }
    _write_json(paths["open_positions"], open_after)
    _write_json(paths["external_inventory"], external_after)

    base["verdict"] = "NORMALIZED_EXTERNAL_INVENTORY"
    base["apply_required"] = False
    base["backup_path"] = str(backup_path)
    base["state_mutations"] = [
        str(paths["open_positions"]),
        str(paths["external_inventory"]),
        str(backup_path),
    ]
    base["safety"]["state_or_log_mutation"] = True
    base["next_required_action"] = "Restart or reload the bot state path after reviewing backup and external inventory records."
    return base


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Coinbase manual-review blocker remediation")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--state-root", type=Path, default=Path("."), help="Root containing state/coinbase and runtime files")
    parser.add_argument("--assertion-json", type=Path, help="Local operator assertion JSON proving external/staked inventory")
    parser.add_argument("--allow-symbol", default=DEFAULT_ALLOWED_SYMBOL, help="Only this symbol may be normalized")
    parser.add_argument("--apply", action="store_true", help="Apply local state normalization")
    parser.add_argument(
        "--operator-approved-external-inventory-normalization",
        action="store_true",
        help="Required with --apply. Confirms operator approval for local state normalization only.",
    )
    args = parser.parse_args(argv)

    report = build_report(
        state_root=args.state_root,
        assertion_json=args.assertion_json,
        allow_symbol=args.allow_symbol,
        apply=args.apply,
        operator_approved=args.operator_approved_external_inventory_normalization,
    )
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("=== Coinbase Manual-Review Blocker Remediation (P2-021C3) ===")
        print(f"Verdict: {report['verdict']}")
        print(f"Blocker symbol: {report['blocker_symbol']}")
        print(f"Safe to normalize: {report['safe_to_normalize']}")
        print(f"Trading block would clear: {report['trading_block_would_clear']}")
        print(f"Next required action: {report['next_required_action']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
