#!/usr/bin/env python3
"""
Offline Coinbase operator digest.

Builds a concise operator-facing digest from the P2-024C observation loop. It
does not call brokers, read secrets, restart services, place trades, or mutate
state/log files.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(ROOT))

from scripts.coinbase_dashboard_observation_loop import build_observation_loop
from scripts.coinbase_opportunity_dashboard import DEFAULT_HEARTBEAT


SCHEMA_VERSION = "p2-024c.coinbase_operator_digest.v1"
MODE = "offline_read_only_operator_digest"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> Tuple[Dict[str, Any], Optional[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, str(exc)
    if isinstance(payload, dict):
        return payload, None
    return {"payload": payload}, None


def _headline(verdict: str) -> str:
    if verdict == "SIT_OUT_CONFIRMED":
        return "Sit out confirmed; keep observing BTC/USD and ETH/USD only."
    if verdict == "READY_TO_OBSERVE":
        return "Candidate context observed; no live trade permission is granted."
    if verdict == "WAIT_FOR_SIGNAL":
        return "Wait for a cleaner local signal before any separate strategy/risk review."
    if verdict == "OBSERVE_EXISTING_POSITION":
        return "Existing position observed; no new-entry action from the dashboard."
    if verdict == "BLOCKED":
        return "Dashboard blocked; investigate local blocker without touching runtime."
    return "Evidence incomplete; refresh local dashboard inputs offline."


def build_operator_digest(observation_loop: Dict[str, Any]) -> Dict[str, Any]:
    aggregate = observation_loop.get("aggregate") if isinstance(observation_loop.get("aggregate"), dict) else {}
    current_verdict = str(aggregate.get("current_style_verdict") or "UNKNOWN")
    next_action = str(aggregate.get("next_required_action") or "refresh_local_evidence_no_trade_action")
    symbols = aggregate.get("symbols") if isinstance(aggregate.get("symbols"), list) else []
    profit = aggregate.get("profit_readout") if isinstance(aggregate.get("profit_readout"), dict) else {}
    latest_cycle = profit.get("latest_measured_cycle") if isinstance(profit.get("latest_measured_cycle"), dict) else {}

    summary_lines = [
        _headline(current_verdict),
        f"next_required_action={next_action}",
        f"final_trade_notional={aggregate.get('final_trade_notional')}",
        "trade_permission=none",
        "profit_readout=unsafe_to_aggregate",
        "risk_increase=not_approved",
    ]
    for row in symbols:
        summary_lines.append(
            f"{row.get('symbol')}: {row.get('opportunity_verdict')} "
            f"regime={row.get('local_regime')} action={row.get('trend_advisory_action')}"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "mode": MODE,
        "headline": _headline(current_verdict),
        "current_style_verdict": current_verdict,
        "stable_verdict": aggregate.get("stable_verdict"),
        "next_required_action": next_action,
        "final_trade_notional": aggregate.get("final_trade_notional"),
        "trade_permission": "none",
        "live_order_actions_allowed": False,
        "btc_eth_only": bool(aggregate.get("btc_eth_only", False)),
        "sol_excluded": bool(aggregate.get("sol_excluded", False)),
        "symbols": symbols,
        "profit_readout": {
            "global_status": profit.get("global_status", "unsafe_to_aggregate"),
            "aggregation_allowed": bool(profit.get("aggregation_allowed", False)),
            "scaling_allowed": bool(profit.get("scaling_allowed", False)),
            "latest_measured_cycle": latest_cycle,
        },
        "summary_lines": summary_lines,
        "operator_digest_text": "\n".join(summary_lines),
        "safety": {
            "offline_only": True,
            "broker_calls_made": False,
            "live_read_only_used": False,
            "order_actions_allowed": False,
            "sizing_changes_allowed": False,
            "risk_override_allowed": False,
            "secrets_or_env_read": False,
            "state_or_log_mutation": False,
            "runtime_restart_performed": False,
            "runtime_control_touched": False,
            "symbol_expansion": False,
            "sol_excluded": bool(aggregate.get("sol_excluded", False)),
            "strategy_auto_trigger_from_trends": False,
        },
        "source_observation": {
            "schema_version": observation_loop.get("schema_version"),
            "iterations_executed": observation_loop.get("iterations_executed"),
            "verdict_counts": aggregate.get("verdict_counts", {}),
        },
    }


def build_digest_from_inputs(
    *,
    observation_json: Optional[Path] = None,
    heartbeat_path: Path = DEFAULT_HEARTBEAT,
    trend_source_json: Optional[Path] = None,
    fee_drag_source_json: Optional[Path] = None,
    iterations: int = 3,
) -> Dict[str, Any]:
    if observation_json is not None:
        observation_loop, error = _load_json(observation_json)
        if error:
            observation_loop = {
                "schema_version": "p2-024c.coinbase_dashboard_observation_loop.v1",
                "iterations_executed": 0,
                "aggregate": {
                    "current_style_verdict": "UNKNOWN",
                    "stable_verdict": "UNKNOWN",
                    "next_required_action": "refresh_local_evidence_no_trade_action",
                    "final_trade_notional": None,
                    "trade_permission": "none",
                    "btc_eth_only": False,
                    "sol_excluded": False,
                    "profit_readout": {"global_status": "unsafe_to_aggregate"},
                    "symbols": [],
                    "verdict_counts": {},
                },
                "load_error": error,
            }
        return build_operator_digest(observation_loop)

    observation_loop = build_observation_loop(
        heartbeat_path=heartbeat_path,
        trend_source_json=trend_source_json,
        fee_drag_source_json=fee_drag_source_json,
        iterations=iterations,
    )
    return build_operator_digest(observation_loop)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build offline Coinbase operator digest")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--observation-json", type=Path, default=None, help="Saved observation loop JSON")
    parser.add_argument("--heartbeat", type=Path, default=DEFAULT_HEARTBEAT, help="Local heartbeat JSON path")
    parser.add_argument("--trend-source-json", type=Path, default=None, help="Local trend/advisory source JSON")
    parser.add_argument("--fee-drag-source-json", type=Path, default=None, help="Local fee-drag evidence/report JSON")
    parser.add_argument("--iterations", type=int, default=3, help="Finite offline observations when no observation JSON is supplied")
    args = parser.parse_args(argv)

    digest = build_digest_from_inputs(
        observation_json=args.observation_json,
        heartbeat_path=args.heartbeat,
        trend_source_json=args.trend_source_json,
        fee_drag_source_json=args.fee_drag_source_json,
        iterations=args.iterations,
    )
    if args.json:
        print(json.dumps(digest, indent=2, sort_keys=True))
    else:
        print("=== Coinbase Operator Digest ===")
        print(f"Verdict: {digest['current_style_verdict']}")
        print(f"Next required action: {digest['next_required_action']}")
        print(f"Final notional: {digest['final_trade_notional']}")
        print(f"Trade permission: {digest['trade_permission']}")
        for row in digest["symbols"]:
            print(
                f"{row['symbol']}: {row['opportunity_verdict']} "
                f"regime={row['local_regime']} action={row['trend_advisory_action']}"
            )
        print(f"Profit readout: {digest['profit_readout']['global_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
