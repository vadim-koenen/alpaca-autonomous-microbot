#!/usr/bin/env python3
"""
P2-028 redesigned-entry validation harness.

Offline diagnostic harness only. It evaluates redesigned-entry concepts against
existing synthetic cycles and pre-entry fields. It does not change live strategy
logic, risk, runtime, exits, probes, or scaling.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from statistics import median
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.coinbase_historical_signal_generator import (  # noqa: E402
    DATA_DIR,
    build_historical_signal_generator_report,
)

SCHEMA_VERSION = "p2-028.redesigned_entry_validation_harness.v1"
REPORT_CLASS = "redesigned_entry_validation_harness"
MONEY_QUANT = Decimal("0.00000001")
RATE_QUANT = Decimal("0.000001")
MIN_SAMPLE_SIZE = 30
PREFERRED_SAMPLE_SIZE = 50
MATERIAL_GROSS_WORSE = Decimal("-0.025")
P2_026B_CANDIDATE = "exclude_pre_entry_return_3_above_p80_0.011338"


@dataclass(frozen=True)
class CandidateSpec:
    candidate_name: str
    family: str
    rule_description: str
    input_fields: Sequence[str]
    keep: Callable[[Dict[str, Any]], bool]
    diagnostic_only: bool = False


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
    winners = sum(1 for value in values if value > 0)
    losers = sum(1 for value in values if value < 0)
    timeout_count = sum(1 for cycle in cycles if _is_timeout(cycle))
    stop_loss_count = sum(1 for cycle in cycles if _is_stop_loss(cycle))
    stop_loss_gross = _sum(_cycle_gross(cycle) for cycle in cycles if _is_stop_loss(cycle))
    sample_size = len(cycles)
    return {
        "sample_size": sample_size,
        "gross_total": _fmt_money(total),
        "avg_gross": _fmt_money(total / sample_size) if sample_size else "0.00000000",
        "median_gross": _fmt_money(_median_decimal(values)),
        "win_rate": _rate(winners, sample_size),
        "winners": winners,
        "losers": losers,
        "timeout_rate": _rate(timeout_count, sample_size),
        "timeout_count": timeout_count,
        "stop_loss_rate": _rate(stop_loss_count, sample_size),
        "stop_loss_count": stop_loss_count,
        "stop_loss_gross": _fmt_money(stop_loss_gross),
    }


def _group_stats(cycles: Sequence[Dict[str, Any]], group_field: str, key_name: str) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for cycle in cycles:
        if group_field == "symbol_strategy":
            key = f"{cycle.get('symbol', 'unknown')}|{cycle.get('strategy', 'unknown')}"
        else:
            key = str(cycle.get(group_field, "unknown"))
        groups.setdefault(key, []).append(cycle)
    rows = []
    for key, rows_for_key in sorted(groups.items()):
        row = {key_name: key}
        row.update(_stats(rows_for_key))
        rows.append(row)
    return sorted(rows, key=lambda row: (_to_decimal(row["gross_total"]), row["sample_size"]))


def _positive_group_count(rows: Sequence[Dict[str, Any]]) -> int:
    return sum(1 for row in rows if _to_decimal(row["gross_total"]) > 0 and row["win_rate"] >= 0.5)


def _candidate_specs() -> List[CandidateSpec]:
    return [
        CandidateSpec(
            candidate_name="momentum_confirmation_keep_positive_3_and_6_bar",
            family="momentum_confirmation_redesign",
            rule_description="Keep entries only when 3-bar and 6-bar pre-entry returns are both non-negative.",
            input_fields=["pre_entry_return_3", "pre_entry_return_6"],
            keep=lambda c: _to_decimal(c.get("pre_entry_return_3")) >= 0 and _to_decimal(c.get("pre_entry_return_6")) >= 0,
        ),
        CandidateSpec(
            candidate_name="momentum_confirmation_keep_positive_12_bar",
            family="momentum_confirmation_redesign",
            rule_description="Keep entries only when 12-bar pre-entry return is non-negative.",
            input_fields=["pre_entry_return_12"],
            keep=lambda c: _to_decimal(c.get("pre_entry_return_12")) >= 0,
        ),
        CandidateSpec(
            candidate_name="mean_reversion_restrict_to_range_regime",
            family="mean_reversion_redesign",
            rule_description="Keep mean-reversion entries only in range regime while keeping all non-mean-reversion entries.",
            input_fields=["strategy", "pre_entry_regime"],
            keep=lambda c: str(c.get("strategy")) != "mean_reversion" or str(c.get("pre_entry_regime", c.get("regime"))) == "range",
        ),
        CandidateSpec(
            candidate_name="diagnostic_retire_mean_reversion",
            family="symbol_strategy_retirement_gating_diagnostics",
            rule_description="Diagnostic: remove mean-reversion entries to estimate module contribution.",
            input_fields=["strategy"],
            keep=lambda c: str(c.get("strategy")) != "mean_reversion",
            diagnostic_only=True,
        ),
        CandidateSpec(
            candidate_name="diagnostic_retire_algo_momentum_pair",
            family="symbol_strategy_retirement_gating_diagnostics",
            rule_description="Diagnostic: remove ALGO/USD momentum-breakout entries highlighted by P2-027.",
            input_fields=["symbol", "strategy"],
            keep=lambda c: not (str(c.get("symbol")) == "ALGO/USD" and str(c.get("strategy")) == "momentum_breakout"),
            diagnostic_only=True,
        ),
        CandidateSpec(
            candidate_name="regime_keep_uptrend_or_range",
            family="regime_specific_entry_gating",
            rule_description="Keep entries only in uptrend or range regimes.",
            input_fields=["pre_entry_regime"],
            keep=lambda c: str(c.get("pre_entry_regime", c.get("regime"))) in {"uptrend", "range"},
        ),
        CandidateSpec(
            candidate_name="volatility_avoid_mid_high_bucket",
            family="volatility_aware_entry_gating",
            rule_description="Avoid the 0.5%-1% pre-entry volatility bucket identified as weak in P2-027 diagnostics.",
            input_fields=["pre_entry_volatility_bucket"],
            keep=lambda c: str(c.get("pre_entry_volatility_bucket")) != "0.5%-1%",
        ),
        CandidateSpec(
            candidate_name="liquidity_avoid_elevated_volume_bucket",
            family="liquidity_aware_entry_gating",
            rule_description="Avoid elevated_1.1x_1.5x liquidity bucket until independently validated.",
            input_fields=["pre_entry_liquidity_bucket"],
            keep=lambda c: str(c.get("pre_entry_liquidity_bucket")) != "elevated_1.1x_1.5x",
        ),
        CandidateSpec(
            candidate_name="session_avoid_06_17_utc",
            family="session_time_of_day_entry_gating",
            rule_description="Avoid 06-11 and 12-17 UTC sessions that P2-027 marked as weak clusters.",
            input_fields=["pre_entry_session_bucket"],
            keep=lambda c: str(c.get("pre_entry_session_bucket")) not in {"06-11", "12-17"},
        ),
        CandidateSpec(
            candidate_name="confidence_keep_085_or_higher",
            family="confidence_threshold_diagnostics",
            rule_description="Keep entries only when pre-entry confidence is at least 0.85.",
            input_fields=["pre_entry_confidence"],
            keep=lambda c: _to_decimal(c.get("pre_entry_confidence", c.get("confidence"))) >= Decimal("0.85"),
        ),
        CandidateSpec(
            candidate_name="timeout_risk_avoid_timeout_heavy_sessions",
            family="timeout_risk_reduction_diagnostics",
            rule_description="Avoid sessions with elevated timeout concentration in P2-027 diagnostics.",
            input_fields=["pre_entry_session_bucket"],
            keep=lambda c: str(c.get("pre_entry_session_bucket")) not in {"18-23"},
        ),
        CandidateSpec(
            candidate_name="stop_loss_risk_avoid_high_volatility_bucket",
            family="stop_loss_risk_reduction_diagnostics",
            rule_description="Avoid the high stop-loss 0.5%-1% volatility bucket.",
            input_fields=["pre_entry_volatility_bucket"],
            keep=lambda c: str(c.get("pre_entry_volatility_bucket")) != "0.5%-1%",
        ),
    ]


def _leakage_risk(input_fields: Sequence[str]) -> bool:
    post_fields = {
        "exit_reason",
        "exit_price",
        "exit_time",
        "pnl_usd",
        "gross_pnl",
        "hold_duration_minutes",
    }
    return any(field in post_fields for field in input_fields)


def _stability(cycles: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    symbol = _group_stats(cycles, "symbol", "symbol")
    strategy = _group_stats(cycles, "strategy", "strategy")
    pair = _group_stats(cycles, "symbol_strategy", "symbol_strategy")
    regime = _group_stats(cycles, "pre_entry_regime", "regime")
    return {
        "positive_symbol_count": _positive_group_count(symbol),
        "positive_strategy_count": _positive_group_count(strategy),
        "positive_symbol_strategy_count": _positive_group_count(pair),
        "positive_regime_count": _positive_group_count(regime),
        "symbol_count": len(symbol),
        "strategy_count": len(strategy),
        "symbol_strategy_count": len(pair),
        "regime_count": len(regime),
        "stable_across_symbols": len(symbol) > 0 and _positive_group_count(symbol) >= max(1, len(symbol) // 2),
        "stable_across_strategies": len(strategy) > 0 and _positive_group_count(strategy) >= max(1, len(strategy) // 2),
        "stable_across_symbol_strategy": len(pair) > 0 and _positive_group_count(pair) >= max(1, len(pair) // 2),
        "stable_across_regimes": len(regime) > 0 and _positive_group_count(regime) >= max(1, len(regime) // 2),
    }


def _status(
    *,
    spec: CandidateSpec,
    baseline: Dict[str, Any],
    stats: Dict[str, Any],
    stability: Dict[str, Any],
    leakage: bool,
) -> tuple[str, List[str]]:
    reasons: List[str] = []
    gross_delta = _to_decimal(stats["gross_total"]) - _to_decimal(baseline["gross_total"])
    if leakage:
        reasons.append("leakage_risk=true")
    if stats["sample_size"] < MIN_SAMPLE_SIZE:
        reasons.append(f"sample_size < {MIN_SAMPLE_SIZE}")
    if gross_delta <= MATERIAL_GROSS_WORSE:
        reasons.append("gross worsens materially")
    if stats["win_rate"] < 0.45:
        reasons.append("win_rate weak")
    if spec.diagnostic_only:
        return ("diagnostic_only", reasons or ["diagnostic contribution estimate only"])
    if reasons:
        return ("rejected", reasons)
    full_sample_ok = (
        _to_decimal(stats["gross_total"]) > _to_decimal(baseline["gross_total"])
        and _to_decimal(stats["avg_gross"]) > 0
        and _to_decimal(stats["median_gross"]) >= 0
        and stats["win_rate"] >= 0.50
    )
    stable = (
        stability["stable_across_symbols"]
        and stability["stable_across_strategies"]
        and stability["stable_across_symbol_strategy"]
    )
    if full_sample_ok and stats["sample_size"] >= PREFERRED_SAMPLE_SIZE and stable:
        return ("validation_ready", [])
    if full_sample_ok:
        return ("promising_needs_holdout", ["full_sample_improves_but_stability_or_sample_gate_incomplete"])
    return ("diagnostic_only", ["useful_for_redesign_diagnostics_but_not_full_sample_positive"])


def _evaluate_candidate(spec: CandidateSpec, cycles: Sequence[Dict[str, Any]], baseline: Dict[str, Any]) -> Dict[str, Any]:
    leakage = _leakage_risk(spec.input_fields)
    kept = [cycle for cycle in cycles if spec.keep(cycle)]
    removed = [cycle for cycle in cycles if not spec.keep(cycle)]
    stats = _stats(kept)
    gross_delta = _to_decimal(stats["gross_total"]) - _to_decimal(baseline["gross_total"])
    stab = _stability(kept)
    status, reasons = _status(spec=spec, baseline=baseline, stats=stats, stability=stab, leakage=leakage)
    baseline_timeout = _to_decimal(str(baseline["timeout_rate"]))
    baseline_stop = _to_decimal(str(baseline["stop_loss_rate"]))
    timeout_reduction = baseline_timeout - _to_decimal(str(stats["timeout_rate"]))
    stop_reduction = baseline_stop - _to_decimal(str(stats["stop_loss_rate"]))
    return {
        "candidate_name": spec.candidate_name,
        "family": spec.family,
        "rule_description": spec.rule_description,
        "input_fields": list(spec.input_fields),
        "pre_entry_only": not leakage,
        "leakage_risk": leakage,
        "sample_size": stats["sample_size"],
        "trades_removed": len(removed),
        "trade_removal_rate": _fmt_rate(Decimal(len(removed)) / Decimal(len(cycles))) if cycles else "0.000000",
        "gross_total": stats["gross_total"],
        "avg_gross": stats["avg_gross"],
        "median_gross": stats["median_gross"],
        "win_rate": stats["win_rate"],
        "timeout_rate": stats["timeout_rate"],
        "stop_loss_rate": stats["stop_loss_rate"],
        "gross_delta_vs_baseline": _fmt_money(gross_delta),
        "timeout_rate_delta_vs_baseline": _fmt_rate(timeout_reduction),
        "stop_loss_rate_delta_vs_baseline": _fmt_rate(stop_reduction),
        "status": status,
        "rejection_reasons": reasons,
        "required_next_validation": (
            "independent_holdout_validation_required_before_any_implementation_proposal"
            if status in {"promising_needs_holdout", "validation_ready"}
            else "diagnostic_review_only"
        ),
        "stability": stab,
    }


def _family_summary(candidates: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in candidates:
        grouped.setdefault(row["family"], []).append(row)
    summary = []
    for family, rows in sorted(grouped.items()):
        status_counts: Dict[str, int] = {}
        for row in rows:
            status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
        best = sorted(rows, key=lambda row: (_to_decimal(row["gross_delta_vs_baseline"]), row["sample_size"]), reverse=True)[0]
        summary.append({
            "family": family,
            "candidate_count": len(rows),
            "status_counts": status_counts,
            "best_candidate": best["candidate_name"],
            "best_gross_delta_vs_baseline": best["gross_delta_vs_baseline"],
            "best_status": best["status"],
        })
    return summary


def _reduction_diagnostics(candidates: Sequence[Dict[str, Any]], field: str) -> List[Dict[str, Any]]:
    return [
        {
            "candidate_name": row["candidate_name"],
            "family": row["family"],
            field: row[field],
            "gross_delta_vs_baseline": row["gross_delta_vs_baseline"],
            "sample_size": row["sample_size"],
            "status": row["status"],
        }
        for row in sorted(candidates, key=lambda item: _to_decimal(item[field]), reverse=True)[:5]
    ]


def _overfit_risk(candidates: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "candidate_count": len(candidates),
        "validation_ready_count": sum(1 for row in candidates if row["status"] == "validation_ready"),
        "promising_needs_holdout_count": sum(1 for row in candidates if row["status"] == "promising_needs_holdout"),
        "diagnostic_only_count": sum(1 for row in candidates if row["status"] == "diagnostic_only"),
        "rejected_count": sum(1 for row in candidates if row["status"] == "rejected"),
        "overfit_risk": "high_until_independent_holdout_passes",
        "p2_026d_lesson": "The prior P2-026B filter improved a sample but failed independent validation.",
    }


def build_redesigned_entry_validation_harness(
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
        source_payload = build_historical_signal_generator_report(data_dir=dpath, max_bars=max_bars, max_cycles=max_cycles)
    cycles = list(synthetic_cycles if synthetic_cycles is not None else source_payload.get("synthetic_cycles", []))
    baseline = _stats(cycles)
    specs = _candidate_specs()
    candidates = [_evaluate_candidate(spec, cycles, baseline) for spec in specs]
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
            "data_offline_ohlcv_untracked_expected": True,
        },
        "baseline_performance": baseline,
        "candidate_families_evaluated": sorted({spec.family for spec in specs}),
        "candidates": candidates,
        "family_summary": _family_summary(candidates),
        "symbol_stability": _group_stats(cycles, "symbol", "symbol"),
        "strategy_stability": _group_stats(cycles, "strategy", "strategy"),
        "symbol_strategy_stability": _group_stats(cycles, "symbol_strategy", "symbol_strategy"),
        "regime_stability": _group_stats(cycles, "pre_entry_regime", "regime"),
        "timeout_reduction_diagnostics": _reduction_diagnostics(candidates, "timeout_rate_delta_vs_baseline"),
        "stop_loss_reduction_diagnostics": _reduction_diagnostics(candidates, "stop_loss_rate_delta_vs_baseline"),
        "overfit_risk_summary": _overfit_risk(candidates),
        "falsified_filter_context": {
            "p2_026b_candidate": P2_026B_CANDIDATE,
            "p2_026d_verdict": "falsified",
            "do_not_implement_prior_filter": True,
        },
        "recommended_next_patch": {
            "patch_id": "P2-029",
            "target": "independent holdout validation for redesigned-entry candidates",
            "description": (
                "Run promising or validation-ready redesigned-entry candidates through independent windows, "
                "chronological folds, and gross-to-net realism before any implementation proposal."
            ),
        },
        "limitations": [
            "Candidates are offline diagnostics over synthetic cycles, not live strategy changes.",
            "Validation-ready means ready for independent holdout validation, not live implementation.",
            "Gross synthetic results are not broker-backed net profitability.",
            "The prior P2-026B filter remains falsified and is not implemented here.",
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
    risk = payload["overfit_risk_summary"]
    candidates = payload["candidates"]
    leading = [row for row in candidates if row["status"] in {"validation_ready", "promising_needs_holdout"}]
    lines = [
        "=== P2-028 REDESIGNED ENTRY VALIDATION HARNESS ===",
        f"bars_scanned={payload['data_summary']['bars_scanned']}",
        f"synthetic_cycles_count={payload['data_summary']['synthetic_cycles_count']}",
        f"baseline_gross={baseline['gross_total']} median={baseline['median_gross']} win_rate={baseline['win_rate']}",
        f"candidate_families_evaluated={len(payload['candidate_families_evaluated'])}",
        f"validation_ready_count={risk['validation_ready_count']}",
        f"promising_needs_holdout_count={risk['promising_needs_holdout_count']}",
        f"rejected_count={risk['rejected_count']}",
        "",
        "Leading offline candidates:",
    ]
    if leading:
        for row in leading[:5]:
            lines.append(
                f"  {row['candidate_name']} status={row['status']} gross_delta={row['gross_delta_vs_baseline']} "
                f"win_rate={row['win_rate']} sample_size={row['sample_size']}"
            )
    else:
        lines.append("  none")
    lines.extend([
        "",
        "authorization: implementation_proposal=false implementation=false paper=false live=false scaling=false",
        f"recommended_next_patch={payload['recommended_next_patch']['patch_id']} {payload['recommended_next_patch']['target']}",
        "=== END REPORT ===",
    ])
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="P2-028 redesigned-entry validation harness")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--max-bars", type=int, default=100000)
    parser.add_argument("--max-cycles", type=int, default=2000)
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output; no write by default")
    args = parser.parse_args(argv)
    payload = build_redesigned_entry_validation_harness(data_dir=args.data_dir, max_bars=args.max_bars, max_cycles=args.max_cycles)
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
