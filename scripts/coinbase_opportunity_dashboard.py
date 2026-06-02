#!/usr/bin/env python3
"""
Offline Coinbase opportunity dashboard.

Composes local heartbeat, balance-relative sizing preview, read-only trend
advisory, and fee-drag evidence into a single operator-facing snapshot. This
script is read-only: it does not import broker clients, read secrets, execute
runtime actions, or mutate state/log files.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import yaml

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(ROOT))

from coinbase_controlled_live_symbol_expansion import (
    evaluate_symbol_eligibility,
    policy_from_crypto_config,
    quote_for_symbol,
)
from scripts.coinbase_fee_drag_profitability_report import build_report as build_fee_drag_report
from scripts.coinbase_pilot_sizing_preview import build_preview as build_sizing_preview
from scripts.coinbase_trend_signal_registry import (
    ELIGIBLE_SYMBOLS,
    EXCLUDED_SYMBOLS,
    build_advisory_snapshot,
    normalize_symbol,
)


SCHEMA_VERSION = "p2-024b.coinbase_opportunity_dashboard.v1"
MODE = "offline_read_only_dashboard"
TRADE_PERMISSION = "none"
DEFAULT_HEARTBEAT = ROOT / "runtime" / "coinbase_heartbeat.json"
DEFAULT_TREND_SOURCE = ROOT / "tests" / "fixtures" / "controlled_live_symbol_expansion" / "expanded_symbol_regimes_sample.json"
FALLBACK_TREND_SOURCE = ROOT / "tests" / "fixtures" / "trend_advisory" / "coinbase_local_market_context_sample.json"
DEFAULT_QUOTE_SOURCE = ROOT / "tests" / "fixtures" / "controlled_live_symbol_expansion" / "expanded_symbol_quotes_healthy.json"
DEFAULT_FEE_DRAG_SOURCE = (
    ROOT
    / "tests"
    / "fixtures"
    / "coinbase_fee_drag_profitability"
    / "real_style_1usd_eth_fee_drag_cycle.json"
)
TMP_FEE_DRAG_SOURCE = Path("/tmp/coinbase_numeric_safe_payload_real-ethusd-029_after_f.json")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Optional[Path]) -> Tuple[Dict[str, Any], Optional[str]]:
    if path is None:
        return {}, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, str(exc)
    if isinstance(payload, dict):
        return payload, None
    return {"payload": payload}, None


def _default_fee_drag_source() -> Optional[Path]:
    if TMP_FEE_DRAG_SOURCE.exists():
        return TMP_FEE_DRAG_SOURCE
    if DEFAULT_FEE_DRAG_SOURCE.exists():
        return DEFAULT_FEE_DRAG_SOURCE
    return None


def _default_trend_source() -> Optional[Path]:
    if DEFAULT_TREND_SOURCE.exists():
        return DEFAULT_TREND_SOURCE
    if FALLBACK_TREND_SOURCE.exists():
        return FALLBACK_TREND_SOURCE
    return None


def _default_quote_source() -> Optional[Path]:
    if DEFAULT_QUOTE_SOURCE.exists():
        return DEFAULT_QUOTE_SOURCE
    return None


def _load_config(path: Path = ROOT / "config_coinbase_crypto.yaml") -> Dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _source(payload: Dict[str, Any], source_id: str) -> Dict[str, Any]:
    sources = payload.get("sources")
    if isinstance(sources, dict) and isinstance(sources.get(source_id), dict):
        return sources[source_id]
    if isinstance(payload.get(source_id), dict):
        return payload[source_id]
    if source_id == "coinbase_local_market_context" and any(
        key in payload for key in ("symbols", "symbol", "regime", "allowed_strategies")
    ):
        return payload
    return {}


def _local_symbol_context(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    src = _source(payload, "coinbase_local_market_context")
    records = src.get("symbols")
    if records is None and any(key in src for key in ("symbol", "regime", "allowed_strategies")):
        records = [src]
    result: Dict[str, Dict[str, Any]] = {}
    if isinstance(records, list):
        for row in records:
            if not isinstance(row, dict):
                continue
            symbol = normalize_symbol(row.get("symbol"))
            if symbol:
                result[symbol] = row
    return result


def _allowed_strategies(local: Dict[str, Any]) -> List[str]:
    strategies = local.get("allowed_strategies")
    if not isinstance(strategies, list):
        return []
    return [str(item) for item in strategies if str(item).strip()]


def _expected_move(local: Dict[str, Any]) -> Optional[str]:
    value = local.get("expected_gross_move_rate")
    return str(value) if value is not None else None


def _advisory_by_symbol(snapshot: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows = snapshot.get("symbols")
    result: Dict[str, Dict[str, Any]] = {}
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                symbol = normalize_symbol(row.get("symbol"))
                if symbol:
                    result[symbol] = row
    return result


def _load_fee_drag(source_json: Optional[Path]) -> Dict[str, Any]:
    source = source_json if source_json is not None else _default_fee_drag_source()
    if source is None:
        return {
            "verdict": "UNKNOWN",
            "cycle_id": None,
            "net_pnl": None,
            "minimum_required_gross_move_rate": None,
            "source_path": None,
        }

    payload, error = _load_json(source)
    if error:
        return {
            "verdict": "UNKNOWN",
            "cycle_id": None,
            "net_pnl": None,
            "minimum_required_gross_move_rate": None,
            "source_path": str(source),
            "load_error": error,
        }

    if {"verdict", "cycle_id", "net_pnl"}.issubset(payload):
        report = dict(payload)
        report.setdefault("source_path", str(source))
        return report

    return build_fee_drag_report(source)


def _fee_drag_status(report: Dict[str, Any]) -> str:
    if report.get("minimum_required_gross_move_rate"):
        return "threshold_active"
    if report.get("verdict") in {"FEE_DRAG_CONFIRMED", "OK"}:
        return "threshold_active"
    return "unknown"


def _required_fee_drag_rate(report: Dict[str, Any]) -> Optional[str]:
    value = report.get("minimum_required_gross_move_rate")
    return str(value) if value is not None else None


def _heartbeat_blockers(heartbeat: Dict[str, Any], load_error: Optional[str]) -> List[str]:
    blockers: List[str] = []
    if load_error:
        blockers.append("heartbeat_unavailable")
    if heartbeat.get("risk_halt_active") is True:
        blockers.append("risk_halt_active")
    if heartbeat.get("kill_switch_present") is True:
        blockers.append("kill_switch_present")
    return blockers


def _symbol_opportunity(
    *,
    symbol: str,
    local: Dict[str, Any],
    advisory: Dict[str, Any],
    fee_status: str,
    eligibility: Dict[str, Any],
    global_blocked: bool,
) -> Dict[str, Any]:
    regime = str(local.get("regime") or "unknown").lower()
    strategies = _allowed_strategies(local)
    advisory_action = str(advisory.get("advisory_action") or "unknown")
    if advisory_action == "unknown":
        if regime in {"downtrend", "dead_chop"} and not strategies:
            advisory_action = "avoid"
        elif strategies:
            advisory_action = "confirm_only"
        elif regime != "unknown":
            advisory_action = "watch"
    reasons: List[str] = []

    if regime != "unknown":
        reasons.append(f"local_regime={regime}")
    else:
        reasons.append("local_regime_unknown")
    if not strategies:
        reasons.append("allowed_strategies_empty")
    if advisory_action != "unknown":
        reasons.append(f"trend_advisory_action={advisory_action}")
    if fee_status == "threshold_active":
        reasons.append("fee_drag_threshold_active")
    for reason in eligibility.get("skip_reasons") or []:
        if reason not in reasons:
            reasons.append(reason)

    if global_blocked:
        opportunity_verdict = "blocked"
        reasons.append("global_runtime_blocker")
    elif eligibility.get("allowed"):
        opportunity_verdict = "candidate"
        reasons.append("candidate_requires_separate_strategy_and_risk_gates")
    elif advisory_action == "avoid" or (regime in {"downtrend", "dead_chop"} and not strategies):
        opportunity_verdict = "sit_out"
    elif eligibility.get("opportunity_verdict") in {"blocked", "sit_out"}:
        opportunity_verdict = eligibility.get("opportunity_verdict")
    else:
        opportunity_verdict = "watch"
        reasons.append("wait_for_cleaner_signal")

    return {
        "symbol": symbol,
        "local_regime": regime,
        "allowed_strategies": strategies,
        "trend_advisory_action": advisory_action,
        "fee_drag_status": fee_status,
        "opportunity_verdict": opportunity_verdict,
        "eligibility": eligibility,
        "skip_reasons": list(eligibility.get("skip_reasons") or []),
        "reason": reasons,
    }


def _global_verdict(symbols: Iterable[Dict[str, Any]], blockers: List[str], open_positions: Any) -> str:
    if blockers:
        return "BLOCKED"
    try:
        open_count = int(open_positions or 0)
    except (TypeError, ValueError):
        open_count = 0
    if open_count > 0:
        return "OBSERVE_EXISTING_POSITION"

    verdicts = [str(row.get("opportunity_verdict")) for row in symbols]
    if verdicts and all(verdict == "sit_out" for verdict in verdicts):
        return "SIT_OUT_CONFIRMED"
    if any(verdict == "candidate" for verdict in verdicts):
        return "READY_TO_OBSERVE"
    if any(verdict == "watch" for verdict in verdicts):
        return "WAIT_FOR_SIGNAL"
    return "UNKNOWN"


def build_dashboard(
    *,
    heartbeat_path: Path = DEFAULT_HEARTBEAT,
    trend_source_json: Optional[Path] = None,
    quote_source_json: Optional[Path] = None,
    fee_drag_source_json: Optional[Path] = None,
    include_logs: bool = False,
    offline_only: bool = True,
) -> Dict[str, Any]:
    heartbeat, heartbeat_error = _load_json(heartbeat_path)
    blockers = _heartbeat_blockers(heartbeat, heartbeat_error)
    config = _load_config()
    crypto = config.get("crypto") if isinstance(config.get("crypto"), dict) else {}
    global_risk = config.get("global_risk") if isinstance(config.get("global_risk"), dict) else {}
    expansion_policy = policy_from_crypto_config(crypto)

    # P2-024F: load local state to separate external/staked inventory (e.g. SOL)
    # from bot-owned positions for accurate max_open_slot reporting. These loads
    # are strictly local/offline files; no broker calls.
    try:
        base = Path(heartbeat_path).resolve().parent.parent if heartbeat_path else Path(".")
        state_coinbase = base / "state" / "coinbase"
    except Exception:
        state_coinbase = Path("state") / "coinbase"
    state_open, _ = _load_json(state_coinbase / "open_positions.json")
    ext_inv_state, _ = _load_json(state_coinbase / "external_inventory.json")
    bot_owned_open_positions = len((state_open or {}).get("positions", {}) or {})
    external_inventory_count = len((ext_inv_state or {}).get("external_inventory", {}) or {})
    external_inventory_symbols = list(((ext_inv_state or {}).get("external_inventory") or {}).keys())

    trend_source = trend_source_json if trend_source_json is not None else _default_trend_source()
    trend_payload, trend_error = _load_json(trend_source)
    quote_source = quote_source_json if quote_source_json is not None else _default_quote_source()
    quote_payload, quote_error = _load_json(quote_source)
    trend_snapshot = build_advisory_snapshot(
        symbols=list(expansion_policy.get("live_symbols") or ELIGIBLE_SYMBOLS) + list(expansion_policy.get("excluded_symbols") or EXCLUDED_SYMBOLS),
        source_json=trend_source,
        allow_network=False,
    )
    local_by_symbol = _local_symbol_context(trend_payload)
    advisory_by_symbol = _advisory_by_symbol(trend_snapshot)

    fee_report = _load_fee_drag(fee_drag_source_json)
    fee_status = _fee_drag_status(fee_report)
    required_fee_drag_rate = _required_fee_drag_rate(fee_report)
    sizing = build_sizing_preview(
        equity=heartbeat.get("equity"),
        buying_power=heartbeat.get("buying_power"),
    )

    symbol_rows = []
    for symbol in expansion_policy.get("live_symbols") or list(ELIGIBLE_SYMBOLS):
        local = local_by_symbol.get(symbol, {})
        eligibility = evaluate_symbol_eligibility(
            symbol=symbol,
            policy=expansion_policy,
            quote=quote_for_symbol(symbol, quote_payload),
            regime=str(local.get("regime") or "unknown"),
            allowed_strategies=_allowed_strategies(local),
            expected_gross_move_rate=_expected_move(local),
            required_gross_move_rate=required_fee_drag_rate,
            open_positions=int(heartbeat.get("open_positions") or 0),
            max_open_positions=int(global_risk.get("max_open_positions") or 1),
            daily_trade_count=int(heartbeat.get("trades_today") or 0),
            max_trades_per_day=int(global_risk.get("max_trades_per_day") or 3),
        )
        symbol_rows.append(
            _symbol_opportunity(
                symbol=symbol,
                local=local,
                advisory=advisory_by_symbol.get(symbol, {}),
                fee_status=fee_status,
                eligibility=eligibility,
                global_blocked=bool(blockers),
            )
        )
    verdict = _global_verdict(symbol_rows, blockers, heartbeat.get("open_positions"))

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "mode": MODE,
        "verdict": verdict,
        "trade_permission": TRADE_PERMISSION,
        "live_order_actions_allowed": False,
        "risk_increase": "not_approved",
        "sizing": sizing,
        "controlled_live_symbol_expansion": {
            "enabled": expansion_policy.get("enabled", False),
            "expanded_live_symbols": list(expansion_policy.get("live_symbols") or []),
            "excluded_symbols": list(expansion_policy.get("excluded_symbols") or []),
            "shared_caps": expansion_policy.get("shared_caps", True),
            "require_quote_health": expansion_policy.get("require_quote_health", True),
            "require_fee_drag_clearance": expansion_policy.get("require_fee_drag_clearance", True),
            "no_derivatives": expansion_policy.get("no_derivatives", True),
            "block_prediction_products": expansion_policy.get("block_prediction_products", True),
            "warning": "Expansion increases opportunity count, not trade size, caps, or max positions.",
        },
        "expanded_live_symbols": list(expansion_policy.get("live_symbols") or []),
        "excluded_symbols": list(expansion_policy.get("excluded_symbols") or []),
        "symbols": symbol_rows,
        "profit_readout": {
            "global_status": "unsafe_to_aggregate",
            "aggregation_allowed": False,
            "scaling_allowed": False,
            "latest_measured_cycle": {
                "cycle_id": fee_report.get("cycle_id"),
                "product_id": fee_report.get("product_id"),
                "gross_pnl": fee_report.get("gross_pnl"),
                "total_fees": fee_report.get("total_fees"),
                "net_pnl": fee_report.get("net_pnl"),
                "verdict": fee_report.get("verdict", "UNKNOWN"),
                "recommendation": fee_report.get("recommendation"),
            },
        },
        "trend_advisory": {
            "schema_version": trend_snapshot.get("schema_version"),
            "mode": trend_snapshot.get("mode"),
            "trade_permission": trend_snapshot.get("trade_permission"),
            "source_path": str(trend_source) if trend_source is not None else None,
            "source_load_error": trend_error,
            "quote_source_path": str(quote_source) if quote_source is not None else None,
            "quote_source_load_error": quote_error,
            "global_narratives": trend_snapshot.get("global_narratives", []),
            "source_status": trend_snapshot.get("source_status", {}),
        },
        "runtime": {
            "heartbeat_path": str(heartbeat_path),
            "heartbeat_load_error": heartbeat_error,
            "broker": heartbeat.get("broker"),
            "mode": heartbeat.get("mode"),
            "pid": heartbeat.get("pid"),
            "open_positions": heartbeat.get("open_positions"),  # bot-owned (P2-024F)
            "bot_owned_open_positions": bot_owned_open_positions,
            "external_inventory_count": external_inventory_count,
            "external_inventory_symbols": external_inventory_symbols,
            "max_open_slot_available": bool(bot_owned_open_positions < int(global_risk.get("max_open_positions") or 1)),
            "risk_halt_active": heartbeat.get("risk_halt_active"),
            "kill_switch_present": heartbeat.get("kill_switch_present"),
            "blockers": blockers,
        },
        "operator_notes": [
            "Dashboard is offline/read-only and cannot authorize trades.",
            "Trend context is advisory-only and never overrides strategy/risk gates.",
            "Fee-drag evidence keeps current real profit aggregation unsafe until more broker-backed cycles exist.",
        ],
        "logs": {
            "include_logs_requested": bool(include_logs),
            "logs_loaded": False,
            "reason": "log_tail_loading_not_enabled_for_p2_024b",
        },
        "safety": {
            "offline_only": bool(offline_only),
            "broker_calls_made": False,
            "live_read_only_used": False,
            "order_actions_allowed": False,
            "sizing_changes_allowed": False,
            "risk_override_allowed": False,
            "sol_excluded": (
                "SOL/USD" in set(expansion_policy.get("excluded_symbols") or [])
                and all(row.get("symbol") != "SOL/USD" for row in symbol_rows)
            ),
            "secrets_or_env_read": False,
            "state_or_log_mutation": False,
            "symbol_expansion": bool(expansion_policy.get("enabled", False)),
            "derivatives_live_execution": False,
            "strategy_auto_trigger_from_trends": False,
        },
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build offline Coinbase opportunity dashboard")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--heartbeat", type=Path, default=DEFAULT_HEARTBEAT, help="Local heartbeat JSON path")
    parser.add_argument("--trend-source-json", type=Path, default=None, help="Local trend/advisory source JSON")
    parser.add_argument("--quote-source-json", type=Path, default=None, help="Local quote health source JSON")
    parser.add_argument("--fee-drag-source-json", type=Path, default=None, help="Local fee-drag evidence/report JSON")
    parser.add_argument("--include-logs", action="store_true", help="Record that log context was requested")
    parser.add_argument("--offline-only", action="store_true", default=True, help="Reserved; dashboard remains offline-only")
    args = parser.parse_args(argv)

    dashboard = build_dashboard(
        heartbeat_path=args.heartbeat,
        trend_source_json=args.trend_source_json,
        quote_source_json=args.quote_source_json,
        fee_drag_source_json=args.fee_drag_source_json,
        include_logs=args.include_logs,
        offline_only=args.offline_only,
    )
    if args.json:
        print(json.dumps(dashboard, indent=2, sort_keys=True))
    else:
        print("=== Coinbase Opportunity Dashboard ===")
        print(f"Verdict: {dashboard['verdict']}")
        print(f"Trade permission: {dashboard['trade_permission']}")
        print(f"Final notional: {dashboard['sizing'].get('final_trade_notional')}")
        for row in dashboard["symbols"]:
            print(
                f"{row['symbol']}: {row['opportunity_verdict']} "
                f"regime={row['local_regime']} action={row['trend_advisory_action']}"
            )
        print(f"Profit readout: {dashboard['profit_readout']['global_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
