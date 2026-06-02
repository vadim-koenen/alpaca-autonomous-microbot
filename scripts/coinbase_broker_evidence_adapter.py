#!/usr/bin/env python3
"""
P2-021B - Offline Coinbase broker evidence adapter.

Normalizes captured Coinbase-like order/fill payloads into the P2-021A
profit-readout evidence schema. This script is offline-only: it reads a supplied
JSON file and never imports broker clients, reads .env, writes logs/state, or
places/cancels/closes/modifies orders.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from scripts.coinbase_profit_readout_evidence_resolver import build_report_from_probe

ONE_CYCLE_READ_ONLY_SCHEMA = "p2-022c.one_cycle_read_only_payload.v1"


def _safe_load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_load_error": str(exc)}


def _as_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _unwrap_order(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("order"), dict):
        return dict(payload["order"])
    if isinstance(payload, dict):
        return dict(payload)
    return {}


def _normalize_side(value: Any) -> str:
    return str(value or "").strip().upper()


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "y")
    return bool(value)


def _first_present(obj: Dict[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        value = obj.get(key)
        if value not in (None, ""):
            return value
    return None


def _normalize_order(order: Dict[str, Any]) -> Dict[str, Any]:
    order = _unwrap_order(order)
    normalized = dict(order)
    if "order_id" not in normalized and normalized.get("id"):
        normalized["order_id"] = normalized.get("id")
    if "filled_value" not in normalized:
        value = _first_present(normalized, ("proceeds", "quote_size", "quote_value", "notional"))
        if value is not None:
            normalized["filled_value"] = value
    if "total_fees" not in normalized:
        fee = _first_present(normalized, ("fee", "commission", "total_fee"))
        if fee is not None:
            normalized["total_fees"] = fee
    return normalized


def _normalize_fill(fill: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(fill)
    if "trade_id" not in normalized:
        fill_id = _first_present(normalized, ("fill_id", "entry_id", "trade_id"))
        if fill_id is not None:
            normalized["trade_id"] = fill_id
    if "fee" not in normalized:
        fee = _first_present(normalized, ("commission", "total_fees", "total_fee"))
        if fee is not None:
            normalized["fee"] = fee
    if "filled_value" not in normalized:
        value = _first_present(normalized, ("proceeds", "sell_proceeds", "quote_size", "quote_value", "notional"))
        if value is not None:
            normalized["filled_value"] = value
    return normalized


def _redacted_fact_value(name: str) -> str:
    return f"<REDACTED_DIRECT_BROKER_{name.upper()}_PRESENT>"


def _payload_order_fact(payload: Dict[str, Any], fact_key: str) -> bool:
    facts = payload.get("order_facts")
    if not isinstance(facts, dict):
        return False
    return _coerce_bool(facts.get(fact_key))


def _payload_fill_fact(fill_fact: Dict[str, Any], fact_key: str) -> bool:
    return _coerce_bool(fill_fact.get(fact_key))


def _embedded_order_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    for key in (
        "order",
        "order_status",
        "order_status_redacted",
        "broker_order",
        "broker_order_payload",
        "raw_order",
    ):
        value = payload.get(key)
        if isinstance(value, dict):
            return _normalize_order(value)

    direct_order_keys = {
        "order_id",
        "client_order_id",
        "product_id",
        "side",
        "status",
        "filled_size",
        "average_filled_price",
        "filled_value",
        "total_fees",
        "settled",
    }
    if any(key in payload for key in direct_order_keys):
        return _normalize_order(payload)
    return {}


def _order_from_broker_payload(
    payload: Dict[str, Any],
    *,
    cycle: Dict[str, Any],
    leg: str,
) -> Dict[str, Any]:
    side = "BUY" if leg == "entry" else "SELL"
    order = _embedded_order_payload(payload)
    order_id_key = f"{leg}_order_id"
    order_id = (
        cycle.get(order_id_key)
        or order.get("order_id")
        or payload.get("order_id")
        or order.get("client_order_id")
    )
    if isinstance(order_id, str) and order_id.startswith("<REDACTED"):
        order_id = cycle.get(order_id_key)

    product_id = (
        cycle.get("product_id")
        or order.get("product_id")
        or payload.get("product_id")
        or payload.get("symbol")
    )

    order.setdefault("order_id", order_id)
    order.setdefault("product_id", product_id)
    order.setdefault("side", side)
    order.setdefault("status", "FILLED")

    field_facts = {
        "filled_size": "has_filled_size",
        "average_filled_price": "has_average_filled_price",
        "filled_value": "has_filled_value",
        "total_fees": "has_total_fees",
    }
    for field, fact in field_facts.items():
        if field not in order and _payload_order_fact(payload, fact):
            order[field] = _redacted_fact_value(field)

    if "settled" not in order and _payload_order_fact(payload, "has_settled"):
        order["settled"] = True

    if side == "SELL" and order.get("filled_value") and not order.get("proceeds"):
        order["proceeds"] = order["filled_value"]

    return order


def _embedded_fills_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    fills: List[Dict[str, Any]] = []
    for key in ("fills", "historical_fills", "list_fills", "fills_redacted"):
        value = payload.get(key)
        if isinstance(value, dict):
            value = value.get("fills") or value.get("data") or []
        fills.extend(_normalize_fill(item) for item in _as_list(value))
    return fills


def _fills_from_broker_payload(
    payload: Dict[str, Any],
    *,
    order: Dict[str, Any],
    cycle: Dict[str, Any],
    leg: str,
) -> List[Dict[str, Any]]:
    side = "BUY" if leg == "entry" else "SELL"
    product_id = order.get("product_id") or cycle.get("product_id") or payload.get("symbol")
    order_id = order.get("order_id")
    fills = _embedded_fills_payload(payload)
    for fill in fills:
        fill.setdefault("order_id", order_id)
        fill.setdefault("product_id", product_id)
        fill.setdefault("side", side)
        if order.get("filled_value") and "filled_value" not in fill:
            fill["filled_value"] = order["filled_value"]

    if fills:
        return fills

    synthetic_fills: List[Dict[str, Any]] = []
    for index, fill_fact in enumerate(_as_list(payload.get("fill_facts")), start=1):
        fill: Dict[str, Any] = {
            "order_id": order_id,
            "product_id": product_id,
            "side": side,
        }
        stable_id = fill_fact.get("stable_id_value")
        if stable_id and not str(stable_id).startswith("<REDACTED"):
            fill["trade_id"] = stable_id
        elif _payload_fill_fact(fill_fact, "has_stable_id"):
            fill["trade_id"] = _redacted_fact_value(f"{leg}_fill_id_{index}")
        if _payload_fill_fact(fill_fact, "has_fee"):
            fill["fee"] = _redacted_fact_value(f"{leg}_fill_fee_{index}")
        if _payload_fill_fact(fill_fact, "has_price"):
            fill["price"] = _redacted_fact_value(f"{leg}_fill_price_{index}")
        if _payload_fill_fact(fill_fact, "has_size"):
            fill["size"] = _redacted_fact_value(f"{leg}_fill_size_{index}")
        if order.get("filled_value"):
            fill["filled_value"] = order["filled_value"]
        synthetic_fills.append(fill)
    return synthetic_fills


def _normalize_one_cycle_read_only_source(source: Dict[str, Any]) -> Dict[str, Any]:
    cycles: List[Dict[str, Any]] = []
    for index, cycle in enumerate(_as_list(source.get("cycles")), start=1):
        entry_payload = cycle.get("entry_broker_payload_redacted")
        exit_payload = cycle.get("exit_broker_payload_redacted")
        if not isinstance(entry_payload, dict) or not isinstance(exit_payload, dict):
            continue

        entry_order = _order_from_broker_payload(entry_payload, cycle=cycle, leg="entry")
        exit_order = _order_from_broker_payload(exit_payload, cycle=cycle, leg="exit")
        entry_fills = _fills_from_broker_payload(entry_payload, order=entry_order, cycle=cycle, leg="entry")
        exit_fills = _fills_from_broker_payload(exit_payload, order=exit_order, cycle=cycle, leg="exit")
        cycles.append({
            "cycle_id": cycle.get("cycle_id") or f"adapted-one-cycle-{index}",
            "product_id": cycle.get("product_id") or entry_order.get("product_id") or exit_order.get("product_id"),
            "entry": {
                "order": entry_order,
                "fills": entry_fills,
            },
            "exit": {
                "order": exit_order,
                "fills": exit_fills,
            },
        })

    return {
        "broker_read_successful": True,
        "staked_external_position": False,
        "bot_inventory": True,
        "source_schema_version": source.get("schema_version"),
        "capture_scope": source.get("capture_scope", {}),
        "evidence_cycles": cycles,
    }


def _extract_orders(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    orders: List[Dict[str, Any]] = []
    for key in ("entry_order", "exit_order"):
        if isinstance(source.get(key), dict):
            orders.append(_normalize_order(source[key]))
    for item in _as_list(source.get("orders")):
        orders.append(_normalize_order(item))
    return orders


def _extract_fills(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    fills: List[Dict[str, Any]] = []
    for key in ("entry_fills", "exit_fills", "fills", "historical_fills", "list_fills"):
        value = source.get(key)
        if isinstance(value, dict):
            value = value.get("fills") or value.get("data") or []
        fills.extend(_normalize_fill(item) for item in _as_list(value))
    return fills


def _select_order(orders: List[Dict[str, Any]], side: str) -> Dict[str, Any]:
    for order in orders:
        if _normalize_side(order.get("side")) == side:
            return order
    return {}


def _select_fills(fills: List[Dict[str, Any]], side: str, order_id: Optional[str]) -> List[Dict[str, Any]]:
    selected: List[Dict[str, Any]] = []
    for fill in fills:
        fill_side = _normalize_side(fill.get("side"))
        fill_order_id = fill.get("order_id") or fill.get("client_order_id")
        side_match = not fill_side or fill_side == side
        order_match = not order_id or not fill_order_id or str(fill_order_id) == str(order_id)
        if side_match and order_match:
            selected.append(fill)
    return selected


def normalize_source(source: Dict[str, Any]) -> Dict[str, Any]:
    if source.get("schema_version") == ONE_CYCLE_READ_ONLY_SCHEMA:
        return _normalize_one_cycle_read_only_source(source)

    orders = _extract_orders(source)
    fills = _extract_fills(source)
    entry_order = _select_order(orders, "BUY")
    exit_order = _select_order(orders, "SELL")
    entry_order_id = entry_order.get("order_id") or entry_order.get("client_order_id")
    exit_order_id = exit_order.get("order_id") or exit_order.get("client_order_id")
    entry_fills = _select_fills(fills, "BUY", entry_order_id)
    exit_fills = _select_fills(fills, "SELL", exit_order_id)

    evidence = {
        "broker_read_successful": bool(source.get("broker_read_successful", True)),
        "staked_external_position": bool(source.get("staked_external_position", False)),
        "external_inventory_classification": source.get("external_inventory_classification"),
        "tradable_by_bot": source.get("tradable_by_bot"),
        "manual_close_allowed": source.get("manual_close_allowed"),
        "bot_inventory": source.get("bot_inventory", not bool(source.get("staked_external_position", False))),
        "local_journal_only_pnl": bool(source.get("local_journal_only_pnl", False)),
        "journal_rows": source.get("journal_rows", []),
        "evidence_cycles": [
            {
                "cycle_id": source.get("cycle_id") or "adapted-cycle-1",
                "product_id": source.get("product_id") or entry_order.get("product_id") or exit_order.get("product_id"),
                "entry": {
                    "order": entry_order,
                    "fills": entry_fills,
                },
                "exit": {
                    "order": exit_order,
                    "fills": exit_fills,
                },
            }
        ] if (entry_order or exit_order or entry_fills or exit_fills) else [],
    }
    return evidence


def _field_sources(source: Dict[str, Any], evidence: Dict[str, Any]) -> Dict[str, Any]:
    cycles = evidence.get("evidence_cycles") or []
    cycle = cycles[0] if cycles else {}
    entry = cycle.get("entry", {}) if isinstance(cycle, dict) else {}
    exit_ = cycle.get("exit", {}) if isinstance(cycle, dict) else {}
    one_cycle_payload = source.get("schema_version") == ONE_CYCLE_READ_ONLY_SCHEMA
    return {
        "one_cycle_read_only_payload": {
            "source_schema_version": source.get("schema_version"),
            "recognized": one_cycle_payload,
            "source_keys": ["cycles[].entry_broker_payload_redacted", "cycles[].exit_broker_payload_redacted"] if one_cycle_payload else [],
            "provides": [
                "direct redacted broker order facts",
                "direct redacted broker fill fact summaries",
                "entry/exit order IDs and product ID from capture scope/cycle",
            ] if one_cycle_payload else [],
        },
        "list_fills_or_historical_fills": {
            "source_keys": [key for key in ("fills", "historical_fills", "list_fills", "entry_fills", "exit_fills") if key in source],
            "provides": ["trade_id/fill_id/entry_id", "order_id", "product_id", "side", "fee/commission", "filled_value/proceeds when present"],
        },
        "order_details_status": {
            "source_keys": [key for key in ("orders", "entry_order", "exit_order") if key in source],
            "provides": ["order_id", "client_order_id", "product_id", "side", "filled_value", "total_fees"],
        },
        "transaction_like_fill_records": {
            "provides": ["commission can normalize to fee", "proceeds can normalize to filled_value"],
        },
        "existing_probe_json": {
            "provides": ["recent_fills_sample can be adapted only when direct ids, fees, and values are present"],
        },
        "local_journals": {
            "sufficient_for_profit_readout": False,
            "reason": "Local journal P/L is not direct broker evidence.",
        },
        "adapted_counts": {
            "entry_fills": len(entry.get("fills") or []),
            "exit_fills": len(exit_.get("fills") or []),
        },
    }


def build_adapter_report(source_path: Path) -> Dict[str, Any]:
    source = _safe_load_json(source_path)
    evidence = normalize_source(source)
    resolver_report = build_report_from_probe(evidence, f"adapted:{source_path}")
    return {
        "verdict": resolver_report["verdict"],
        "profit_readout": resolver_report["profit_readout"],
        "aggregation_allowed": resolver_report["aggregation_allowed"],
        "scaling_allowed": resolver_report["scaling_allowed"],
        "adapted_evidence": evidence,
        "resolver_report": resolver_report,
        "source_map": _field_sources(source, evidence),
        "next_required_action": (
            "With human approval only, capture order details via get_order_status(order_id=...) "
            "and fills via get_historical_fills(product_id=..., order_id=...), redact payloads, "
            "then rerun this adapter offline."
        ),
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


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Coinbase broker evidence adapter")
    parser.add_argument("--source-json", required=True, type=Path, help="Offline Coinbase-like source payload")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args(argv)

    report = build_adapter_report(args.source_json)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("=== Coinbase Broker Evidence Adapter (P2-021B) ===")
        print(f"Verdict: {report['verdict']}")
        print(f"Profit/Readout: {report['profit_readout']}")
        print(f"Aggregation allowed: {report['aggregation_allowed']}")
        print(f"Scaling allowed: {report['scaling_allowed']}")
        print(f"Next required action: {report['next_required_action']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
