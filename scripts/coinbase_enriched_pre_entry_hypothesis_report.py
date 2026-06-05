#!/usr/bin/env python3
"""
P2-026B enriched pre-entry hypothesis testing.

Offline-only. Consumes P2-026A synthetic cycles and evaluates analysis-only
pre-entry hypotheses. Stop-loss outcome is used only as an evaluation target,
never as an input filter. No broker clients, network fetches, runtime/config
mutation, strategy changes, or live orders.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from statistics import median
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.coinbase_historical_signal_generator import (  # noqa: E402
    DATA_DIR,
    PRE_ENTRY_FEATURE_SCHEMA,
    build_historical_signal_generator_report,
)

SCHEMA_VERSION = "p2-026b.coinbase_enriched_pre_entry_hypothesis_testing.v1"
MONEY_QUANT = Decimal("0.00000001")
RATE_QUANT = Decimal("0.000001")
PREFERRED_SAMPLE_SIZE = 50
MINIMUM_SAMPLE_SIZE = 30
MAX_TRADE_REMOVAL_RATE = Decimal("0.40")
MATERIAL_GROSS_IMPROVEMENT = Decimal("0.05")
MATERIAL_STOP_LOSS_RATE_REDUCTION = Decimal("0.20")
MIN_STOP_LOSS_REMOVAL_RATE = Decimal("0.25")

SINGLE_FIELD_FEATURES = [
    "pre_entry_symbol_strategy_key",
    "symbol",
    "strategy",
    "pre_entry_regime",
    "pre_entry_confidence_bucket",
    "pre_entry_momentum_bucket",
    "pre_entry_volatility_bucket",
    "pre_entry_atr_bucket",
    "pre_entry_liquidity_bucket",
    "pre_entry_volume_ratio_12_bucket",
    "pre_entry_hour_utc_bucket",
    "pre_entry_day_of_week_utc",
    "pre_entry_session_bucket",
]

NUMERIC_THRESHOLD_SPECS = [
    ("pre_entry_volatility_12", "above", [70, 80, 90]),
    ("pre_entry_atr_14", "above", [70, 80, 90]),
    ("pre_entry_return_3", "below", [10, 20, 30]),
    ("pre_entry_return_3", "above", [70, 80, 90]),
    ("pre_entry_return_6", "below", [10, 20, 30]),
    ("pre_entry_return_6", "above", [70, 80, 90]),
    ("pre_entry_volume_ratio_12", "below", [10, 20, 30]),
    ("pre_entry_range_pct_3", "above", [70, 80, 90]),
]

COMBINATION_FEATURES = [
    ("pre_entry_symbol_strategy_key", "pre_entry_volatility_bucket"),
    ("pre_entry_symbol_strategy_key", "pre_entry_momentum_bucket"),
    ("pre_entry_symbol_strategy_key", "pre_entry_atr_bucket"),
    ("pre_entry_symbol_strategy_key", "pre_entry_liquidity_bucket"),
    ("pre_entry_session_bucket", "strategy"),
    ("pre_entry_regime", "strategy"),
]

FOCUSED_COMBINATIONS = [
    ("ALGO/USD", "momentum_breakout", "pre_entry_volatility_bucket"),
    ("ALGO/USD", "momentum_breakout", "pre_entry_momentum_bucket"),
    ("ALGO/USD", "momentum_breakout", "pre_entry_atr_bucket"),
    ("ALGO/USD", "momentum_breakout", "pre_entry_liquidity_bucket"),
]


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


def _cycle_gross(cycle: Dict[str, Any]) -> Decimal:
    return _to_decimal(cycle.get("gross_pnl", cycle.get("pnl_usd", "0")))


def _sum(values: Iterable[Decimal]) -> Decimal:
    total = Decimal("0")
    for value in values:
        total += value
    return total


def _median_decimal(values: Sequence[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    return Decimal(str(median([float(value) for value in values])))


def _is_stop_loss(cycle: Dict[str, Any]) -> bool:
    return "stop" in str(cycle.get("exit_reason", "")).lower()


def _confidence_bucket(value: Any) -> str:
    confidence = _to_decimal(value, Decimal("-1"))
    if confidence < 0:
        return "unknown"
    if confidence < Decimal("0.75"):
        return "<0.75"
    if confidence < Decimal("0.85"):
        return "0.75-0.85"
    if confidence < Decimal("0.95"):
        return "0.85-0.95"
    return ">=0.95"


def _hour_bucket(value: Any) -> str:
    try:
        hour = int(value)
    except Exception:
        return "unknown"
    if hour < 6:
        return "00-05"
    if hour < 12:
        return "06-11"
    if hour < 18:
        return "12-17"
    return "18-23"


def _value(cycle: Dict[str, Any], feature: str) -> str:
    if feature == "pre_entry_confidence_bucket":
        return _confidence_bucket(cycle.get("pre_entry_confidence", cycle.get("confidence")))
    if feature == "pre_entry_hour_utc_bucket":
        return _hour_bucket(cycle.get("pre_entry_hour_utc"))
    if feature == "pre_entry_volume_ratio_12_bucket":
        return str(cycle.get("pre_entry_liquidity_bucket", "unknown"))
    if feature == "symbol":
        return str(cycle.get("symbol", "unknown"))
    if feature == "strategy":
        return str(cycle.get("strategy", "unknown"))
    if feature == "exit_reason":
        return str(cycle.get("exit_reason", "unknown"))
    return str(cycle.get(feature, "unknown"))


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
    lower = int(rank.to_integral_value(rounding=ROUND_HALF_UP))
    lower = min(max(lower, 0), len(sorted_values) - 1)
    return sorted_values[lower]


def _gross_stats(cycles: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    gross_values = [_cycle_gross(cycle) for cycle in cycles]
    total = _sum(gross_values)
    sample_size = len(cycles)
    winners = sum(1 for value in gross_values if value > 0)
    losers = sum(1 for value in gross_values if value < 0)
    return {
        "sample_size": sample_size,
        "gross_total": total,
        "avg_gross": total / sample_size if sample_size else Decimal("0"),
        "median_gross": _median_decimal(gross_values),
        "win_rate": _rate(winners, sample_size),
        "winner_count": winners,
        "loser_count": losers,
    }


def _concentration_warning(cycles: Sequence[Dict[str, Any]]) -> bool:
    gross_values = [_cycle_gross(cycle) for cycle in cycles]
    gains = sorted(value for value in gross_values if value > 0)
    if not gains:
        return False
    total_gains = _sum(gains)
    return total_gains > 0 and gains[-1] / total_gains > Decimal("0.50")


def _data_quality_warning(hypothesis_name: str, removed_rows: Sequence[Dict[str, Any]]) -> bool:
    if "ALGO/USD" in hypothesis_name:
        return True
    removed_symbols = {str(cycle.get("symbol", "")) for cycle in removed_rows}
    return removed_symbols == {"ALGO/USD"} and len(removed_rows) >= 3


def _evaluate_hypothesis(
    *,
    name: str,
    family: str,
    input_fields: Sequence[str],
    cycles: Sequence[Dict[str, Any]],
    remove_predicate: Callable[[Dict[str, Any]], bool],
    baseline_stats: Dict[str, Any],
    baseline_stop_loss_count: int,
    baseline_stop_loss_rate: Decimal,
    analysis_only: bool = True,
) -> Dict[str, Any]:
    post_entry_fields = {"exit_reason", "exit_price", "hold_duration_minutes", "exit_basis", "gross_pnl", "pnl_usd"}
    leakage_risk = any(field in post_entry_fields for field in input_fields)
    pre_entry_only = not leakage_risk
    removed = [cycle for cycle in cycles if remove_predicate(cycle)]
    remaining = [cycle for cycle in cycles if not remove_predicate(cycle)]
    after_stats = _gross_stats(remaining)
    stop_loss_after = sum(1 for cycle in remaining if _is_stop_loss(cycle))
    stop_loss_removed = sum(1 for cycle in removed if _is_stop_loss(cycle))
    sample_before = len(cycles)
    sample_after = len(remaining)
    trades_removed = len(removed)
    percent_trades_removed = Decimal(trades_removed) / Decimal(sample_before) if sample_before else Decimal("0")
    percent_stop_loss_removed = (
        Decimal(stop_loss_removed) / Decimal(baseline_stop_loss_count) if baseline_stop_loss_count else Decimal("0")
    )
    stop_loss_rate_after = Decimal(stop_loss_after) / Decimal(sample_after) if sample_after else Decimal("0")
    gross_before = baseline_stats["gross_total"]
    gross_after = after_stats["gross_total"]
    gross_delta = gross_after - gross_before
    concentration = _concentration_warning(remaining)
    data_quality = _data_quality_warning(name, removed)
    overfit = sample_after < PREFERRED_SAMPLE_SIZE or trades_removed < 3 or stop_loss_removed < 2 or len(input_fields) > 2

    failed_gates: List[str] = []
    if not pre_entry_only:
        failed_gates.append("pre_entry_only=false")
    if leakage_risk:
        failed_gates.append("leakage_risk=true")
    if sample_after < MINIMUM_SAMPLE_SIZE:
        failed_gates.append("sample_size_after < 30")
    if gross_after <= gross_before:
        failed_gates.append("gross_after <= gross_before")
    if after_stats["avg_gross"] <= 0:
        failed_gates.append("avg_gross_after <= 0")
    if after_stats["median_gross"] < 0:
        failed_gates.append("median_gross_after < 0")
    if Decimal(str(after_stats["win_rate"])) < Decimal("0.52"):
        failed_gates.append("win_rate_after < 0.52")
    if stop_loss_rate_after > baseline_stop_loss_rate * (Decimal("1") - MATERIAL_STOP_LOSS_RATE_REDUCTION):
        failed_gates.append("stop_loss_rate_after not materially lower")
    material_gross = gross_delta >= MATERIAL_GROSS_IMPROVEMENT
    if percent_stop_loss_removed < MIN_STOP_LOSS_REMOVAL_RATE and not material_gross:
        failed_gates.append("insufficient stop-loss removal and gross improvement")
    if percent_trades_removed > MAX_TRADE_REMOVAL_RATE:
        failed_gates.append("percent_trades_removed > 40%")
    if concentration:
        failed_gates.append("single winner dominates")
    if sample_after < PREFERRED_SAMPLE_SIZE:
        failed_gates.append("sample_size_after < 50 preferred")
    if data_quality:
        failed_gates.append("data_quality_warning")
    if trades_removed == sample_before:
        failed_gates.append("removed all trades")

    if leakage_risk:
        status = "rejected"
    elif sample_after < MINIMUM_SAMPLE_SIZE or percent_trades_removed > Decimal("0.70") or len(input_fields) > 2:
        status = "likely_overfit"
    elif not failed_gates:
        status = "validated_candidate"
    elif (
        pre_entry_only
        and sample_after >= MINIMUM_SAMPLE_SIZE
        and gross_after > gross_before
        and after_stats["avg_gross"] > 0
        and after_stats["median_gross"] >= 0
        and Decimal(str(after_stats["win_rate"])) >= Decimal("0.50")
        and not concentration
    ):
        status = "provisional_candidate" if data_quality or sample_after < PREFERRED_SAMPLE_SIZE else "diagnostic_only"
    elif overfit:
        status = "likely_overfit"
    else:
        status = "rejected"

    implementation_candidate = status == "validated_candidate"
    return {
        "hypothesis_name": name,
        "family": family,
        "analysis_only": analysis_only,
        "input_fields_used": list(input_fields),
        "leakage_risk": leakage_risk,
        "pre_entry_only": pre_entry_only,
        "sample_size_before": sample_before,
        "sample_size_after": sample_after,
        "trades_removed": trades_removed,
        "percent_trades_removed": _fmt_rate(percent_trades_removed),
        "stop_loss_removed": stop_loss_removed,
        "percent_stop_loss_removed": _fmt_rate(percent_stop_loss_removed),
        "gross_before": _fmt_money(gross_before),
        "gross_after": _fmt_money(gross_after),
        "gross_delta": _fmt_money(gross_delta),
        "avg_gross_after": _fmt_money(after_stats["avg_gross"]),
        "median_gross_after": _fmt_money(after_stats["median_gross"]),
        "win_rate_after": after_stats["win_rate"],
        "stop_loss_rate_before": _fmt_rate(baseline_stop_loss_rate),
        "stop_loss_rate_after": _fmt_rate(stop_loss_rate_after),
        "concentration_warning": concentration,
        "overfit_warning": overfit,
        "data_quality_warning": data_quality,
        "implementation_candidate": implementation_candidate,
        "implementation_authorized": False,
        "status": status,
        "failed_gates": failed_gates,
    }


def _single_field_hypotheses(cycles: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    specs = []
    for feature in SINGLE_FIELD_FEATURES:
        values = sorted({_value(cycle, feature) for cycle in cycles})
        for value in values:
            if value in {"", "unknown", "None"}:
                continue
            specs.append(
                {
                    "name": f"exclude_{feature}_{value}",
                    "family": "single_field",
                    "input_fields": [feature],
                    "remove": lambda cycle, feature=feature, value=value: _value(cycle, feature) == value,
                }
            )
    return specs


def _numeric_threshold_hypotheses(cycles: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    specs = []
    for field, direction, percentiles in NUMERIC_THRESHOLD_SPECS:
        values = _numeric_values(cycles, field)
        for pct in percentiles:
            threshold = _percentile(values, pct)
            if direction == "above":
                name = f"exclude_{field}_above_p{pct}_{_fmt_rate(threshold)}"
                remove = lambda cycle, field=field, threshold=threshold: _to_decimal(cycle.get(field)) > threshold
            else:
                name = f"exclude_{field}_below_p{pct}_{_fmt_rate(threshold)}"
                remove = lambda cycle, field=field, threshold=threshold: _to_decimal(cycle.get(field)) < threshold
            specs.append(
                {
                    "name": name,
                    "family": "numeric_threshold",
                    "input_fields": [field],
                    "remove": remove,
                    "threshold": _fmt_rate(threshold),
                    "percentile": pct,
                    "direction": direction,
                }
            )
    return specs


def _combination_hypotheses(cycles: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    specs = []
    for left, right in COMBINATION_FEATURES:
        pairs = sorted({(_value(cycle, left), _value(cycle, right)) for cycle in cycles})
        for left_value, right_value in pairs:
            if "unknown" in {left_value, right_value}:
                continue
            specs.append(
                {
                    "name": f"exclude_{left}_{left_value}__{right}_{right_value}",
                    "family": "combination",
                    "input_fields": [left, right],
                    "remove": lambda cycle, left=left, right=right, left_value=left_value, right_value=right_value: (
                        _value(cycle, left) == left_value and _value(cycle, right) == right_value
                    ),
                }
            )
    for symbol, strategy, feature in FOCUSED_COMBINATIONS:
        values = sorted({_value(cycle, feature) for cycle in cycles if cycle.get("symbol") == symbol and cycle.get("strategy") == strategy})
        for value in values:
            specs.append(
                {
                    "name": f"exclude_{symbol}_{strategy}_{feature}_{value}",
                    "family": "focused_combination",
                    "input_fields": ["symbol", "strategy", feature],
                    "remove": lambda cycle, symbol=symbol, strategy=strategy, feature=feature, value=value: (
                        cycle.get("symbol") == symbol and cycle.get("strategy") == strategy and _value(cycle, feature) == value
                    ),
                }
            )
    return specs


def _intent_hypotheses(cycles: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    volatility_values = _numeric_values(cycles, "pre_entry_volatility_12")
    atr_values = _numeric_values(cycles, "pre_entry_atr_14")
    volume_values = _numeric_values(cycles, "pre_entry_volume_ratio_12")
    return [
        {
            "name": "exclude_momentum_breakout_high_volatility_p80",
            "family": "strategy_numeric_combo",
            "input_fields": ["strategy", "pre_entry_volatility_12"],
            "remove": lambda cycle, threshold=_percentile(volatility_values, 80): (
                cycle.get("strategy") == "momentum_breakout" and _to_decimal(cycle.get("pre_entry_volatility_12")) > threshold
            ),
        },
        {
            "name": "exclude_momentum_breakout_adverse_momentum",
            "family": "strategy_bucket_combo",
            "input_fields": ["strategy", "pre_entry_momentum_bucket"],
            "remove": lambda cycle: (
                cycle.get("strategy") == "momentum_breakout"
                and _value(cycle, "pre_entry_momentum_bucket") in {"<=-1%", "-1%--0.5%", "-0.5%-0"}
            ),
        },
        {
            "name": "exclude_momentum_breakout_low_liquidity",
            "family": "strategy_bucket_combo",
            "input_fields": ["strategy", "pre_entry_liquidity_bucket"],
            "remove": lambda cycle: (
                cycle.get("strategy") == "momentum_breakout"
                and _value(cycle, "pre_entry_liquidity_bucket") in {"thin_<0.5x", "below_avg_0.5x_0.9x"}
            ),
        },
        {
            "name": "exclude_ALGO_USD_high_ATR_p80",
            "family": "symbol_numeric_combo",
            "input_fields": ["symbol", "pre_entry_atr_14"],
            "remove": lambda cycle, threshold=_percentile(atr_values, 80): (
                cycle.get("symbol") == "ALGO/USD" and _to_decimal(cycle.get("pre_entry_atr_14")) > threshold
            ),
        },
        {
            "name": "exclude_ALGO_USD_adverse_momentum",
            "family": "symbol_bucket_combo",
            "input_fields": ["symbol", "pre_entry_momentum_bucket"],
            "remove": lambda cycle: (
                cycle.get("symbol") == "ALGO/USD"
                and _value(cycle, "pre_entry_momentum_bucket") in {"<=-1%", "-1%--0.5%", "-0.5%-0"}
            ),
        },
        {
            "name": "exclude_ALGO_USD_low_volume_ratio_p30",
            "family": "symbol_numeric_combo",
            "input_fields": ["symbol", "pre_entry_volume_ratio_12"],
            "remove": lambda cycle, threshold=_percentile(volume_values, 30): (
                cycle.get("symbol") == "ALGO/USD" and _to_decimal(cycle.get("pre_entry_volume_ratio_12")) < threshold
            ),
        },
    ]


def _leakage_control_hypothesis() -> Dict[str, Any]:
    return {
        "name": "reject_exit_reason_stop_loss_as_input",
        "family": "leakage_control",
        "input_fields": ["exit_reason"],
        "remove": lambda cycle: _is_stop_loss(cycle),
    }


def _rank(rows: Sequence[Dict[str, Any]], field: str, limit: int) -> List[Dict[str, Any]]:
    return sorted(rows, key=lambda row: _to_decimal(row.get(field)), reverse=True)[:limit]


def _candidate_rank_pool(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        row
        for row in rows
        if row.get("pre_entry_only") is True
        and row.get("leakage_risk") is False
        and row.get("status") != "rejected"
    ]


def _source_summary(source_payload: Dict[str, Any], cycles: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    baseline_stats = _gross_stats(cycles)
    stop_loss_count = sum(1 for cycle in cycles if _is_stop_loss(cycle))
    stop_loss_rate = Decimal(stop_loss_count) / Decimal(len(cycles)) if cycles else Decimal("0")
    return {
        "bars_scanned": source_payload.get("bars_scanned", 0),
        "synthetic_cycles_count": len(cycles),
        "baseline_gross": _fmt_money(baseline_stats["gross_total"]),
        "baseline_win_rate": baseline_stats["win_rate"],
        "baseline_stop_loss_count": stop_loss_count,
        "baseline_stop_loss_rate": _fmt_rate(stop_loss_rate),
        "leakage_guards": source_payload.get("leakage_guards", {}),
    }


def build_enriched_pre_entry_hypothesis_report(
    *,
    data_dir: Optional[Path] = None,
    max_bars: Optional[int] = 50000,
    max_cycles: Optional[int] = 1000,
    top_n: int = 20,
    source_payload: Optional[Dict[str, Any]] = None,
    synthetic_cycles: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if source_payload is None:
        source_payload = build_historical_signal_generator_report(
            data_dir=data_dir or DATA_DIR,
            max_bars=max_bars,
            max_cycles=max_cycles,
        )
    cycles = list(synthetic_cycles if synthetic_cycles is not None else source_payload.get("synthetic_cycles", []))
    baseline_stats = _gross_stats(cycles)
    baseline_stop_loss_count = sum(1 for cycle in cycles if _is_stop_loss(cycle))
    baseline_stop_loss_rate = Decimal(baseline_stop_loss_count) / Decimal(len(cycles)) if cycles else Decimal("0")

    specs = []
    specs.extend(_single_field_hypotheses(cycles))
    specs.extend(_numeric_threshold_hypotheses(cycles))
    specs.extend(_combination_hypotheses(cycles))
    specs.extend(_intent_hypotheses(cycles))
    specs.append(_leakage_control_hypothesis())

    seen = set()
    unique_specs = []
    for spec in specs:
        if spec["name"] in seen:
            continue
        seen.add(spec["name"])
        unique_specs.append(spec)

    rows = [
        _evaluate_hypothesis(
            name=spec["name"],
            family=spec["family"],
            input_fields=spec["input_fields"],
            cycles=cycles,
            remove_predicate=spec["remove"],
            baseline_stats=baseline_stats,
            baseline_stop_loss_count=baseline_stop_loss_count,
            baseline_stop_loss_rate=baseline_stop_loss_rate,
        )
        for spec in unique_specs
    ]
    rows = sorted(
        rows,
        key=lambda row: (
            row["status"] == "validated_candidate",
            row["status"] == "provisional_candidate",
            _to_decimal(row["gross_delta"]),
            _to_decimal(row["percent_stop_loss_removed"]),
        ),
        reverse=True,
    )
    validated = [row for row in rows if row["status"] == "validated_candidate"]
    provisional = [row for row in rows if row["status"] == "provisional_candidate"]
    diagnostic = [row for row in rows if row["status"] == "diagnostic_only"]
    rejected = [row for row in rows if row["status"] == "rejected"]
    overfit = [row for row in rows if row["status"] == "likely_overfit"]
    best = (validated or provisional or diagnostic or rows or [None])[0]
    available_fields = (
        PRE_ENTRY_FEATURE_SCHEMA["numeric_fields"]
        + PRE_ENTRY_FEATURE_SCHEMA["categorical_fields"]
        + ["symbol", "strategy"]
    )
    unavailable_fields = [
        "order_book_spread",
        "bid_ask_depth",
        "maker_taker_fee_estimate",
        "order_book_liquidity_bucket",
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "report_class": "enriched_pre_entry_hypothesis_testing",
        "source_synthetic_summary": _source_summary(source_payload, cycles),
        "feature_schema": {
            "available_pre_entry_fields": available_fields,
            "unavailable_fields": unavailable_fields,
        },
        "feature_families_tested": {
            "single_field": SINGLE_FIELD_FEATURES,
            "numeric_threshold": [field for field, _, _ in NUMERIC_THRESHOLD_SPECS],
            "combination": [list(pair) for pair in COMBINATION_FEATURES],
            "focused_combination": [list(item) for item in FOCUSED_COMBINATIONS],
            "leakage_control": ["exit_reason"],
        },
        "hypothesis_results": rows,
        "top_candidates_by_gross_delta": _rank(_candidate_rank_pool(rows), "gross_delta", top_n),
        "top_candidates_by_stop_loss_reduction": _rank(
            _candidate_rank_pool(rows), "percent_stop_loss_removed", top_n
        ),
        "validated_candidates": validated,
        "provisional_candidates": provisional,
        "diagnostic_only_candidates": diagnostic[:top_n],
        "rejected_candidates_count": len(rejected),
        "likely_overfit_count": len(overfit),
        "best_candidate": best,
        "implementation_verdict": {
            "any_validated_candidate_found": bool(validated),
            "any_provisional_candidate_found": bool(provisional),
            "implementation_authorized": False,
            "paper_probe_authorized": False,
            "live_probe_authorized": False,
            "scaling_authorized": False,
        },
        "leakage_controls": {
            "uses_only_pre_entry_fields_for_filters": True,
            "stop_loss_outcome_used_only_as_target": True,
            "exit_reason_filter_input_rejected": any(
                row["hypothesis_name"] == "reject_exit_reason_stop_loss_as_input" and row["leakage_risk"]
                for row in rows
            ),
            "pre_entry_features_use_only_past_bars": source_payload.get("leakage_guards", {}).get(
                "pre_entry_features_use_only_past_bars", False
            ),
            "no_exit_reason_in_pre_entry_features": source_payload.get("leakage_guards", {}).get(
                "no_exit_reason_in_pre_entry_features", False
            ),
            "no_future_path_in_pre_entry_features": source_payload.get("leakage_guards", {}).get(
                "no_future_path_in_pre_entry_features", False
            ),
        },
        "limitations": [
            "Synthetic cycles are offline candidates, not live fills.",
            "Hypotheses are analysis-only and do not modify live strategy behavior.",
            "Multiple testing can overfit a 91-cycle sample.",
            "OHLCV lacks order-book spread, depth, queue-position, and fee-aware liquidity fields.",
            "ALGO/USD has a known local data-quality caveat from the expanded OHLCV rerun.",
        ],
        "next_step_recommendation": (
            "Review whether any validated/provisional/diagnostic enriched pre-entry hypothesis is stable under a larger offline sample; "
            "do not implement live filters, tune exits, run probes, restart, or scale."
        ),
    }


def write_report(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _human_summary(payload: Dict[str, Any]) -> str:
    source = payload["source_synthetic_summary"]
    verdict = payload["implementation_verdict"]
    best = payload.get("best_candidate")
    lines = [
        "=== P2-026B ENRICHED PRE-ENTRY HYPOTHESIS TESTING ===",
        f"bars_scanned={source['bars_scanned']}",
        f"synthetic_cycles_count={source['synthetic_cycles_count']}",
        f"baseline_gross={source['baseline_gross']} win_rate={source['baseline_win_rate']}",
        f"baseline_stop_loss_count={source['baseline_stop_loss_count']} "
        f"baseline_stop_loss_rate={source['baseline_stop_loss_rate']}",
        "",
        f"hypotheses_evaluated={len(payload['hypothesis_results'])}",
        f"validated_candidates={len(payload['validated_candidates'])}",
        f"provisional_candidates={len(payload['provisional_candidates'])}",
        f"diagnostic_only_candidates={len(payload['diagnostic_only_candidates'])}",
        f"likely_overfit_count={payload['likely_overfit_count']}",
        f"rejected_candidates_count={payload['rejected_candidates_count']}",
        "",
        f"best_candidate={best['hypothesis_name'] if best else None}",
        f"best_candidate_status={best['status'] if best else None}",
        "",
        "Top gross-delta rows:",
    ]
    for row in payload["top_candidates_by_gross_delta"][:10]:
        lines.append(
            f"  {row['hypothesis_name']}: status={row['status']} N={row['sample_size_after']} "
            f"removed={row['trades_removed']} stop_removed={row['stop_loss_removed']} "
            f"gross_delta={row['gross_delta']} stop_loss_rate_after={row['stop_loss_rate_after']}"
        )
    lines.extend(
        [
            "",
            f"any_validated_candidate_found={str(verdict['any_validated_candidate_found']).lower()}",
            f"any_provisional_candidate_found={str(verdict['any_provisional_candidate_found']).lower()}",
            "Permission verdict: implementation=false paper=false live=false scaling=false",
            f"Next: {payload['next_step_recommendation']}",
            "=== END REPORT ===",
        ]
    )
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Enriched pre-entry hypothesis testing (offline only, P2-026B)")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--max-bars", type=int, default=50000)
    parser.add_argument("--max-cycles", type=int, default=1000)
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output; no write by default")
    args = parser.parse_args(argv)

    payload = build_enriched_pre_entry_hypothesis_report(
        data_dir=args.data_dir,
        max_bars=args.max_bars,
        max_cycles=args.max_cycles,
        top_n=args.top_n,
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
