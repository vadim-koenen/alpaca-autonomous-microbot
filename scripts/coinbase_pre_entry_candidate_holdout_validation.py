#!/usr/bin/env python3
"""
P2-026C fixed pre-entry candidate holdout validation.

Offline diagnostic report only. It validates the fixed P2-026B candidate
against chronological, folded, symbol, strategy, and threshold splits without
modifying trading behavior.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.coinbase_historical_signal_generator import (  # noqa: E402
    DATA_DIR,
    build_historical_signal_generator_report,
)

SCHEMA_VERSION = "p2-026c.pre_entry_candidate_holdout_validation.v1"
RULE_NAME = "exclude_pre_entry_return_3_above_p80_0.011338"
INPUT_FIELD = "pre_entry_return_3"
OPERATOR = ">"
DEFAULT_THRESHOLD = Decimal("0.011338")
MONEY_QUANT = Decimal("0.00000001")
RATE_QUANT = Decimal("0.000001")
MAX_TRADE_REMOVAL_RATE = Decimal("0.40")
MIN_HOLDOUT_AFTER = 20
PREFERRED_HOLDOUT_AFTER = 30
POST_ENTRY_FIELDS = {
    "exit_reason",
    "exit_price",
    "exit_time",
    "hold_duration_minutes",
    "max_adverse_excursion",
    "gross_pnl",
    "pnl_usd",
}
SENSITIVITY_THRESHOLDS = [
    Decimal("0.006"),
    Decimal("0.008"),
    Decimal("0.010"),
    DEFAULT_THRESHOLD,
    Decimal("0.012"),
    Decimal("0.014"),
    Decimal("0.016"),
]
PERCENTILES = [70, 75, 80, 85, 90]


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


def _is_stop_loss(cycle: Dict[str, Any]) -> bool:
    return "stop" in str(cycle.get("exit_reason", "")).lower()


def _entry_sort_key(cycle: Dict[str, Any]) -> Tuple[datetime, str, str]:
    raw = str(cycle.get("entry_time", ""))
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    except Exception:
        parsed = datetime.min.replace(tzinfo=timezone.utc)
    return parsed, str(cycle.get("symbol", "")), str(cycle.get("strategy", ""))


def _sorted_cycles(cycles: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(cycles, key=_entry_sort_key)


def _numeric_values(cycles: Sequence[Dict[str, Any]], field: str) -> List[Decimal]:
    values = [_to_decimal(cycle.get(field), Decimal("NaN")) for cycle in cycles]
    return [value for value in values if value.is_finite()]


def _percentile(values: Sequence[Decimal], percentile: int) -> Decimal:
    if not values:
        return Decimal("0")
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (Decimal(percentile) / Decimal("100")) * Decimal(len(sorted_values) - 1)
    idx = int(rank.to_integral_value(rounding=ROUND_HALF_UP))
    idx = min(max(idx, 0), len(sorted_values) - 1)
    return sorted_values[idx]


def _gross_stats(cycles: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    gross_values = [_cycle_gross(cycle) for cycle in cycles]
    total = _sum(gross_values)
    sample_size = len(cycles)
    winner_count = sum(1 for value in gross_values if value > 0)
    return {
        "sample_size": sample_size,
        "gross_total": total,
        "avg_gross": total / sample_size if sample_size else Decimal("0"),
        "median_gross": _median_decimal(gross_values),
        "win_rate": _rate(winner_count, sample_size),
        "winner_count": winner_count,
    }


def _concentration_warning(cycles: Sequence[Dict[str, Any]]) -> bool:
    gains = sorted(_cycle_gross(cycle) for cycle in cycles if _cycle_gross(cycle) > 0)
    if not gains:
        return False
    total_gains = _sum(gains)
    return total_gains > 0 and gains[-1] / total_gains > Decimal("0.50")


def _uses_candidate_rule(cycle: Dict[str, Any], *, threshold: Decimal, input_field: str = INPUT_FIELD) -> bool:
    return _to_decimal(cycle.get(input_field), Decimal("0")) > threshold


def _data_quality_warning(label: str, cycles: Sequence[Dict[str, Any]], removed: Sequence[Dict[str, Any]]) -> bool:
    label_has_algo = "ALGO/USD" in label or "ALGO_USD" in label
    cycle_symbols = {str(cycle.get("symbol", "")) for cycle in cycles}
    removed_symbols = {str(cycle.get("symbol", "")) for cycle in removed}
    return label_has_algo or cycle_symbols == {"ALGO/USD"} or removed_symbols == {"ALGO/USD"}


def evaluate_candidate_result(
    *,
    label: str,
    cycles: Sequence[Dict[str, Any]],
    threshold: Decimal = DEFAULT_THRESHOLD,
    input_field: str = INPUT_FIELD,
    min_after: int = MIN_HOLDOUT_AFTER,
) -> Dict[str, Any]:
    leakage_risk = input_field in POST_ENTRY_FIELDS
    pre_entry_only = not leakage_risk
    removed_indices = {
        idx
        for idx, cycle in enumerate(cycles)
        if pre_entry_only and _uses_candidate_rule(cycle, threshold=threshold, input_field=input_field)
    }
    removed = [cycle for idx, cycle in enumerate(cycles) if idx in removed_indices]
    remaining = [cycle for idx, cycle in enumerate(cycles) if idx not in removed_indices]
    before_stats = _gross_stats(cycles)
    after_stats = _gross_stats(remaining)
    stop_loss_before = sum(1 for cycle in cycles if _is_stop_loss(cycle))
    stop_loss_after = sum(1 for cycle in remaining if _is_stop_loss(cycle))
    sample_size_before = len(cycles)
    sample_size_after = len(remaining)
    trades_removed = len(removed)
    percent_trades_removed = Decimal(trades_removed) / Decimal(sample_size_before) if sample_size_before else Decimal("0")
    stop_loss_rate_before = Decimal(stop_loss_before) / Decimal(sample_size_before) if sample_size_before else Decimal("0")
    stop_loss_rate_after = Decimal(stop_loss_after) / Decimal(sample_size_after) if sample_size_after else Decimal("0")
    gross_delta = after_stats["gross_total"] - before_stats["gross_total"]
    concentration = _concentration_warning(remaining)
    data_quality = _data_quality_warning(label, cycles, removed)
    sample_size_warning = sample_size_after < min_after or sample_size_before < min_after
    overfit = sample_size_warning or trades_removed < 2 or sample_size_before < PREFERRED_HOLDOUT_AFTER

    failed_hard: List[str] = []
    failed_gates: List[str] = []
    if leakage_risk:
        failed_hard.append("leakage_risk=true")
    if not pre_entry_only:
        failed_hard.append("pre_entry_only=false")
    if sample_size_after < min_after:
        failed_hard.append(f"sample_size_after < {min_after}")
    if after_stats["gross_total"] <= before_stats["gross_total"]:
        failed_hard.append("gross_after <= gross_before")
    if after_stats["avg_gross"] <= 0:
        failed_hard.append("avg_gross_after <= 0")
    if after_stats["median_gross"] < 0:
        failed_hard.append("median_gross_after < 0")
    if Decimal(str(after_stats["win_rate"])) < Decimal("0.50"):
        failed_hard.append("win_rate_after < 0.50")
    if stop_loss_rate_after >= stop_loss_rate_before:
        failed_hard.append("stop_loss_rate_after not lower")
    if percent_trades_removed > MAX_TRADE_REMOVAL_RATE:
        failed_hard.append("percent_trades_removed > 40%")
    if concentration:
        failed_hard.append("single winner dominates")
    if sample_size_after < PREFERRED_HOLDOUT_AFTER:
        failed_gates.append("sample_size_after < 30 preferred")
    if data_quality:
        failed_gates.append("data_quality_warning")
    failed_gates = failed_hard + failed_gates

    return {
        "label": label,
        "threshold": _fmt_rate(threshold),
        "input_field": input_field,
        "sample_size_before": sample_size_before,
        "sample_size_after": sample_size_after,
        "trades_removed": trades_removed,
        "percent_trades_removed": _fmt_rate(percent_trades_removed),
        "gross_before": _fmt_money(before_stats["gross_total"]),
        "gross_after": _fmt_money(after_stats["gross_total"]),
        "gross_delta": _fmt_money(gross_delta),
        "avg_gross_after": _fmt_money(after_stats["avg_gross"]),
        "median_gross_after": _fmt_money(after_stats["median_gross"]),
        "win_rate_after": after_stats["win_rate"],
        "stop_loss_count_before": stop_loss_before,
        "stop_loss_count_after": stop_loss_after,
        "stop_loss_rate_before": _fmt_rate(stop_loss_rate_before),
        "stop_loss_rate_after": _fmt_rate(stop_loss_rate_after),
        "concentration_warning": concentration,
        "overfit_warning": overfit,
        "data_quality_warning": data_quality,
        "sample_size_warning": sample_size_warning,
        "passes_gate": not failed_hard,
        "failed_gates": failed_gates,
    }


def chronological_split(cycles: Sequence[Dict[str, Any]], train_fraction: Decimal = Decimal("0.70")) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    ordered = _sorted_cycles(cycles)
    if not ordered:
        return [], []
    split_idx = int((Decimal(len(ordered)) * train_fraction).to_integral_value(rounding=ROUND_HALF_UP))
    split_idx = min(max(split_idx, 1), len(ordered) - 1) if len(ordered) > 1 else len(ordered)
    return ordered[:split_idx], ordered[split_idx:]


def rolling_folds(cycles: Sequence[Dict[str, Any]], folds: int = 4) -> List[List[Dict[str, Any]]]:
    ordered = _sorted_cycles(cycles)
    if not ordered:
        return []
    fold_count = min(max(folds, 3), 5, len(ordered))
    base_size = len(ordered) // fold_count
    remainder = len(ordered) % fold_count
    results = []
    start = 0
    for idx in range(fold_count):
        size = base_size + (1 if idx < remainder else 0)
        end = start + size
        results.append(ordered[start:end])
        start = end
    return results


def grouped_results(
    *,
    cycles: Sequence[Dict[str, Any]],
    key_fields: Sequence[str],
    label_prefix: str,
    threshold: Decimal,
) -> List[Dict[str, Any]]:
    groups: Dict[Tuple[str, ...], List[Dict[str, Any]]] = defaultdict(list)
    for cycle in cycles:
        key = tuple(str(cycle.get(field, "unknown")) for field in key_fields)
        groups[key].append(cycle)
    rows = []
    for key, group_cycles in sorted(groups.items()):
        label = f"{label_prefix}=" + "|".join(key)
        row = evaluate_candidate_result(label=label, cycles=group_cycles, threshold=threshold)
        row["group_key"] = "|".join(key)
        rows.append(row)
    return rows


def _positive_effect(row: Dict[str, Any]) -> bool:
    return _to_decimal(row.get("gross_delta")) > 0 and _to_decimal(row.get("stop_loss_rate_after")) < _to_decimal(row.get("stop_loss_rate_before"))


def _source_summary(source_payload: Dict[str, Any], cycles: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    stats = _gross_stats(cycles)
    stop_loss_count = sum(1 for cycle in cycles if _is_stop_loss(cycle))
    return {
        "bars_scanned": source_payload.get("bars_scanned", 0),
        "synthetic_cycles_count": len(cycles),
        "baseline_gross": _fmt_money(stats["gross_total"]),
        "baseline_win_rate": stats["win_rate"],
        "baseline_stop_loss_count": stop_loss_count,
        "leakage_guards": source_payload.get("leakage_guards", {}),
    }


def _threshold_sensitivity(cycles: Sequence[Dict[str, Any]], thresholds: Sequence[Decimal]) -> List[Dict[str, Any]]:
    return [
        evaluate_candidate_result(label=f"threshold_{_fmt_rate(threshold)}", cycles=cycles, threshold=threshold)
        for threshold in thresholds
    ]


def _percentile_sensitivity(cycles: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    values = _numeric_values(cycles, INPUT_FIELD)
    rows = []
    for percentile in PERCENTILES:
        threshold = _percentile(values, percentile)
        row = evaluate_candidate_result(label=f"full_sample_p{percentile}", cycles=cycles, threshold=threshold)
        row["percentile"] = percentile
        row["diagnostic_not_holdout_safe"] = True
        rows.append(row)
    return rows


def build_holdout_validation_report(
    *,
    data_dir: Optional[Path] = None,
    threshold: Decimal = DEFAULT_THRESHOLD,
    max_bars: Optional[int] = 50000,
    max_cycles: Optional[int] = 1000,
    folds: int = 4,
    source_payload: Optional[Dict[str, Any]] = None,
    synthetic_cycles: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if source_payload is None:
        source_payload = build_historical_signal_generator_report(
            data_dir=data_dir or DATA_DIR,
            max_bars=max_bars,
            max_cycles=max_cycles,
        )
    cycles = _sorted_cycles(synthetic_cycles if synthetic_cycles is not None else source_payload.get("synthetic_cycles", []))
    train_cycles, holdout_cycles = chronological_split(cycles)

    full_sample = evaluate_candidate_result(label="full_sample", cycles=cycles, threshold=threshold)
    train_result = evaluate_candidate_result(label="chronological_train_70pct", cycles=train_cycles, threshold=threshold)
    holdout_result = evaluate_candidate_result(label="chronological_holdout_30pct", cycles=holdout_cycles, threshold=threshold)
    fold_results = [
        evaluate_candidate_result(label=f"fold_{idx + 1}", cycles=fold_cycles, threshold=threshold)
        | {"fold_index": idx + 1}
        for idx, fold_cycles in enumerate(rolling_folds(cycles, folds=folds))
    ]
    symbol_rows = grouped_results(cycles=cycles, key_fields=["symbol"], label_prefix="symbol", threshold=threshold)
    strategy_rows = grouped_results(cycles=cycles, key_fields=["strategy"], label_prefix="strategy", threshold=threshold)
    symbol_strategy_rows = grouped_results(
        cycles=cycles,
        key_fields=["symbol", "strategy"],
        label_prefix="symbol_strategy",
        threshold=threshold,
    )
    threshold_rows = _threshold_sensitivity(cycles, SENSITIVITY_THRESHOLDS)
    percentile_rows = _percentile_sensitivity(cycles)

    positive_folds = [row for row in fold_results if _positive_effect(row)]
    positive_symbols = [row for row in symbol_rows if _positive_effect(row)]
    positive_strategies = [row for row in strategy_rows if _positive_effect(row)]
    non_algo_cycles = [cycle for cycle in cycles if cycle.get("symbol") != "ALGO/USD"]
    non_algo_result = evaluate_candidate_result(label="non_algo_excluding_algo_dependency_check", cycles=non_algo_cycles, threshold=threshold)
    threshold_positive = [row for row in threshold_rows if _positive_effect(row) and row["passes_gate"]]
    selected_neighbor_count = sum(
        1
        for row in threshold_rows
        if row["threshold"] != _fmt_rate(threshold)
        and abs(_to_decimal(row["threshold"]) - threshold) <= Decimal("0.004")
        and _positive_effect(row)
    )
    depends_on_algo = _positive_effect(full_sample) and not _positive_effect(non_algo_result)
    depends_on_one_strategy = _positive_effect(full_sample) and len(positive_strategies) <= 1
    stable_across_folds = len(positive_folds) >= 2
    threshold_robust = len(threshold_positive) >= 3 and selected_neighbor_count >= 1
    holdout_validated = holdout_result["passes_gate"] and stable_across_folds and not depends_on_algo and not depends_on_one_strategy and threshold_robust
    provisionally_stable = (
        not holdout_validated
        and holdout_result["passes_gate"]
        and stable_across_folds
        and not depends_on_algo
        and selected_neighbor_count >= 1
    )
    likely_overfit = not holdout_validated and not provisionally_stable
    if holdout_validated:
        verdict = "holdout_validated"
    elif provisionally_stable:
        verdict = "provisionally_stable"
    elif INPUT_FIELD in POST_ENTRY_FIELDS:
        verdict = "rejected"
    else:
        verdict = "unstable_or_overfit"

    return {
        "schema_version": SCHEMA_VERSION,
        "report_class": "pre_entry_candidate_holdout_validation",
        "candidate": {
            "rule_name": RULE_NAME,
            "input_field": INPUT_FIELD,
            "operator": OPERATOR,
            "threshold": _fmt_rate(threshold),
            "action": "exclude_trade",
            "pre_entry_only": True,
            "leakage_risk": False,
        },
        "source_synthetic_summary": _source_summary(source_payload, cycles),
        "full_sample_result": full_sample,
        "chronological_train_result": train_result,
        "chronological_holdout_result": holdout_result,
        "rolling_fold_results": fold_results,
        "symbol_stability": symbol_rows,
        "strategy_stability": strategy_rows,
        "symbol_strategy_stability": symbol_strategy_rows,
        "threshold_sensitivity": threshold_rows,
        "percentile_sensitivity_diagnostic": percentile_rows,
        "stability_checks": {
            "positive_fold_count": len(positive_folds),
            "positive_symbol_count": len(positive_symbols),
            "positive_strategy_count": len(positive_strategies),
            "stable_across_folds": stable_across_folds,
            "depends_on_algo_usd": depends_on_algo,
            "depends_on_one_strategy": depends_on_one_strategy,
            "threshold_robust": threshold_robust,
            "selected_threshold_neighbor_positive_count": selected_neighbor_count,
            "exact_threshold_overfit_risk": not threshold_robust,
            "non_algo_result": non_algo_result,
        },
        "stability_verdict": {
            "verdict": verdict,
            "holdout_validated": holdout_validated,
            "provisionally_stable": provisionally_stable,
            "likely_overfit": likely_overfit,
            "implementation_proposal_authorized": holdout_validated,
            "implementation_authorized": False,
            "paper_probe_authorized": False,
            "live_probe_authorized": False,
            "scaling_authorized": False,
        },
        "limitations": [
            "The candidate was selected from the same synthetic cycle sample in P2-026B.",
            "Synthetic cycles are not live fills.",
            "Small symbols and folds can be too narrow for implementation confidence.",
            "Percentile sensitivity recomputes full-sample thresholds and is diagnostic only.",
            "OHLCV does not include order-book depth, queue position, or realized fee drag.",
            "ALGO/USD has a known local data-quality caveat.",
        ],
        "next_step_recommendation": (
            "If the candidate is not holdout validated, continue offline stability work with larger or independent slices. "
            "Do not implement the filter, tune exits, run probes, restart, or scale from this report."
        ),
    }


def write_report(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _human_summary(payload: Dict[str, Any]) -> str:
    source = payload["source_synthetic_summary"]
    verdict = payload["stability_verdict"]
    holdout = payload["chronological_holdout_result"]
    checks = payload["stability_checks"]
    lines = [
        "=== P2-026C PRE-ENTRY CANDIDATE HOLDOUT VALIDATION ===",
        f"rule_name={payload['candidate']['rule_name']}",
        f"input_field={payload['candidate']['input_field']}",
        f"threshold={payload['candidate']['threshold']}",
        f"bars_scanned={source['bars_scanned']}",
        f"synthetic_cycles_count={source['synthetic_cycles_count']}",
        f"baseline_gross={source['baseline_gross']} win_rate={source['baseline_win_rate']}",
        f"baseline_stop_loss_count={source['baseline_stop_loss_count']}",
        "",
        "Holdout result:",
        f"  sample_size_before={holdout['sample_size_before']} sample_size_after={holdout['sample_size_after']}",
        f"  gross_before={holdout['gross_before']} gross_after={holdout['gross_after']} gross_delta={holdout['gross_delta']}",
        f"  stop_loss_rate_before={holdout['stop_loss_rate_before']} stop_loss_rate_after={holdout['stop_loss_rate_after']}",
        f"  passes_gate={str(holdout['passes_gate']).lower()} failed_gates={holdout['failed_gates']}",
        "",
        f"positive_fold_count={checks['positive_fold_count']}",
        f"stable_across_folds={str(checks['stable_across_folds']).lower()}",
        f"depends_on_algo_usd={str(checks['depends_on_algo_usd']).lower()}",
        f"depends_on_one_strategy={str(checks['depends_on_one_strategy']).lower()}",
        f"threshold_robust={str(checks['threshold_robust']).lower()}",
        "",
        f"verdict={verdict['verdict']}",
        f"holdout_validated={str(verdict['holdout_validated']).lower()}",
        f"provisionally_stable={str(verdict['provisionally_stable']).lower()}",
        f"likely_overfit={str(verdict['likely_overfit']).lower()}",
        f"implementation_proposal_authorized={str(verdict['implementation_proposal_authorized']).lower()}",
        "Permission verdict: implementation=false paper=false live=false scaling=false",
        f"Next: {payload['next_step_recommendation']}",
        "=== END REPORT ===",
    ]
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="P2-026C pre-entry candidate holdout validation")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--threshold", type=Decimal, default=DEFAULT_THRESHOLD)
    parser.add_argument("--max-bars", type=int, default=50000)
    parser.add_argument("--max-cycles", type=int, default=1000)
    parser.add_argument("--folds", type=int, default=4)
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output; no write by default")
    args = parser.parse_args(argv)

    payload = build_holdout_validation_report(
        data_dir=args.data_dir,
        threshold=args.threshold,
        max_bars=args.max_bars,
        max_cycles=args.max_cycles,
        folds=args.folds,
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
