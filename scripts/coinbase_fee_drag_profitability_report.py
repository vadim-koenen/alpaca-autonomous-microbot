#!/usr/bin/env python3
"""
Offline Coinbase fee-drag profitability report.

Consumes a numeric-safe broker-backed evidence payload or a saved P2-022D
numeric P/L readout JSON. It never imports broker clients, reads .env, places
orders, or writes logs/state beyond stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from coinbase_fee_aware_pilot import calculate_fee_drag_metrics, public_metrics
from scripts.coinbase_broker_backed_pnl_readout import build_report as build_numeric_pnl_report


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_load_error": str(exc)}
    return payload if isinstance(payload, dict) else {"payload": payload}


def _readout_from_source(path: Path) -> Dict[str, Any]:
    payload = _load_json(path)
    if isinstance(payload.get("cycle_reports"), list) and "profit_readout" in payload:
        return payload
    return build_numeric_pnl_report(path)


def _first_cycle(readout: Dict[str, Any]) -> Dict[str, Any]:
    cycles = readout.get("cycle_reports")
    if isinstance(cycles, list) and cycles and isinstance(cycles[0], dict):
        return cycles[0]
    return {}


def build_report(source_json: Path) -> Dict[str, Any]:
    readout = _readout_from_source(source_json)
    cycle = _first_cycle(readout)
    entry = cycle.get("entry") if isinstance(cycle.get("entry"), dict) else {}
    exit_ = cycle.get("exit") if isinstance(cycle.get("exit"), dict) else {}

    metrics = calculate_fee_drag_metrics(
        entry_value=entry.get("filled_value_or_proceeds"),
        entry_fee=entry.get("total_fees"),
        exit_value=exit_.get("filled_value_or_proceeds"),
        exit_fee=exit_.get("total_fees"),
    )
    public = public_metrics(metrics)
    blockers = list(readout.get("blockers") or [])
    if metrics.get("verdict") == "BLOCKED":
        blockers.extend(metrics.get("blockers") or [])

    report = {
        "verdict": metrics.get("verdict", "BLOCKED"),
        "cycle_id": cycle.get("cycle_id"),
        "product_id": cycle.get("product_id"),
        "profit_readout": readout.get("profit_readout", "unsafe_to_aggregate"),
        "numeric_readout_verdict": readout.get("verdict"),
        "gross_pnl": public.get("gross_pnl"),
        "total_fees": public.get("total_fees"),
        "net_pnl": public.get("net_pnl"),
        "gross_pnl_rate": public.get("gross_pnl_rate"),
        "fee_rate": public.get("fee_rate"),
        "total_fee_rate": public.get("total_fee_rate"),
        "net_pnl_rate": public.get("net_pnl_rate"),
        "observed_entry_fee_rate": public.get("observed_entry_fee_rate"),
        "observed_exit_fee_rate": public.get("observed_exit_fee_rate"),
        "observed_round_trip_fee_rate": public.get("observed_round_trip_fee_rate"),
        "minimum_required_gross_move_rate": public.get("minimum_required_gross_move_rate"),
        "break_even_exit_value": public.get("break_even_exit_value"),
        "required_break_even_exit_value": public.get("required_break_even_exit_value"),
        "micro_trade_fee_drag_detected": public.get("micro_trade_fee_drag_detected", False),
        "recommendation": public.get("recommendation", "do_not_continue_1usd_micro_trades"),
        "scale_allowed": False,
        "scaling_allowed": False,
        "risk_increase": "not_approved",
        "blockers": sorted(set(str(blocker) for blocker in blockers)),
        "source_path": str(source_json),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "safety": {
            "offline_only": True,
            "broker_calls_made": False,
            "live_read_only_used": False,
            "secrets_or_env_read": False,
            "orders_cancels_closes_modifications": False,
            "state_or_log_mutation": False,
            "fill_logger_activation": False,
            "risk_increase": "not_approved",
            "scaling_allowed": False,
        },
    }
    if report["verdict"] == "FEE_DRAG_CONFIRMED":
        report["recommendation"] = "do_not_continue_1usd_micro_trades"
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Coinbase fee-drag profitability report")
    parser.add_argument("--source-json", required=True, type=Path, help="Numeric-safe evidence or readout JSON")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args(argv)

    report = build_report(args.source_json)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("=== Coinbase Fee-Drag Profitability Report ===")
        print(f"Verdict: {report['verdict']}")
        print(f"Cycle: {report['cycle_id']} {report['product_id']}")
        print(f"Gross P/L: {report['gross_pnl']}")
        print(f"Total fees: {report['total_fees']}")
        print(f"Net P/L: {report['net_pnl']}")
        print(f"Break-even exit value: {report['break_even_exit_value']}")
        print(f"Scaling allowed: {report['scaling_allowed']}")
        print(f"Recommendation: {report['recommendation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
