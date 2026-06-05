#!/usr/bin/env python3
"""
P2-027 strategy/signal redesign diagnostics.

Offline diagnostic report only. It summarizes synthetic-cycle weakness clusters
and ranks redesign directions after P2-026D falsified the prior filter-mining
candidate. It does not implement live strategy logic, filters, exits, probes,
runtime changes, or scaling.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.coinbase_historical_signal_generator import (  # noqa: E402
    DATA_DIR,
    build_historical_signal_generator_report,
)
from scripts.coinbase_independent_sample_candidate_falsification_report import (  # noqa: E402
    build_independent_sample_falsification_report,
)
from scripts.coinbase_stop_loss_diagnostics_report import build_stop_loss_diagnostics_report  # noqa: E402

SCHEMA_VERSION = "p2-027.strategy_signal_redesign_diagnostics.v1"
REPORT_CLASS = "strategy_signal_redesign_diagnostics"
MONEY_QUANT = Decimal("0.00000001")
RATE_QUANT = Decimal("0.000001")
P2_026B_CANDIDATE = "exclude_pre_entry_return_3_above_p80_0.011338"


def _to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return default


def _fmt_money(value: Decimal) -> str:
    return str(value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP))


def _fmt_rate(value: Decimal) -> str:
    return str(value.quantize(RATE_QUANT, rounding=ROUND_HALF_UP))


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _sum(values: Iterable[Decimal]) -> Decimal:
    total = Decimal("0")
    for value in values:
        total += value
    return total


def _cycle_gross(cycle: Dict[str, Any]) -> Decimal:
    return _to_decimal(cycle.get("gross_pnl", cycle.get("pnl_usd", "0")))


def _median_decimal(values: Sequence[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    return Decimal(str(median([float(value) for value in values])))


def _reason_bucket(value: Any) -> str:
    text = str(value or "").lower()
    if "stop" in text:
        return "stop_loss"
    if "take-profit" in text or "take profit" in text:
        return "take_profit"
    if "timeout" in text or "max hold" in text:
        return "timeout"
    if "end_of_data" in text:
        return "end_of_data"
    return text or "unknown"


def _is_timeout(cycle: Dict[str, Any]) -> bool:
    return _reason_bucket(cycle.get("exit_reason")) == "timeout"


def _is_stop_loss(cycle: Dict[str, Any]) -> bool:
    return _reason_bucket(cycle.get("exit_reason")) == "stop_loss"


def _stats(cycles: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    values = [_cycle_gross(cycle) for cycle in cycles]
    total = _sum(values)
    sample_size = len(cycles)
    winners = sum(1 for value in values if value > 0)
    losers = sum(1 for value in values if value < 0)
    return {
        "cycles": sample_size,
        "gross_total": _fmt_money(total),
        "avg_gross": _fmt_money(total / sample_size) if sample_size else "0.00000000",
        "median_gross": _fmt_money(_median_decimal(values)),
        "win_rate": _rate(winners, sample_size),
        "winners": winners,
        "losers": losers,
        "flat": sample_size - winners - losers,
    }


def _group_stats(
    cycles: Sequence[Dict[str, Any]],
    key_field: str,
    *,
    key_name: str = "key",
) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for cycle in cycles:
        if key_field == "exit_reason_bucket":
            key = _reason_bucket(cycle.get("exit_reason"))
        elif key_field == "symbol_strategy":
            key = f"{cycle.get('symbol', 'unknown')}|{cycle.get('strategy', 'unknown')}"
        else:
            key = str(cycle.get(key_field, "unknown"))
        groups[key].append(cycle)
    rows: List[Dict[str, Any]] = []
    for key, rows_for_key in sorted(groups.items()):
        row = {key_name: key}
        row.update(_stats(rows_for_key))
        row["share_of_cycles"] = _fmt_rate(Decimal(len(rows_for_key)) / Decimal(len(cycles))) if cycles else "0.000000"
        row["timeout_count"] = sum(1 for cycle in rows_for_key if _is_timeout(cycle))
        row["timeout_rate"] = _rate(row["timeout_count"], len(rows_for_key))
        row["stop_loss_count"] = sum(1 for cycle in rows_for_key if _is_stop_loss(cycle))
        row["stop_loss_rate"] = _rate(row["stop_loss_count"], len(rows_for_key))
        rows.append(row)
    return sorted(rows, key=lambda row: (_to_decimal(row["gross_total"]), row["cycles"]))


def _exit_reason_summary(cycles: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = _group_stats(cycles, "exit_reason_bucket", key_name="exit_reason")
    raw_counts = Counter(str(cycle.get("exit_reason", "unknown")) for cycle in cycles)
    for row in rows:
        row["raw_exit_reason_examples"] = [
            reason for reason, _ in raw_counts.most_common()
            if _reason_bucket(reason) == row["exit_reason"]
        ][:3]
    return rows


def _worst(rows: Sequence[Dict[str, Any]], key_field: str, limit: int = 5) -> List[Dict[str, Any]]:
    return [
        {
            key_field: row[key_field],
            "cycles": row["cycles"],
            "gross_total": row["gross_total"],
            "avg_gross": row["avg_gross"],
            "median_gross": row["median_gross"],
            "win_rate": row["win_rate"],
            "timeout_rate": row.get("timeout_rate", 0.0),
            "stop_loss_rate": row.get("stop_loss_rate", 0.0),
        }
        for row in sorted(rows, key=lambda item: (_to_decimal(item["gross_total"]), item["cycles"]))[:limit]
    ]


def _largest_loss_clusters(payload: Dict[str, List[Dict[str, Any]]], limit: int = 8) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for family, rows in payload.items():
        for row in rows:
            gross = _to_decimal(row.get("gross_total"))
            if gross >= 0:
                continue
            key_field = next((key for key in row if key not in {
                "cycles",
                "gross_total",
                "avg_gross",
                "median_gross",
                "win_rate",
                "winners",
                "losers",
                "flat",
                "share_of_cycles",
                "timeout_count",
                "timeout_rate",
                "stop_loss_count",
                "stop_loss_rate",
            }), "key")
            candidates.append({
                "cluster_family": family,
                "cluster": row.get(key_field),
                "cycles": row["cycles"],
                "gross_total": row["gross_total"],
                "win_rate": row["win_rate"],
                "timeout_rate": row.get("timeout_rate", 0.0),
                "stop_loss_rate": row.get("stop_loss_rate", 0.0),
            })
    return sorted(candidates, key=lambda row: (_to_decimal(row["gross_total"]), -row["cycles"]))[:limit]


def _timeout_diagnostics(cycles: Sequence[Dict[str, Any]], grouped: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    timeout_cycles = [cycle for cycle in cycles if _is_timeout(cycle)]
    stats = _stats(timeout_cycles)
    stats["timeout_count"] = len(timeout_cycles)
    stats["timeout_rate"] = _rate(len(timeout_cycles), len(cycles))
    stats["excessive_timeout_concentration"] = stats["timeout_rate"] >= 0.35
    stats["negative_timeout_gross"] = _to_decimal(stats["gross_total"]) < 0
    stats["weak_timeout_symbol_strategy_pairs"] = [
        row for row in _worst(grouped["symbol_strategy_performance"], "symbol_strategy", limit=8)
        if row["timeout_rate"] >= 0.30
    ][:5]
    stats["diagnostic_interpretation"] = (
        "Timeout exits are frequent enough to deserve root-cause analysis before live exit tuning."
        if stats["excessive_timeout_concentration"]
        else "Timeout exits are present but not the dominant offline concentration."
    )
    return stats


def _stop_loss_diagnostics(cycles: Sequence[Dict[str, Any]], stop_loss_payload: Dict[str, Any]) -> Dict[str, Any]:
    stop_cycles = [cycle for cycle in cycles if _is_stop_loss(cycle)]
    stats = _stats(stop_cycles)
    stats["stop_loss_count"] = len(stop_cycles)
    stats["stop_loss_rate"] = _rate(len(stop_cycles), len(cycles))
    stats["stop_loss_gross_contribution"] = stop_loss_payload["stop_loss_summary"]["stop_loss_gross_total"]
    stats["stop_loss_symbols"] = stop_loss_payload["stop_loss_summary"]["stop_loss_symbols"]
    stats["stop_loss_strategies"] = stop_loss_payload["stop_loss_summary"]["stop_loss_strategies"]
    stats["direct_stop_loss_exclusion_implementable"] = False
    stats["diagnostic_interpretation"] = (
        "Stop-loss losses dominate the gross drawdown, but stop-loss is an outcome and cannot be used as a live pre-entry rule."
    )
    return stats


def _opportunity(
    *,
    candidate_name: str,
    diagnostic_basis: str,
    expected_effect: str,
    evidence_strength: str,
    implementation_risk: str,
    offline_validation_required: str,
    priority: int,
) -> Dict[str, Any]:
    return {
        "candidate_name": candidate_name,
        "diagnostic_basis": diagnostic_basis,
        "expected_effect": expected_effect,
        "evidence_strength": evidence_strength,
        "implementation_risk": implementation_risk,
        "offline_validation_required": offline_validation_required,
        "priority": priority,
        "live_implementation_candidate": False,
    }


def _redesign_opportunities(
    *,
    baseline: Dict[str, Any],
    strategy_rows: Sequence[Dict[str, Any]],
    symbol_strategy_rows: Sequence[Dict[str, Any]],
    timeout: Dict[str, Any],
    stop_loss: Dict[str, Any],
    regime_rows: Sequence[Dict[str, Any]],
    volatility_rows: Sequence[Dict[str, Any]],
    liquidity_rows: Sequence[Dict[str, Any]],
    session_rows: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    worst_strategy = _worst(strategy_rows, "strategy", limit=1)[0] if strategy_rows else None
    worst_pair = _worst(symbol_strategy_rows, "symbol_strategy", limit=1)[0] if symbol_strategy_rows else None
    weakest_regime = _worst(regime_rows, "regime", limit=1)[0] if regime_rows else None
    weakest_vol = _worst(volatility_rows, "volatility_bucket", limit=1)[0] if volatility_rows else None
    weakest_liq = _worst(liquidity_rows, "liquidity_bucket", limit=1)[0] if liquidity_rows else None
    weakest_session = _worst(session_rows, "session_bucket", limit=1)[0] if session_rows else None
    rows = [
        _opportunity(
            candidate_name="retire_or_redesign_weak_strategy_modules",
            diagnostic_basis=(
                f"worst_strategy={worst_strategy['strategy']} gross={worst_strategy['gross_total']} "
                f"win_rate={worst_strategy['win_rate']}" if worst_strategy else "no strategy rows"
            ),
            expected_effect="Reduce repeated weak entries before searching smaller filters.",
            evidence_strength="medium" if worst_strategy and _to_decimal(worst_strategy["gross_total"]) < 0 else "low",
            implementation_risk="high_until_independent_replay_passes",
            offline_validation_required="P2-028 should compare redesigned or disabled strategy modules on independent synthetic windows.",
            priority=1,
        ),
        _opportunity(
            candidate_name="symbol_strategy_gating_based_on_independent_evidence",
            diagnostic_basis=(
                f"worst_pair={worst_pair['symbol_strategy']} gross={worst_pair['gross_total']} "
                f"stop_loss_rate={worst_pair['stop_loss_rate']}" if worst_pair else "no symbol_strategy rows"
            ),
            expected_effect="Avoid combining symbols and strategy modes that are structurally weak.",
            evidence_strength="medium" if worst_pair and _to_decimal(worst_pair["gross_total"]) < 0 else "low",
            implementation_risk="high_if_not_holdout_validated",
            offline_validation_required="Validate pair-level changes on April independent data and chronological folds.",
            priority=2,
        ),
        _opportunity(
            candidate_name="momentum_breakout_redesign_or_retirement",
            diagnostic_basis=(
                "momentum_breakout dominates cycle count and remains near or below zero gross in the expanded sample."
            ),
            expected_effect="Improve entry quality by changing the main source of entries rather than patching exits.",
            evidence_strength="medium",
            implementation_risk="high_until_alternative_signal_replay_exists",
            offline_validation_required="Build an offline replay comparing current momentum breakout against redesigned confirmation logic.",
            priority=3,
        ),
        _opportunity(
            candidate_name="timeout_exit_root_cause_analysis",
            diagnostic_basis=(
                f"timeout_rate={timeout['timeout_rate']} timeout_gross={timeout['gross_total']}"
            ),
            expected_effect="Separate weak entries that drift until timeout from exits that need different management.",
            evidence_strength="medium" if timeout["excessive_timeout_concentration"] else "low",
            implementation_risk="medium_but_no_live_exit_tuning_yet",
            offline_validation_required="Diagnose timeout paths with pre-entry-only features and post-entry path labels before any exit tuning.",
            priority=4,
        ),
        _opportunity(
            candidate_name="entry_confirmation_redesign_pre_entry_only",
            diagnostic_basis=(
                f"baseline_median={baseline['median_gross']} baseline_win_rate={baseline['win_rate']}"
            ),
            expected_effect="Require stronger evidence before entry instead of mining one-off exclusion filters.",
            evidence_strength="medium" if _to_decimal(baseline["median_gross"]) < 0 else "low",
            implementation_risk="high_if_threshold_mined",
            offline_validation_required="Use fixed pre-entry feature contracts and independent samples; do not reuse the falsified P2-026B threshold.",
            priority=5,
        ),
        _opportunity(
            candidate_name="regime_specific_gating_or_signal_design",
            diagnostic_basis=(
                f"weakest_regime={weakest_regime['regime']} gross={weakest_regime['gross_total']}"
                if weakest_regime else "no regime rows"
            ),
            expected_effect="Avoid applying one entry rule across regimes with different gross behavior.",
            evidence_strength="low_to_medium",
            implementation_risk="high_if_small_sample",
            offline_validation_required="Require regime-level holdout and independent-sample stability before any proposal.",
            priority=6,
        ),
        _opportunity(
            candidate_name="volatility_liquidity_session_diagnostics_only",
            diagnostic_basis=(
                f"weakest_volatility={weakest_vol['volatility_bucket'] if weakest_vol else 'none'}; "
                f"weakest_liquidity={weakest_liq['liquidity_bucket'] if weakest_liq else 'none'}; "
                f"weakest_session={weakest_session['session_bucket'] if weakest_session else 'none'}"
            ),
            expected_effect="Identify environmental contexts for future validation, not immediate filters.",
            evidence_strength="low_until_independent_validation",
            implementation_risk="high_overfit_risk",
            offline_validation_required="Only promote if independently validated after the P2-026B/P2-026D overfit lesson.",
            priority=7,
        ),
        _opportunity(
            candidate_name="gross_to_net_fee_slippage_realism_after_stable_gross_edge",
            diagnostic_basis="Current gross edge is not stable enough; fee/slippage realism is still mandatory before any paper or live probe.",
            expected_effect="Prevent repeating gross-positive but net-negative micro-trade behavior.",
            evidence_strength="policy_required",
            implementation_risk="low_as_offline_accounting_only",
            offline_validation_required="Apply fee/slippage model only after a redesign shows stable positive gross across independent samples.",
            priority=8,
        ),
    ]
    return sorted(rows, key=lambda row: row["priority"])


def build_strategy_signal_redesign_diagnostics(
    *,
    data_dir: Optional[Path] = None,
    max_bars: Optional[int] = 100000,
    max_cycles: Optional[int] = 2000,
    source_payload: Optional[Dict[str, Any]] = None,
    synthetic_cycles: Optional[List[Dict[str, Any]]] = None,
    generated_at_utc: Optional[str] = None,
) -> Dict[str, Any]:
    dpath = data_dir or DATA_DIR
    if source_payload is None:
        source_payload = build_historical_signal_generator_report(
            data_dir=dpath,
            max_bars=max_bars,
            max_cycles=max_cycles,
        )
    cycles = list(synthetic_cycles if synthetic_cycles is not None else source_payload.get("synthetic_cycles", []))
    baseline = _stats(cycles)
    symbol_rows = _group_stats(cycles, "symbol", key_name="symbol")
    strategy_rows = _group_stats(cycles, "strategy", key_name="strategy")
    symbol_strategy_rows = _group_stats(cycles, "symbol_strategy", key_name="symbol_strategy")
    regime_rows = _group_stats(cycles, "pre_entry_regime", key_name="regime")
    confidence_rows = _group_stats(cycles, "pre_entry_confidence", key_name="confidence_bucket")
    volatility_rows = _group_stats(cycles, "pre_entry_volatility_bucket", key_name="volatility_bucket")
    liquidity_rows = _group_stats(cycles, "pre_entry_liquidity_bucket", key_name="liquidity_bucket")
    session_rows = _group_stats(cycles, "pre_entry_session_bucket", key_name="session_bucket")
    exit_rows = _exit_reason_summary(cycles)
    stop_loss_payload = build_stop_loss_diagnostics_report(
        data_dir=dpath,
        max_bars=max_bars,
        max_cycles=max_cycles,
        source_payload=source_payload,
        synthetic_cycles=cycles,
    )
    falsification_payload = build_independent_sample_falsification_report(
        data_dir=dpath,
        max_bars=max_bars,
        max_cycles=max_cycles,
        source_payload=source_payload,
        synthetic_cycles=cycles,
    )
    grouped = {
        "symbol_performance": symbol_rows,
        "strategy_performance": strategy_rows,
        "symbol_strategy_performance": symbol_strategy_rows,
        "regime_performance": regime_rows,
        "confidence_bucket_performance": confidence_rows,
        "volatility_bucket_performance": volatility_rows,
        "liquidity_bucket_performance": liquidity_rows,
        "session_bucket_performance": session_rows,
        "exit_reason_summary": exit_rows,
    }
    timeout = _timeout_diagnostics(cycles, grouped)
    stop_loss = _stop_loss_diagnostics(cycles, stop_loss_payload)
    opportunities = _redesign_opportunities(
        baseline=baseline,
        strategy_rows=strategy_rows,
        symbol_strategy_rows=symbol_strategy_rows,
        timeout=timeout,
        stop_loss=stop_loss,
        regime_rows=regime_rows,
        volatility_rows=volatility_rows,
        liquidity_rows=liquidity_rows,
        session_rows=session_rows,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "report_class": REPORT_CLASS,
        "generated_at_utc": generated_at_utc or datetime.now(timezone.utc).isoformat(),
        "data_summary": {
            "bars_scanned": source_payload.get("bars_scanned", 0),
            "synthetic_cycles_count": len(cycles),
            "symbols": sorted({str(cycle.get("symbol", "unknown")) for cycle in cycles}),
            "strategies": sorted({str(cycle.get("strategy", "unknown")) for cycle in cycles}),
            "data_dir": source_payload.get("data_dir", str(dpath)),
            "leakage_guards": source_payload.get("leakage_guards", {}),
            "data_offline_ohlcv_untracked_expected": True,
        },
        "baseline_performance": baseline,
        "exit_reason_summary": exit_rows,
        "symbol_performance": symbol_rows,
        "strategy_performance": strategy_rows,
        "symbol_strategy_performance": symbol_strategy_rows,
        "regime_performance": regime_rows,
        "confidence_bucket_performance": confidence_rows,
        "volatility_bucket_performance": volatility_rows,
        "liquidity_bucket_performance": liquidity_rows,
        "session_bucket_performance": session_rows,
        "timeout_diagnostics": timeout,
        "stop_loss_diagnostics": stop_loss,
        "concentration_risk": {
            "worst_symbols": _worst(symbol_rows, "symbol"),
            "worst_strategies": _worst(strategy_rows, "strategy"),
            "worst_symbol_strategy_pairs": _worst(symbol_strategy_rows, "symbol_strategy"),
            "largest_loss_clusters": _largest_loss_clusters(grouped),
        },
        "falsified_filter_context": {
            "p2_026b_candidate": P2_026B_CANDIDATE,
            "p2_026d_verdict": falsification_payload["falsification_verdict"]["verdict"],
            "full_sample_passes_gate": falsification_payload["candidate_expanded_result"]["passes_gate"],
            "independent_window_passes_gate": falsification_payload["independent_window_result"]["passes_gate"],
            "chronological_holdout_passes_gate": falsification_payload["chronological_holdout_result"]["passes_gate"],
            "filter_implementation_authorized": False,
        },
        "redesign_opportunities": opportunities,
        "recommended_next_patch": {
            "patch_id": "P2-028",
            "target": "offline redesigned-entry validation harness",
            "description": (
                "Test redesigned strategy/signal variants against the current baseline with independent windows, "
                "symbol_strategy breakdowns, timeout/stop-loss diagnostics, and no live implementation."
            ),
            "must_not_do": [
                "implement the falsified P2-026B filter",
                "change live strategy thresholds",
                "tune live exits",
                "run paper or live probes",
                "scale",
            ],
        },
        "limitations": [
            "Synthetic cycles are not broker fills.",
            "Gross synthetic performance is not net broker P/L.",
            "P2-026D falsified the prior filter as an implementation candidate.",
            "Redesign opportunities are diagnostic roadmap items, not implementation winners.",
            "Order-book depth, queue position, and live fee/slippage fields are not present in OHLCV-only cycles.",
        ],
        "authorization": {
            "implementation_proposal_authorized": False,
            "implementation_authorized": False,
            "paper_probe_authorized": False,
            "live_probe_authorized": False,
            "scaling_authorized": False,
        },
    }


def write_report(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _human_summary(payload: Dict[str, Any]) -> str:
    baseline = payload["baseline_performance"]
    timeout = payload["timeout_diagnostics"]
    stop_loss = payload["stop_loss_diagnostics"]
    falsified = payload["falsified_filter_context"]
    top_cluster = payload["concentration_risk"]["largest_loss_clusters"][0]
    lines = [
        "=== P2-027 STRATEGY SIGNAL REDESIGN DIAGNOSTICS ===",
        f"bars_scanned={payload['data_summary']['bars_scanned']}",
        f"synthetic_cycles_count={payload['data_summary']['synthetic_cycles_count']}",
        f"gross_total={baseline['gross_total']} avg_gross={baseline['avg_gross']} "
        f"median_gross={baseline['median_gross']} win_rate={baseline['win_rate']}",
        "",
        f"timeout_count={timeout['timeout_count']} timeout_rate={timeout['timeout_rate']} "
        f"timeout_gross={timeout['gross_total']}",
        f"stop_loss_count={stop_loss['stop_loss_count']} stop_loss_rate={stop_loss['stop_loss_rate']} "
        f"stop_loss_gross={stop_loss['gross_total']}",
        f"largest_loss_cluster={top_cluster['cluster_family']}:{top_cluster['cluster']} gross={top_cluster['gross_total']}",
        "",
        f"p2_026d_verdict={falsified['p2_026d_verdict']}",
        f"filter_implementation_authorized={str(falsified['filter_implementation_authorized']).lower()}",
        "authorization: implementation_proposal=false implementation=false paper=false live=false scaling=false",
        "",
        "Top redesign directions:",
    ]
    for row in payload["redesign_opportunities"][:5]:
        lines.append(f"  {row['priority']}. {row['candidate_name']} evidence={row['evidence_strength']}")
    lines.extend([
        "",
        f"recommended_next_patch={payload['recommended_next_patch']['patch_id']} "
        f"{payload['recommended_next_patch']['target']}",
        "=== END REPORT ===",
    ])
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="P2-027 strategy/signal redesign diagnostics")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--max-bars", type=int, default=100000)
    parser.add_argument("--max-cycles", type=int, default=2000)
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output; no write by default")
    args = parser.parse_args(argv)
    payload = build_strategy_signal_redesign_diagnostics(
        data_dir=args.data_dir,
        max_bars=args.max_bars,
        max_cycles=args.max_cycles,
    )
    if args.output:
        write_report(args.output, payload)
    if args.json:
        json.dump(payload, sys.stdout, indent=2)
        print()
    else:
        print(_human_summary(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
