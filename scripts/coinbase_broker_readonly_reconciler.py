#!/usr/bin/env python3
"""Fixture-first Coinbase broker/local-state reconciliation and GO/NO_GO report."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import yaml

try:
    from scripts.bot_heartbeat_watchdog import build_report as build_heartbeat_report
    from scripts.coinbase_manual_review_blocker_watchdog import (
        extract_positions,
        is_manual_review_blocker,
        normalize_symbol,
        parse_time,
        position_symbol,
        read_json,
    )
except ModuleNotFoundError:
    from bot_heartbeat_watchdog import build_report as build_heartbeat_report
    from coinbase_manual_review_blocker_watchdog import (
        extract_positions,
        is_manual_review_blocker,
        normalize_symbol,
        parse_time,
        position_symbol,
        read_json,
    )


SYMBOLS = ("ADA/USD", "SOL/USD", "BTC/USD", "ETH/USD")
AUTHORIZATIONS = {
    "broker_order_authorized": False,
    "live_trading_authorized": False,
    "state_clear_authorized": False,
    "scaling_authorized": False,
    "strategy_change_authorized": False,
}


def _broker_balances(payload: Dict[str, Any]) -> Dict[str, float]:
    balances: Dict[str, float] = {}
    source = payload.get("balances") or payload.get("broker_balances") or []
    if isinstance(source, dict):
        source = [{"asset": key, "available": value} for key, value in source.items()]
    for item in source if isinstance(source, list) else []:
        if not isinstance(item, dict):
            continue
        asset = str(item.get("asset") or item.get("currency") or "").upper()
        try:
            quantity = float(
                item.get("available")
                or item.get("available_balance")
                or item.get("quantity")
                or item.get("qty")
                or 0
            )
        except (TypeError, ValueError):
            quantity = 0.0
        if asset:
            balances[normalize_symbol(f"{asset}/USD")] = quantity
    return balances


def _broker_orders(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    source = payload.get("open_orders") or payload.get("broker_open_orders") or []
    result = []
    for item in source if isinstance(source, list) else []:
        if not isinstance(item, dict):
            continue
        result.append({
            "symbol": normalize_symbol(item.get("symbol") or item.get("product_id")),
            "side": str(item.get("side") or "").lower(),
            "status": str(item.get("status") or "open").lower(),
        })
    return result


def _config_constraints(path: Path) -> Dict[str, Any]:
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        config = {}
    risk = config.get("global_risk") or {}
    crypto = config.get("crypto") or {}
    return {
        "max_open_positions": risk.get("max_open_positions"),
        "max_trades_per_day": risk.get("max_trades_per_day"),
        "max_trade_notional_usd": crypto.get("max_trade_notional_usd"),
        "absolute_hard_trade_cap_usd": crypto.get("absolute_hard_trade_cap_usd"),
        "constraints_unchanged_by_this_report": True,
    }


def build_report(
    *,
    repo_root: Path,
    broker_payload: Optional[Dict[str, Any]] = None,
    process_snapshot: Optional[Path] = None,
    heartbeat_report: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
    emit_alerts: bool = False,
    reports_root: Optional[Path] = None,
    alive_pids: Optional[set[int]] = None,
) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    open_state, open_error = read_json(
        repo_root / "state" / "coinbase" / "open_positions.json",
        {"positions": {}},
    )
    external_state, external_error = read_json(
        repo_root / "state" / "coinbase" / "external_inventory.json",
        {"external_inventory": {}},
    )
    open_positions, _ = extract_positions(open_state)
    external_positions, _ = extract_positions(
        external_state.get("external_inventory", external_state)
        if isinstance(external_state, dict)
        else {}
    )
    local_open = {
        position_symbol(key, value): value for key, value in open_positions.items()
    }
    local_external = {
        position_symbol(key, value): value for key, value in external_positions.items()
    }

    payload = broker_payload or {}
    broker_succeeded = bool(payload.get("broker_query_succeeded"))
    balances = _broker_balances(payload) if broker_succeeded else {}
    orders = _broker_orders(payload) if broker_succeeded else []
    per_symbol: Dict[str, Dict[str, Any]] = {}
    for symbol in SYMBOLS:
        local_is_open = symbol in local_open
        local_is_external = symbol in local_external
        balance = balances.get(symbol, 0.0)
        open_order = any(order["symbol"] == symbol for order in orders)
        broker_open = balance > 0 or open_order
        if local_is_external:
            classification = "local_external_inventory_only"
        elif not broker_succeeded:
            classification = "unknown"
        elif local_is_open and broker_open:
            classification = "local_open_broker_open"
        elif local_is_open and not broker_open:
            classification = "local_open_broker_flat"
        elif not local_is_open and broker_open:
            classification = "local_flat_broker_open"
        else:
            classification = "unknown"
        per_symbol[symbol] = {
            "classification": classification,
            "local_open": local_is_open,
            "local_external_inventory": local_is_external,
            "broker_balance": balance if broker_succeeded else None,
            "broker_open_order": open_order if broker_succeeded else None,
        }

    ada_local_blocker = bool(
        "ADA/USD" in local_open and is_manual_review_blocker(local_open["ADA/USD"])
    )
    ada_broker_flat = bool(
        broker_succeeded
        and balances.get("ADA/USD", 0.0) <= 0
        and not any(order["symbol"] == "ADA/USD" for order in orders)
    )
    ada_clear_candidate = ada_local_blocker and ada_broker_flat

    heartbeat = heartbeat_report or build_heartbeat_report(
        repo_root=repo_root,
        process_snapshot=process_snapshot,
        now=now,
        alive_pids=alive_pids,
        emit_alerts=emit_alerts,
        reports_root=reports_root,
    )
    safe_to_clear_local_ada = bool(
        ada_clear_candidate
        and not heartbeat.get("duplicate_live_process_risk")
        and heartbeat.get("lock_health") == "OK"
    )
    constraints = _config_constraints(repo_root / "config_coinbase_crypto.yaml")
    reasons: List[str] = []
    if not broker_succeeded:
        reasons.append("broker_truth_unknown_fixture_or_captured_json_required")
    if not ada_broker_flat:
        reasons.append("ada_broker_exposure_or_open_order_not_confirmed_absent")
    if heartbeat.get("duplicate_live_process_risk"):
        reasons.append("duplicate_live_process_risk")
    if heartbeat.get("lock_health") != "OK":
        reasons.append("lock_health_not_ok")
    if not heartbeat.get("heartbeat_fresh"):
        reasons.append("heartbeat_not_fresh")
    if not heartbeat.get("file_alerting_active"):
        reasons.append("file_alerting_not_active")
    if constraints.get("max_open_positions") != 1:
        reasons.append("max_open_positions_not_one")
    if ada_local_blocker and not ada_clear_candidate:
        reasons.append("local_ada_blocker_not_safely_clearable")

    go = not reasons
    actions: List[str] = []
    if not broker_succeeded:
        actions.append("Capture balances and open orders through a separately approved read-only broker command.")
    if safe_to_clear_local_ada:
        actions.append("Operator may run the guarded P2-029B ADA local-state clear command.")
    elif ada_clear_candidate:
        actions.append(
            "ADA broker facts are flat, but resolve process/lock guards before guarded local cleanup."
        )
    elif ada_local_blocker:
        actions.append("Do not clear ADA local state until broker flatness is directly confirmed.")
    if heartbeat.get("duplicate_live_process_risk"):
        actions.append("Stop and verify all duplicate live processes before any recovery.")
    if not heartbeat.get("file_alerting_active"):
        actions.append("Run the heartbeat watchdog with --emit-alerts and verify local alert files.")

    return {
        "schema_version": "1.0",
        "generated_at_utc": now.isoformat(),
        "report_class": "coinbase_broker_readonly_reconciliation",
        "broker_readonly_enabled": broker_payload is not None,
        "broker_query_attempted": False,
        "broker_query_succeeded": broker_succeeded,
        "broker_integration_status": "fixture_or_captured_json_only_pending_credential_boundary_review",
        "local_open_positions": sorted(local_open),
        "local_external_inventory": sorted(local_external),
        "broker_balances": (
            [{"symbol": symbol, "quantity": quantity} for symbol, quantity in sorted(balances.items())]
            if broker_succeeded else None
        ),
        "broker_open_orders": orders if broker_succeeded else None,
        "reconciled_symbols": per_symbol,
        "ada_local_blocker_present": ada_local_blocker,
        "ada_clear_candidate": ada_clear_candidate,
        "safe_to_clear_local_ada": safe_to_clear_local_ada,
        "resume_micro_trading_go_no_go": "GO" if go else "NO_GO",
        "safe_to_resume_micro_trading": go,
        "reasons": reasons,
        "required_operator_actions": actions,
        "heartbeat": {
            "fresh": heartbeat.get("heartbeat_fresh"),
            "duplicate_live_process_risk": heartbeat.get("duplicate_live_process_risk"),
            "lock_health": heartbeat.get("lock_health"),
            "file_alerting_active": heartbeat.get("file_alerting_active"),
        },
        "config_constraints": constraints,
        "input_status": {
            "open_positions": open_error or "loaded",
            "external_inventory": external_error or "loaded",
        },
        "default_mode_state_mutation": False,
        **AUTHORIZATIONS,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--broker-json", type=Path)
    parser.add_argument("--process-snapshot", type=Path)
    parser.add_argument("--now")
    parser.add_argument("--emit-alerts", action="store_true")
    parser.add_argument("--go-no-go-report", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    broker_payload = None
    if args.broker_json:
        broker_payload, error = read_json(args.broker_json, {})
        if error:
            broker_payload = {"broker_query_succeeded": False, "input_error": error}
    now = parse_time(args.now) if args.now else datetime.now(timezone.utc)
    report = build_report(
        repo_root=args.repo_root.resolve(),
        broker_payload=broker_payload,
        process_snapshot=args.process_snapshot.resolve() if args.process_snapshot else None,
        now=now,
        emit_alerts=args.emit_alerts,
    )
    if args.go_no_go_report:
        report["go_no_go_report_requested"] = True
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if args.json or not args.output:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
