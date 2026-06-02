#!/usr/bin/env python3
"""
Offline Coinbase dashboard observation loop.

Runs a finite, no-sleep observation pass over the local P2-024B opportunity
dashboard. It reads local JSON inputs only and never calls brokers, reads
secrets, restarts runtime, or mutates state/log files.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(ROOT))

from scripts.coinbase_opportunity_dashboard import DEFAULT_HEARTBEAT, build_dashboard


SCHEMA_VERSION = "p2-024c.coinbase_dashboard_observation_loop.v1"
MODE = "offline_read_only_dashboard_observation_loop"
TRADE_PERMISSION = "none"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def next_required_action(verdict: str, runtime_blockers: Iterable[str]) -> str:
    blockers = list(runtime_blockers or [])
    if blockers:
        return "investigate_offline_runtime_blocker_no_trade_action"
    if verdict == "SIT_OUT_CONFIRMED":
        return "continue_observing_until_btc_eth_signal_clears_trend_fee_and_risk_gates"
    if verdict == "READY_TO_OBSERVE":
        return "observe_candidate_only_no_trade_permission"
    if verdict == "WAIT_FOR_SIGNAL":
        return "wait_for_cleaner_signal_no_trade_action"
    if verdict == "OBSERVE_EXISTING_POSITION":
        return "observe_existing_position_no_new_entry"
    return "refresh_local_evidence_no_trade_action"


def _symbol_summary(symbols: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in symbols:
        rows.append({
            "symbol": row.get("symbol"),
            "local_regime": row.get("local_regime"),
            "allowed_strategies": list(row.get("allowed_strategies") or []),
            "trend_advisory_action": row.get("trend_advisory_action"),
            "fee_drag_status": row.get("fee_drag_status"),
            "opportunity_verdict": row.get("opportunity_verdict"),
            "reason": list(row.get("reason") or []),
        })
    return rows


def _observation_from_dashboard(iteration: int, dashboard: Dict[str, Any]) -> Dict[str, Any]:
    verdict = str(dashboard.get("verdict") or "UNKNOWN")
    runtime = dashboard.get("runtime") if isinstance(dashboard.get("runtime"), dict) else {}
    sizing = dashboard.get("sizing") if isinstance(dashboard.get("sizing"), dict) else {}
    profit = dashboard.get("profit_readout") if isinstance(dashboard.get("profit_readout"), dict) else {}
    safety = dashboard.get("safety") if isinstance(dashboard.get("safety"), dict) else {}
    symbols = dashboard.get("symbols") if isinstance(dashboard.get("symbols"), list) else []
    expansion = (
        dashboard.get("controlled_live_symbol_expansion")
        if isinstance(dashboard.get("controlled_live_symbol_expansion"), dict)
        else {}
    )

    return {
        "iteration": iteration,
        "observed_at": now_iso(),
        "dashboard_generated_at": dashboard.get("generated_at"),
        "verdict": verdict,
        "trade_permission": dashboard.get("trade_permission", TRADE_PERMISSION),
        "live_order_actions_allowed": bool(dashboard.get("live_order_actions_allowed", False)),
        "next_required_action": next_required_action(verdict, runtime.get("blockers") or []),
        "final_trade_notional": sizing.get("final_trade_notional"),
        "eligible_symbols": list(sizing.get("eligible_symbols") or []),
        "excluded_symbols": list(sizing.get("excluded_symbols") or []),
        "expanded_live_symbols": list(expansion.get("expanded_live_symbols") or sizing.get("expanded_live_symbols") or []),
        "shared_caps": bool(expansion.get("shared_caps", True)),
        "symbols": _symbol_summary(symbols),
        "profit_readout": {
            "global_status": profit.get("global_status"),
            "aggregation_allowed": bool(profit.get("aggregation_allowed", False)),
            "scaling_allowed": bool(profit.get("scaling_allowed", False)),
            "latest_measured_cycle": profit.get("latest_measured_cycle"),
        },
        "runtime": {
            "broker": runtime.get("broker"),
            "mode": runtime.get("mode"),
            "open_positions": runtime.get("open_positions"),
            "risk_halt_active": runtime.get("risk_halt_active"),
            "kill_switch_present": runtime.get("kill_switch_present"),
            "blockers": list(runtime.get("blockers") or []),
        },
        "safety": {
            "offline_only": bool(safety.get("offline_only", True)),
            "broker_calls_made": bool(safety.get("broker_calls_made", False)),
            "live_read_only_used": bool(safety.get("live_read_only_used", False)),
            "order_actions_allowed": bool(safety.get("order_actions_allowed", False)),
            "sizing_changes_allowed": bool(safety.get("sizing_changes_allowed", False)),
            "risk_override_allowed": bool(safety.get("risk_override_allowed", False)),
            "sol_excluded": bool(safety.get("sol_excluded", False)),
            "secrets_or_env_read": bool(safety.get("secrets_or_env_read", False)),
            "state_or_log_mutation": bool(safety.get("state_or_log_mutation", False)),
            "symbol_expansion": bool(safety.get("symbol_expansion", False)),
            "strategy_auto_trigger_from_trends": bool(
                safety.get("strategy_auto_trigger_from_trends", False)
            ),
        },
    }


def _aggregate(observations: List[Dict[str, Any]]) -> Dict[str, Any]:
    verdict_counts = Counter(str(row.get("verdict") or "UNKNOWN") for row in observations)
    last = observations[-1] if observations else {}
    stable_verdict = (
        str(last.get("verdict") or "UNKNOWN")
        if len(verdict_counts) == 1 and observations
        else "MIXED"
    )
    symbols = last.get("symbols") if isinstance(last.get("symbols"), list) else []

    return {
        "stable_verdict": stable_verdict,
        "current_style_verdict": str(last.get("verdict") or "UNKNOWN"),
        "verdict_counts": dict(sorted(verdict_counts.items())),
        "next_required_action": str(last.get("next_required_action") or "refresh_local_evidence_no_trade_action"),
        "final_trade_notional": last.get("final_trade_notional"),
        "trade_permission": last.get("trade_permission", TRADE_PERMISSION),
        "live_order_actions_allowed": bool(last.get("live_order_actions_allowed", False)),
        "eligible_symbols": list(last.get("eligible_symbols") or []),
        "excluded_symbols": list(last.get("excluded_symbols") or []),
        "expanded_live_symbols": list(last.get("expanded_live_symbols") or last.get("eligible_symbols") or []),
        "shared_caps": bool(last.get("shared_caps", True)),
        "symbols": symbols,
        "btc_eth_only": [row.get("symbol") for row in symbols] == ["BTC/USD", "ETH/USD"],
        "expanded_basket_enabled": len([row.get("symbol") for row in symbols]) > 2,
        "sol_excluded": all(row.get("symbol") != "SOL/USD" for row in symbols),
        "profit_readout": last.get("profit_readout", {}),
    }


def build_observation_loop(
    *,
    heartbeat_path: Path = DEFAULT_HEARTBEAT,
    trend_source_json: Optional[Path] = None,
    quote_source_json: Optional[Path] = None,
    fee_drag_source_json: Optional[Path] = None,
    include_logs: bool = False,
    iterations: int = 3,
    offline_only: bool = True,
) -> Dict[str, Any]:
    safe_iterations = max(1, min(int(iterations or 1), 20))
    observations: List[Dict[str, Any]] = []
    for idx in range(safe_iterations):
        dashboard = build_dashboard(
            heartbeat_path=heartbeat_path,
            trend_source_json=trend_source_json,
            quote_source_json=quote_source_json,
            fee_drag_source_json=fee_drag_source_json,
            include_logs=include_logs,
            offline_only=offline_only,
        )
        observations.append(_observation_from_dashboard(idx + 1, dashboard))

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "mode": MODE,
        "iterations_requested": iterations,
        "iterations_executed": safe_iterations,
        "loop_control": {
            "finite_iterations": True,
            "sleep_performed": False,
            "interval_seconds": "0",
            "writes_files": False,
        },
        "aggregate": _aggregate(observations),
        "observations": observations,
        "safety": {
            "offline_only": bool(offline_only),
            "broker_calls_made": False,
            "live_read_only_used": False,
            "order_actions_allowed": False,
            "sizing_changes_allowed": False,
            "risk_override_allowed": False,
            "secrets_or_env_read": False,
            "state_or_log_mutation": False,
            "runtime_restart_performed": False,
            "runtime_control_touched": False,
            "symbol_expansion": any(row.get("safety", {}).get("symbol_expansion") is True for row in observations),
            "sol_excluded": all(row.get("safety", {}).get("sol_excluded") is True for row in observations),
            "strategy_auto_trigger_from_trends": False,
        },
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run offline Coinbase dashboard observation loop")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--heartbeat", type=Path, default=DEFAULT_HEARTBEAT, help="Local heartbeat JSON path")
    parser.add_argument("--trend-source-json", type=Path, default=None, help="Local trend/advisory source JSON")
    parser.add_argument("--quote-source-json", type=Path, default=None, help="Local quote health source JSON")
    parser.add_argument("--fee-drag-source-json", type=Path, default=None, help="Local fee-drag evidence/report JSON")
    parser.add_argument("--include-logs", action="store_true", help="Record that log context was requested")
    parser.add_argument("--iterations", type=int, default=3, help="Finite offline observations to compose")
    args = parser.parse_args(argv)

    loop = build_observation_loop(
        heartbeat_path=args.heartbeat,
        trend_source_json=args.trend_source_json,
        quote_source_json=args.quote_source_json,
        fee_drag_source_json=args.fee_drag_source_json,
        include_logs=args.include_logs,
        iterations=args.iterations,
    )
    if args.json:
        print(json.dumps(loop, indent=2, sort_keys=True))
    else:
        aggregate = loop["aggregate"]
        print("=== Coinbase Dashboard Observation Loop ===")
        print(f"Iterations: {loop['iterations_executed']}")
        print(f"Stable verdict: {aggregate['stable_verdict']}")
        print(f"Current-style verdict: {aggregate['current_style_verdict']}")
        print(f"Next required action: {aggregate['next_required_action']}")
        print(f"Final notional: {aggregate['final_trade_notional']}")
        print(f"Trade permission: {aggregate['trade_permission']}")
        for row in aggregate["symbols"]:
            print(
                f"{row['symbol']}: {row['opportunity_verdict']} "
                f"regime={row['local_regime']} action={row['trend_advisory_action']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
