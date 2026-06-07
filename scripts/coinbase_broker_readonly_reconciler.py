#!/usr/bin/env python3
"""Fixture-first Coinbase broker/local-state reconciliation and GO/NO_GO report."""

from __future__ import annotations

import argparse
import json
import logging
import os
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
    from scripts.utils import load_env
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
    try:
        from utils import load_env
    except ImportError:
        def load_env(): pass


SYMBOLS = ("ADA/USD", "SOL/USD", "BTC/USD", "ETH/USD")
AUTHORIZATIONS = {
    "broker_order_authorized": False,
    "live_trading_authorized": False,
    "state_clear_authorized": False,
    "scaling_authorized": False,
    "strategy_change_authorized": False,
}
DUST_THRESHOLD_ADA = 1.0  # qty below this is considered dust


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


def fetch_live_coinbase_data(repo_root: Path) -> Dict[str, Any]:
    """Fetch real balances and open orders from Coinbase Advanced Trade."""
    try:
        from coinbase.rest import RESTClient
    except ImportError:
        return {"broker_query_succeeded": False, "error": "coinbase-advanced-py not installed"}

    # Use existing utils if possible to load keys safely
    os.environ["ROOT_DIR"] = str(repo_root) # hint for load_env if needed
    load_env()

    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")

    if not api_key or not api_secret or api_key == "replace_me":
        return {"broker_query_succeeded": False, "error": "COINBASE_API_KEY/SECRET not set in environment"}

    try:
        # Suppress noisy SDK warnings
        logging.getLogger("coinbase").setLevel(logging.ERROR)

        client = RESTClient(api_key=api_key, api_secret=api_secret.replace("\\n", "\n"))

        # 1. Get Portfolio
        portfolios = client.get_portfolios()
        if not portfolios:
            return {"broker_query_succeeded": False, "error": "No portfolios returned"}

        p_list = getattr(portfolios, "portfolios", [])
        if not p_list:
             # Try dictionary access if object has no portfolios attr (SDK versions vary)
             if isinstance(portfolios, dict):
                 p_list = portfolios.get("portfolios", [])
             elif hasattr(portfolios, "to_dict"):
                 p_list = portfolios.to_dict().get("portfolios", [])

        if not p_list:
            return {"broker_query_succeeded": False, "error": "Portfolio list empty"}

        p_uuid = p_list[0].get("uuid") if isinstance(p_list[0], dict) else getattr(p_list[0], "uuid", "")
        if not p_uuid:
            return {"broker_query_succeeded": False, "error": "Could not resolve portfolio UUID"}

        # 2. Get Breakdown (Spot Positions)
        breakdown = client.get_portfolio_breakdown(portfolio_uuid=p_uuid)
        bd_dict = {}
        if hasattr(breakdown, "to_dict"):
            bd_dict = breakdown.to_dict()
        elif isinstance(breakdown, dict):
            bd_dict = breakdown

        spot_positions = bd_dict.get("breakdown", {}).get("spot_positions", [])
        balances_list = []
        for sp in spot_positions:
            balances_list.append({
                "asset": sp.get("asset"),
                "available": sp.get("total_balance_crypto")
            })

        # 3. Get Open Orders
        orders_resp = client.list_orders(order_status=["OPEN"])
        orders_list = []
        o_source = []
        if hasattr(orders_resp, "to_dict"):
            o_source = orders_resp.to_dict().get("orders", [])
        elif isinstance(orders_resp, dict):
            o_source = orders_resp.get("orders", [])

        for o in o_source:
            orders_list.append({
                "product_id": o.get("product_id"),
                "side": o.get("side"),
                "status": o.get("status")
            })

        return {
            "broker_query_succeeded": True,
            "balances": balances_list,
            "open_orders": orders_list,
            "broker_truth_source": "coinbase_advanced_trade_api",
            "broker_calls_made": True,
            "real_broker_query_implemented": True
        }

    except Exception as e:
        return {"broker_query_succeeded": False, "error": f"API call failed: {str(e)}"}


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
    live_read_only: bool = False,
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

    broker_positions_nonzero = []
    for sym, qty in sorted(balances.items()):
        if qty > 0:
            broker_positions_nonzero.append({"symbol": sym, "quantity": qty})

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
    ada_broker_qty = balances.get("ADA/USD", 0.0)
    ada_broker_present = ada_broker_qty > DUST_THRESHOLD_ADA
    ada_broker_flat = bool(
        broker_succeeded
        and not ada_broker_present
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
        reasons.append("broker_truth_unknown_live_read_only_required")
    if broker_succeeded and not ada_broker_flat:
        reasons.append("ada_broker_exposure_or_open_order_still_present")
    if broker_succeeded and any(orders):
        reasons.append("open_broker_orders_exist")
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
    if ada_local_blocker and not ada_clear_candidate and broker_succeeded:
        reasons.append("local_ada_blocker_requires_broker_close_first")

    safe_to_resume = False
    if broker_succeeded and not reasons and not local_open and not orders:
        safe_to_resume = "READY_FOR_OPERATOR_APPROVAL"

    go = bool(safe_to_resume == "READY_FOR_OPERATOR_APPROVAL")

    actions: List[str] = []
    if not broker_succeeded:
        actions.append("Run with --live-read-only to verify broker truth.")
    if ada_broker_present:
        actions.append("ADA still present at broker. Operator must manually close/convert ADA or implement controlled close workflow.")
    if safe_to_clear_local_ada:
        actions.append("Operator may run the guarded P2-029B ADA local-state clear command.")
    elif ada_clear_candidate:
        actions.append(
            "ADA broker facts are flat, but resolve process/lock guards before guarded local cleanup."
        )
    elif ada_local_blocker and broker_succeeded:
        actions.append("Do not clear ADA local state until broker position is closed/sold.")
    if heartbeat.get("duplicate_live_process_risk"):
        actions.append("Stop and verify all duplicate live processes before any recovery.")
    if not heartbeat.get("file_alerting_active"):
        actions.append("Run the heartbeat watchdog with --emit-alerts and verify local alert files.")

    return {
        "schema_version": "1.1",
        "timestamp_utc": now.isoformat(),
        "report_class": "coinbase_broker_readonly_reconciliation",
        "broker": "coinbase",
        "live_read_only": live_read_only,
        "broker_calls_made": bool(payload.get("broker_calls_made", False)),
        "order_mutation_performed": False,
        "state_mutation_performed": False,
        "restart_performed": False,
        "broker_readonly_enabled": broker_payload is not None or live_read_only,
        "broker_query_attempted": live_read_only,
        "broker_query_succeeded": broker_succeeded,
        "broker_integration_status": payload.get("error", "fixture_first" if not live_read_only else "live_success"),
        "stop_trading_present": repo_root.joinpath("runtime", "STOP_TRADING").exists(),
        "local_open_positions": sorted(local_open),
        "local_external_inventory": sorted(local_external),
        "broker_positions_nonzero": broker_positions_nonzero if broker_succeeded else None,
        "broker_open_orders": orders if broker_succeeded else None,
        "reconciled_symbols": per_symbol,
        "ada_broker_qty": ada_broker_qty if broker_succeeded else None,
        "ada_broker_present": ada_broker_present if broker_succeeded else None,
        "ada_local_blocker_present": ada_local_blocker,
        "ada_clear_candidate": ada_clear_candidate,
        "safe_to_clear_local_ada": safe_to_clear_local_ada,
        "resume_micro_trading_go_no_go": "GO" if go else "NO_GO",
        "safe_to_resume_micro_trading": safe_to_resume,
        "external_inventory_symbols": sorted(local_external),
        "local_broker_mismatches": [s for s, v in per_symbol.items() if "mismatch" in v["classification"] or v["classification"].startswith("local_open_broker_flat") or v["classification"].startswith("local_flat_broker_open")],
        "reasons": reasons,
        "required_operator_actions": actions,
        "recommended_action": actions[0] if actions else "Continue normal monitoring.",
        "heartbeat": {
            "fresh": heartbeat.get("heartbeat_fresh"),
            "duplicate_live_process_risk": heartbeat.get("duplicate_live_process_risk"),
            "lock_health": heartbeat.get("lock_health"),
            "file_alerting_active": bool(heartbeat.get("file_alerting_active")),
        },
        "config_constraints": constraints,
        "input_status": {
            "open_positions": open_error or "loaded",
            "external_inventory": external_error or "loaded",
        },
        **AUTHORIZATIONS,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--broker-json", type=Path)
    parser.add_argument("--live-read-only", action="store_true")
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
            broker_payload = {"broker_query_succeeded": False, "error": f"JSON read error: {error}"}
    elif args.live_read_only:
        broker_payload = fetch_live_coinbase_data(args.repo_root)

    now = parse_time(args.now) if args.now else datetime.now(timezone.utc)
    report = build_report(
        repo_root=args.repo_root.resolve(),
        broker_payload=broker_payload,
        process_snapshot=args.process_snapshot.resolve() if args.process_snapshot else None,
        now=now,
        emit_alerts=args.emit_alerts,
        live_read_only=args.live_read_only,
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
