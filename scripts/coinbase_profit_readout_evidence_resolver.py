#!/usr/bin/env python3
"""
P2-021A - Offline Coinbase profit readout direct-evidence resolver.

This script is intentionally offline-only. It reads fixture/probe JSON supplied
by the operator, never imports broker clients, never reads .env, never writes
state/logs, and never places/cancels/closes/modifies orders.

It answers one narrow question:
Can profit_readout move beyond unsafe_to_aggregate for a closed bot-owned cycle
using direct broker evidence only?
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


MEASURED_READOUT = "measured_broker_backed_limited"
UNSAFE_READOUT = "unsafe_to_aggregate"

ORDER_ID_KEYS = ("order_id", "client_order_id", "coinbase_order_id")
FILL_ID_KEYS = ("trade_id", "fill_id", "entry_id", "fill_key")
FEE_KEYS = ("fee", "commission", "total_fees", "total_fee")
VALUE_KEYS = ("filled_value", "proceeds", "sell_proceeds", "notional", "quote_size", "quote_value")


def _safe_load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_load_error": str(exc)}


def _normalize_side(value: Any) -> str:
    return str(value or "").strip().upper()


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def _nonzero_numberish(value: Any) -> bool:
    if not _present(value):
        return False
    try:
        return float(str(value).strip()) != 0.0
    except Exception:
        return True


def _first_present(obj: Dict[str, Any], keys: Sequence[str]) -> Tuple[Optional[str], Any]:
    for key in keys:
        if key in obj and _present(obj.get(key)):
            return key, obj.get(key)
    return None, None


def _as_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _unwrap_order(payload: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(payload.get("order"), dict):
        return payload["order"]
    return payload


def _extract_fills(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        if isinstance(payload.get("fills"), list):
            return _as_list(payload.get("fills"))
        if isinstance(payload.get("data"), list):
            return _as_list(payload.get("data"))
    if isinstance(payload, list):
        return _as_list(payload)
    return []


def _leg_from_recent_fill(fill: Dict[str, Any]) -> Dict[str, Any]:
    order_id = fill.get("order_id") or fill.get("client_order_id")
    return {
        "order": {
            "order_id": order_id,
            "client_order_id": fill.get("client_order_id"),
            "product_id": fill.get("product_id"),
            "side": fill.get("side"),
            "status": "FILLED",
            "filled_value": fill.get("filled_value") or fill.get("proceeds"),
            "total_fees": fill.get("total_fees") or fill.get("fee") or fill.get("commission"),
        },
        "fills": [fill],
    }


def _cycles_from_probe(probe: Dict[str, Any]) -> List[Dict[str, Any]]:
    if isinstance(probe.get("evidence_cycles"), list):
        return _as_list(probe.get("evidence_cycles"))

    entry_order = probe.get("entry_order")
    exit_order = probe.get("exit_order")
    if isinstance(entry_order, dict) or isinstance(exit_order, dict):
        return [{
            "cycle_id": probe.get("cycle_id") or "cycle-1",
            "product_id": probe.get("product_id"),
            "entry": {
                "order": entry_order or {},
                "fills": probe.get("entry_fills") or [],
            },
            "exit": {
                "order": exit_order or {},
                "fills": probe.get("exit_fills") or [],
            },
        }]

    recent_fills = _as_list(probe.get("recent_fills_sample"))
    buys = [f for f in recent_fills if _normalize_side(f.get("side")) == "BUY"]
    sells = [f for f in recent_fills if _normalize_side(f.get("side")) == "SELL"]
    if buys or sells:
        return [{
            "cycle_id": probe.get("cycle_id") or "recent-fills-sample",
            "product_id": probe.get("product_id") or (buys + sells)[0].get("product_id"),
            "entry": _leg_from_recent_fill(buys[0]) if buys else {},
            "exit": _leg_from_recent_fill(sells[0]) if sells else {},
        }]

    return []


def _leg_payloads(leg: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    order = _unwrap_order(leg.get("order") or leg.get("order_status") or {})
    fills = _extract_fills(leg.get("fills") or leg.get("historical_fills") or leg.get("list_fills") or [])
    return order if isinstance(order, dict) else {}, fills


def _leg_side(order: Dict[str, Any], fills: List[Dict[str, Any]], fallback: str) -> str:
    side = _normalize_side(order.get("side"))
    if side:
        return side
    for fill in fills:
        side = _normalize_side(fill.get("side"))
        if side:
            return side
    return fallback


def _field_available(order: Dict[str, Any], fills: List[Dict[str, Any]], keys: Sequence[str], *, nonzero: bool = False) -> bool:
    _, order_value = _first_present(order, keys)
    if (nonzero and _nonzero_numberish(order_value)) or (not nonzero and _present(order_value)):
        return True
    for fill in fills:
        _, fill_value = _first_present(fill, keys)
        if (nonzero and _nonzero_numberish(fill_value)) or (not nonzero and _present(fill_value)):
            return True
    return False


def _fill_ids_available(fills: List[Dict[str, Any]]) -> bool:
    if not fills:
        return False
    return all(_first_present(fill, FILL_ID_KEYS)[0] is not None for fill in fills)


def _order_id_available(order: Dict[str, Any], fills: List[Dict[str, Any]]) -> bool:
    if _first_present(order, ORDER_ID_KEYS)[0] is not None:
        return True
    return any(_first_present(fill, ORDER_ID_KEYS)[0] is not None for fill in fills)


def _evaluate_leg(leg: Dict[str, Any], fallback_side: str) -> Dict[str, Any]:
    order, fills = _leg_payloads(leg)
    side = _leg_side(order, fills, fallback_side)
    order_id_available = _order_id_available(order, fills)
    fill_id_available = _fill_ids_available(fills)
    fee_available = _field_available(order, fills, FEE_KEYS, nonzero=True)
    value_available = _field_available(order, fills, VALUE_KEYS, nonzero=True)
    evidence_available = all([
        side in ("BUY", "SELL"),
        order_id_available,
        fill_id_available,
        fee_available,
        value_available,
    ])
    return {
        "side": side,
        "order_id_available": order_id_available,
        "trade_or_fill_id_available": fill_id_available,
        "fee_available": fee_available,
        "proceeds_or_filled_value_available": value_available,
        "fills_count": len(fills),
        "evidence_available": evidence_available,
    }


def _cycle_missing_fields(cycle: Dict[str, Any], entry: Dict[str, Any], exit_: Dict[str, Any]) -> List[str]:
    cycle_id = cycle.get("cycle_id") or "cycle"
    missing: List[str] = []
    for label, leg in (("entry", entry), ("exit", exit_)):
        if not leg["order_id_available"]:
            missing.append(f"{cycle_id}.{label}.direct_order_id")
        if not leg["trade_or_fill_id_available"]:
            missing.append(f"{cycle_id}.{label}.direct_trade_or_fill_id")
        if not leg["fee_available"]:
            missing.append(f"{cycle_id}.{label}.direct_fee")
        if not leg["proceeds_or_filled_value_available"]:
            missing.append(f"{cycle_id}.{label}.direct_proceeds_or_filled_value")
        if label == "entry" and leg["side"] != "BUY":
            missing.append(f"{cycle_id}.entry.side_buy")
        if label == "exit" and leg["side"] != "SELL":
            missing.append(f"{cycle_id}.exit.side_sell")
    return missing


def _contains_local_journal_only_pnl(probe: Dict[str, Any]) -> bool:
    if probe.get("local_journal_only_pnl") is True:
        return True
    for row in _as_list(probe.get("journal_rows")):
        if any(key in row for key in ("pnl", "realized_pnl", "profit", "net_pnl")):
            return True
    return False


def _bool_or_default(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "1", "yes", "y"):
            return True
        if text in ("false", "0", "no", "n"):
            return False
    return default


def build_report_from_probe(probe: Dict[str, Any], probe_source: str = "<memory>") -> Dict[str, Any]:
    staked_external_position = _bool_or_default(probe.get("staked_external_position"), False)
    bot_inventory = _bool_or_default(probe.get("bot_inventory"), not staked_external_position)
    local_journal_only_pnl = _contains_local_journal_only_pnl(probe)
    cycles = _cycles_from_probe(probe)

    cycle_reports: List[Dict[str, Any]] = []
    required_missing_fields: List[str] = []
    complete_cycles = 0
    entry_available = False
    exit_available = False
    fee_available = False
    value_available = False
    order_id_available = False
    fill_id_available = False

    for cycle in cycles:
        entry = _evaluate_leg(cycle.get("entry") or {}, "BUY")
        exit_ = _evaluate_leg(cycle.get("exit") or {}, "SELL")
        missing = _cycle_missing_fields(cycle, entry, exit_)
        required_missing_fields.extend(missing)
        complete = not missing
        complete_cycles += 1 if complete else 0
        entry_available = entry_available or entry["evidence_available"]
        exit_available = exit_available or exit_["evidence_available"]
        fee_available = fee_available or (entry["fee_available"] and exit_["fee_available"])
        value_available = value_available or (entry["proceeds_or_filled_value_available"] and exit_["proceeds_or_filled_value_available"])
        order_id_available = order_id_available or (entry["order_id_available"] and exit_["order_id_available"])
        fill_id_available = fill_id_available or (entry["trade_or_fill_id_available"] and exit_["trade_or_fill_id_available"])
        cycle_reports.append({
            "cycle_id": cycle.get("cycle_id") or "cycle",
            "product_id": cycle.get("product_id"),
            "entry": entry,
            "exit": exit_,
            "complete_direct_evidence": complete,
            "missing_fields": missing,
        })

    blockers: List[str] = []
    if probe.get("_load_error"):
        blockers.append(f"Could not load fixture/probe JSON: {probe['_load_error']}")
    if staked_external_position or bot_inventory is False:
        blockers.append("Inventory is external/staked and excluded from bot P/L aggregation.")
    if local_journal_only_pnl:
        blockers.append("Local journal P/L is present but is not direct broker evidence.")
    if not cycles:
        blockers.append("No direct entry+exit evidence cycles supplied.")
    if required_missing_fields:
        blockers.append("One or more required direct broker evidence fields are missing.")

    direct_complete = (
        bool(cycles)
        and complete_cycles == len(cycles)
        and not required_missing_fields
        and not staked_external_position
        and bot_inventory is True
        and not local_journal_only_pnl
    )

    if direct_complete:
        verdict = "EVIDENCE_RESOLVED"
        profit_readout = MEASURED_READOUT
        evidence_level = "L4_direct_entry_exit_broker_facts"
        aggregation_allowed = True
        next_action = (
            "Direct entry+exit broker evidence is complete for supplied closed bot-owned cycles. "
            "Aggregation is allowed for these limited cycles only. Risk scaling remains not approved."
        )
    else:
        verdict = "BLOCKED"
        profit_readout = UNSAFE_READOUT
        evidence_level = "L0_local_only_or_incomplete" if local_journal_only_pnl else "L2_or_L3_incomplete_direct_evidence"
        if staked_external_position or bot_inventory is False:
            evidence_level = "EXTERNAL_LOCKED_INVENTORY_EXCLUDED"
            next_action = (
                "Exclude staked external inventory from bot P/L and bot-tradable inventory. "
                "Do not close or remediate staked SOL. Continue evidence resolution only for closed bot-owned cycles."
            )
        else:
            next_action = (
                "Recover missing direct broker facts from offline captured order status/details and list-fills payloads. "
                "Future human-approved live-read-only work should query get_historical_fills(product_id=..., order_id=...) "
                "and get_order_status(order_id=...) for the affected bot-owned orders, then rerun this resolver offline."
            )
        aggregation_allowed = False

    # Risk increase remains a separate human gate even after direct evidence is complete.
    scaling_allowed = False

    return {
        "verdict": verdict,
        "profit_readout": profit_readout,
        "aggregation_allowed": aggregation_allowed,
        "scaling_allowed": scaling_allowed,
        "evidence_level": evidence_level,
        "required_missing_fields": sorted(set(required_missing_fields)),
        "entry_evidence_available": entry_available,
        "exit_evidence_available": exit_available,
        "direct_fee_available": fee_available,
        "direct_proceeds_or_filled_value_available": value_available,
        "direct_order_id_available": order_id_available,
        "direct_trade_or_fill_id_available": fill_id_available,
        "staked_external_position": staked_external_position,
        "bot_inventory": bot_inventory,
        "next_required_action": next_action,
        "blockers": blockers,
        "cycles_evaluated": len(cycles),
        "complete_direct_cycles": complete_cycles,
        "local_journal_only_pnl": local_journal_only_pnl,
        "cycle_reports": cycle_reports,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "probe_source": probe_source,
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


def build_report(probe_path: Path) -> Dict[str, Any]:
    probe = _safe_load_json(probe_path)
    return build_report_from_probe(probe, str(probe_path))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Coinbase profit readout evidence resolver")
    parser.add_argument("--probe-json", required=True, type=Path, help="Fixture/probe JSON to inspect")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args(argv)

    report = build_report(args.probe_json)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("=== Coinbase Profit Readout Evidence Resolver (P2-021A) ===")
        print(f"Verdict: {report['verdict']}")
        print(f"Profit/Readout: {report['profit_readout']}")
        print(f"Evidence level: {report['evidence_level']}")
        print(f"Aggregation allowed: {report['aggregation_allowed']}")
        print(f"Scaling allowed: {report['scaling_allowed']}")
        print(f"Entry evidence available: {report['entry_evidence_available']}")
        print(f"Exit evidence available: {report['exit_evidence_available']}")
        print(f"Direct fee available: {report['direct_fee_available']}")
        print(f"Direct proceeds/filled_value available: {report['direct_proceeds_or_filled_value_available']}")
        print(f"Staked external position: {report['staked_external_position']}")
        print(f"Bot inventory: {report['bot_inventory']}")
        print("Missing fields:")
        for field in report["required_missing_fields"]:
            print(f"  - {field}")
        print("Next required action:")
        print(f"  {report['next_required_action']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
