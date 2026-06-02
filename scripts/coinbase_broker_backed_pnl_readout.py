#!/usr/bin/env python3
"""
Offline broker-backed numeric P/L readout for Coinbase evidence cycles.

This script reads local JSON only. It never imports broker clients, reads .env,
writes logs/state, or places/cancels/closes/modifies orders. It computes numeric
P/L only when direct broker-backed numeric values are present.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from scripts.coinbase_broker_evidence_adapter import normalize_source
from scripts.coinbase_profit_readout_evidence_resolver import build_report_from_probe


MEASURED_VERDICT = "MEASURED_BROKER_BACKED_LIMITED"
BLOCKED_VERDICT = "BLOCKED"
MEASURED_READOUT = "measured_broker_backed_limited"
UNSAFE_READOUT = "unsafe_to_aggregate"
MONEY_QUANT = Decimal("0.0001")

ORDER_ID_KEYS = ("order_id", "client_order_id", "coinbase_order_id")
FILL_ID_KEYS = ("trade_id", "fill_id", "entry_id", "fill_key")
FEE_KEYS = ("total_fees", "fee", "commission", "total_fee")
VALUE_KEYS = ("filled_value", "proceeds", "sell_proceeds", "notional", "quote_size", "quote_value")


def _safe_load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_load_error": str(exc)}


def _as_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def _bool_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "y")
    return bool(value)


def _normalize_side(value: Any) -> str:
    return str(value or "").strip().upper()


def _first_present(obj: Dict[str, Any], keys: Sequence[str]) -> Tuple[Optional[str], Any]:
    for key in keys:
        if key in obj and _present(obj.get(key)):
            return key, obj.get(key)
    return None, None


def _decimal_or_none(value: Any) -> Tuple[Optional[Decimal], Optional[str]]:
    if not _present(value):
        return None, "missing"
    text = str(value).strip()
    if text.startswith("<REDACTED") or text.endswith("_PRESENT>"):
        return None, "redacted"
    try:
        return Decimal(text), None
    except (InvalidOperation, ValueError):
        return None, "not_numeric"


def _format_decimal(value: Decimal) -> str:
    return str(value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP))


def _redact_identifier(value: Any, label: str) -> str:
    return f"<REDACTED_{label.upper()}>" if _present(value) else ""


def _identifiers(values: Iterable[Any], label: str, redact: bool) -> List[str]:
    seen: List[str] = []
    for value in values:
        if not _present(value):
            continue
        text = str(value)
        redacted = _redact_identifier(text, label) if redact else text
        if redacted not in seen:
            seen.append(redacted)
    return seen


def _leg_payloads(leg: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    order = leg.get("order") or leg.get("order_status") or {}
    if isinstance(order, dict) and isinstance(order.get("order"), dict):
        order = order["order"]
    fills = (
        leg.get("fills")
        or leg.get("historical_fills")
        or leg.get("list_fills")
        or []
    )
    if isinstance(fills, dict):
        fills = fills.get("fills") or fills.get("data") or []
    return order if isinstance(order, dict) else {}, _as_list(fills)


def _order_id_available(order: Dict[str, Any], fills: List[Dict[str, Any]]) -> bool:
    if _first_present(order, ORDER_ID_KEYS)[0] is not None:
        return True
    return any(_first_present(fill, ORDER_ID_KEYS)[0] is not None for fill in fills)


def _fill_ids_available(fills: List[Dict[str, Any]]) -> bool:
    if not fills:
        return False
    return all(_first_present(fill, FILL_ID_KEYS)[0] is not None for fill in fills)


def _first_decimal_from(order: Dict[str, Any], fills: List[Dict[str, Any]], keys: Sequence[str]) -> Tuple[Optional[Decimal], str, Optional[str]]:
    key, value = _first_present(order, keys)
    if key is not None:
        amount, reason = _decimal_or_none(value)
        if amount is not None:
            return amount, f"order.{key}", None
        return None, f"order.{key}", reason

    fill_errors: List[str] = []
    for index, fill in enumerate(fills):
        key, value = _first_present(fill, keys)
        if key is None:
            continue
        amount, reason = _decimal_or_none(value)
        if amount is not None:
            return amount, f"fills[{index}].{key}", None
        fill_errors.append(reason or "not_numeric")

    if fill_errors:
        return None, "fills", fill_errors[0]
    return None, "missing", "missing"


def _fee_decimal(order: Dict[str, Any], fills: List[Dict[str, Any]]) -> Tuple[Optional[Decimal], str, Optional[str]]:
    amount, source, reason = _first_decimal_from(order, [], FEE_KEYS)
    if amount is not None or reason not in (None, "missing"):
        return amount, source, reason

    if not fills:
        return None, "missing", "missing"

    total = Decimal("0")
    sources: List[str] = []
    for index, fill in enumerate(fills):
        key, value = _first_present(fill, FEE_KEYS)
        if key is None:
            return None, f"fills[{index}]", "missing"
        fee, reason = _decimal_or_none(value)
        if fee is None:
            return None, f"fills[{index}].{key}", reason
        total += fee
        sources.append(f"fills[{index}].{key}")
    return total, "+".join(sources), None


def _leg_side(order: Dict[str, Any], fills: List[Dict[str, Any]], fallback: str) -> str:
    side = _normalize_side(order.get("side"))
    if side:
        return side
    for fill in fills:
        side = _normalize_side(fill.get("side"))
        if side:
            return side
    return fallback


def _leg_numeric_report(
    leg: Dict[str, Any],
    *,
    label: str,
    redact_identifiers: bool,
) -> Dict[str, Any]:
    order, fills = _leg_payloads(leg)
    fallback_side = "BUY" if label == "entry" else "SELL"
    side = _leg_side(order, fills, fallback_side)
    value, value_source, value_error = _first_decimal_from(order, fills, VALUE_KEYS)
    fees, fee_source, fee_error = _fee_decimal(order, fills)
    order_ids = [
        value
        for value in [_first_present(order, ORDER_ID_KEYS)[1]]
        + [_first_present(fill, ORDER_ID_KEYS)[1] for fill in fills]
        if _present(value)
    ]
    fill_ids = [_first_present(fill, FILL_ID_KEYS)[1] for fill in fills]
    settled = _bool_true(order.get("settled"))

    missing: List[str] = []
    redacted = False
    if side not in ("BUY", "SELL"):
        missing.append(f"{label}.side")
    if label == "entry" and side != "BUY":
        missing.append("entry.side_buy")
    if label == "exit" and side != "SELL":
        missing.append("exit.side_sell")
    if not _order_id_available(order, fills):
        missing.append(f"{label}.direct_order_id")
    if not _fill_ids_available(fills):
        missing.append(f"{label}.direct_trade_or_fill_id")
    if not settled:
        missing.append(f"{label}.settled_true")
    if value is None:
        missing.append(f"{label}.numeric_filled_value_or_proceeds")
        redacted = redacted or value_error == "redacted"
    if fees is None:
        missing.append(f"{label}.numeric_total_fees")
        redacted = redacted or fee_error == "redacted"

    return {
        "side": side,
        "settled": settled,
        "order_ids": _identifiers(order_ids, "order_id", redact_identifiers),
        "fill_ids": _identifiers(fill_ids, "fill_id", redact_identifiers),
        "filled_value_or_proceeds": _format_decimal(value) if value is not None else None,
        "filled_value_or_proceeds_source": value_source,
        "total_fees": _format_decimal(fees) if fees is not None else None,
        "total_fees_source": fee_source,
        "numeric_value_available": value is not None,
        "numeric_fee_available": fees is not None,
        "order_id_available": _order_id_available(order, fills),
        "trade_or_fill_id_available": _fill_ids_available(fills),
        "numeric_values_redacted": redacted,
        "missing_fields": missing,
        "_value_decimal": value,
        "_fee_decimal": fees,
    }


def _contains_local_journal_only_pnl(source: Dict[str, Any]) -> bool:
    if source.get("local_journal_only_pnl") is True:
        return True
    for row in _as_list(source.get("journal_rows")):
        if any(key in row for key in ("pnl", "realized_pnl", "profit", "net_pnl")):
            return True
    return False


def _evidence_from_source(source: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(source.get("adapted_evidence"), dict):
        return source["adapted_evidence"]
    if isinstance(source.get("evidence_cycles"), list):
        return source
    return normalize_source(source)


def _public_leg_report(report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in report.items()
        if key not in ("_value_decimal", "_fee_decimal")
    }


def build_report(source_path: Path, *, redact_identifiers: bool = True) -> Dict[str, Any]:
    source = _safe_load_json(source_path)
    evidence = _evidence_from_source(source)
    resolver_report = build_report_from_probe(evidence, f"numeric-readout:{source_path}")
    cycles = _as_list(evidence.get("evidence_cycles"))

    cycle_reports: List[Dict[str, Any]] = []
    blockers: List[str] = []
    complete_numeric_cycles = 0
    gross_total = Decimal("0")
    fee_total = Decimal("0")
    local_journal_only_pnl = _contains_local_journal_only_pnl(source) or _contains_local_journal_only_pnl(evidence)
    numeric_values_redacted = False

    if source.get("_load_error"):
        blockers.append(f"Could not load source JSON: {source['_load_error']}")
    if local_journal_only_pnl:
        blockers.append("Local journal P/L is present but is not direct broker numeric evidence.")
    if not cycles:
        blockers.append("No evidence cycles supplied.")

    for cycle in cycles:
        entry = _leg_numeric_report(cycle.get("entry") or {}, label="entry", redact_identifiers=redact_identifiers)
        exit_ = _leg_numeric_report(cycle.get("exit") or {}, label="exit", redact_identifiers=redact_identifiers)
        cycle_missing = entry["missing_fields"] + exit_["missing_fields"]
        numeric_values_redacted = numeric_values_redacted or entry["numeric_values_redacted"] or exit_["numeric_values_redacted"]

        gross: Optional[Decimal] = None
        total_fees: Optional[Decimal] = None
        net: Optional[Decimal] = None
        if not cycle_missing and not local_journal_only_pnl:
            gross = exit_["_value_decimal"] - entry["_value_decimal"]
            total_fees = entry["_fee_decimal"] + exit_["_fee_decimal"]
            net = gross - total_fees
            gross_total += gross
            fee_total += total_fees
            complete_numeric_cycles += 1

        cycle_reports.append({
            "cycle_id": cycle.get("cycle_id") or "cycle",
            "product_id": cycle.get("product_id"),
            "entry": _public_leg_report(entry),
            "exit": _public_leg_report(exit_),
            "complete_numeric_evidence": not cycle_missing and not local_journal_only_pnl,
            "missing_fields": cycle_missing,
            "gross_pnl": _format_decimal(gross) if gross is not None else None,
            "total_fees": _format_decimal(total_fees) if total_fees is not None else None,
            "net_pnl": _format_decimal(net) if net is not None else None,
        })

    if numeric_values_redacted:
        blockers.append(
            "Direct broker evidence completeness is proven, but numeric P/L requires numeric-safe "
            "filled_value/proceeds and fee values; redacted presence markers are not numeric."
        )

    incomplete_cycles = [cycle for cycle in cycle_reports if not cycle["complete_numeric_evidence"]]
    if incomplete_cycles:
        blockers.append("One or more cycles are missing required direct numeric broker fields.")

    evidence_complete = resolver_report.get("verdict") == "EVIDENCE_RESOLVED"
    if not evidence_complete:
        blockers.append("Resolver did not confirm complete direct broker evidence cycles.")

    measured = (
        bool(cycles)
        and complete_numeric_cycles == len(cycles)
        and evidence_complete
        and not local_journal_only_pnl
        and not blockers
    )

    net_total = gross_total - fee_total
    if net_total > 0:
        direction = "positive"
    elif net_total < 0:
        direction = "negative"
    else:
        direction = "flat"

    return {
        "verdict": MEASURED_VERDICT if measured else BLOCKED_VERDICT,
        "profit_readout": MEASURED_READOUT if measured else UNSAFE_READOUT,
        "cycles_evaluated": len(cycles),
        "complete_numeric_cycles": complete_numeric_cycles,
        "gross_pnl": _format_decimal(gross_total) if measured else None,
        "total_fees": _format_decimal(fee_total) if measured else None,
        "net_pnl": _format_decimal(net_total) if measured else None,
        "net_pnl_direction": direction if measured else "flat",
        "evidence_level": resolver_report.get("evidence_level"),
        "scaling_allowed": False,
        "risk_increase": "not_approved",
        "local_journal_only_pnl": local_journal_only_pnl,
        "numeric_values_redacted": numeric_values_redacted,
        "blockers": sorted(set(blockers)),
        "cycle_reports": cycle_reports,
        "resolver_verdict": resolver_report.get("verdict"),
        "resolver_profit_readout": resolver_report.get("profit_readout"),
        "aggregation_allowed_limited_to_numeric_cycles": bool(measured),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_path": str(source_path),
        "safety": {
            "offline_only": True,
            "broker_calls_made": False,
            "live_read_only_used": False,
            "secrets_or_env_read": False,
            "orders_cancels_closes_modifications": False,
            "state_or_log_mutation": False,
            "fill_logger_activation": False,
            "risk_increase": "not_approved",
        },
    }


def _parse_redact_flag(value: str) -> bool:
    text = value.strip().lower()
    if text in ("true", "1", "yes", "y"):
        return True
    if text in ("false", "0", "no", "n"):
        return False
    raise argparse.ArgumentTypeError("--redact-identifiers must be true or false")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Coinbase broker-backed numeric P/L readout")
    parser.add_argument("--source-json", required=True, type=Path, help="Offline broker-backed evidence JSON")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument(
        "--redact-identifiers",
        type=_parse_redact_flag,
        default=True,
        help="Redact order/fill identifiers in output (default: true)",
    )
    args = parser.parse_args(argv)

    report = build_report(args.source_json, redact_identifiers=args.redact_identifiers)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("=== Coinbase Broker-Backed Numeric P/L Readout ===")
        print(f"Verdict: {report['verdict']}")
        print(f"Profit/Readout: {report['profit_readout']}")
        print(f"Cycles evaluated: {report['cycles_evaluated']}")
        print(f"Complete numeric cycles: {report['complete_numeric_cycles']}")
        print(f"Gross P/L: {report['gross_pnl']}")
        print(f"Total fees: {report['total_fees']}")
        print(f"Net P/L: {report['net_pnl']}")
        print(f"Scaling allowed: {report['scaling_allowed']}")
        if report["blockers"]:
            print("Blockers:")
            for blocker in report["blockers"]:
                print(f"  - {blocker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
