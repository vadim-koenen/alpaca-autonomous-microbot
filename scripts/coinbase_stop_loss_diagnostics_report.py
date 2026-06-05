#!/usr/bin/env python3
"""
P2-025Z stop-loss diagnostics report.

Offline-only. Explains the P2-025Y stop-loss exclusion diagnostic and tests
whether any implementable pre-entry feature can explain the stop-loss cluster.
No broker clients, no network fetches, no runtime/config mutation, and no live
orders.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from statistics import median
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.coinbase_historical_signal_generator import (  # noqa: E402
    DATA_DIR,
    build_historical_signal_generator_report,
)

SCHEMA_VERSION = "p2-026a.coinbase_stop_loss_diagnostics.v1"
MONEY_QUANT = Decimal("0.00000001")
RATE_QUANT = Decimal("0.000001")
PREFERRED_SAMPLE_SIZE = 50
MINIMUM_SAMPLE_SIZE = 30
MEANINGFUL_STOP_LOSS_REMOVAL_RATE = Decimal("0.50")
MAX_TRADE_REMOVAL_RATE = Decimal("0.50")

BASE_PRE_ENTRY_FEATURES = [
    "symbol",
    "strategy",
    "symbol_strategy",
    "regime",
    "confidence_bucket",
    "spread_bucket",
    "entry_hour_bucket",
    "entry_day_bucket",
    "notional_bucket",
    "entry_basis",
]

ENRICHED_PRE_ENTRY_FEATURES = [
    "pre_entry_return_3_bucket",
    "pre_entry_return_6_bucket",
    "pre_entry_return_12_bucket",
    "pre_entry_volatility_12_bucket",
    "pre_entry_atr_bucket",
    "pre_entry_volume_ratio_12_bucket",
    "pre_entry_liquidity_bucket",
    "pre_entry_hour_utc_bucket",
    "pre_entry_day_of_week_utc",
    "pre_entry_session_bucket",
    "pre_entry_symbol_strategy_key",
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


def _median_decimal(values: List[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    return Decimal(str(median([float(value) for value in values])))


def _reason_bucket(reason: Any) -> str:
    text = str(reason or "").lower()
    if "stop" in text:
        return "stop_loss"
    if "take-profit" in text or "take profit" in text:
        return "take_profit"
    if "timeout" in text or "max hold" in text:
        return "timeout"
    if "end_of_data" in text:
        return "end_of_data"
    return text or "unknown"


def _is_stop_loss(cycle: Dict[str, Any]) -> bool:
    return _reason_bucket(cycle.get("exit_reason")) == "stop_loss"


def _parse_timestamp(value: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


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


def _spread_bucket(value: Any) -> str:
    spread = _to_decimal(value, Decimal("-1"))
    if spread < 0:
        return "unknown"
    if spread == 0:
        return "0"
    if spread <= Decimal("0.05"):
        return "0-0.05%"
    if spread <= Decimal("0.10"):
        return "0.05-0.10%"
    if spread <= Decimal("0.20"):
        return "0.10-0.20%"
    return ">0.20%"


def _notional_bucket(value: Any) -> str:
    notional = _to_decimal(value, Decimal("-1"))
    if notional < 0:
        return "unknown"
    if notional <= Decimal("1"):
        return "<=$1"
    if notional <= Decimal("5"):
        return "$1-$5"
    if notional <= Decimal("10"):
        return "$5-$10"
    return ">$10"


def _signed_rate_bucket(value: Any) -> str:
    rate = _to_decimal(value, Decimal("0"))
    if rate <= Decimal("-0.01"):
        return "<=-1%"
    if rate <= Decimal("-0.005"):
        return "-1%--0.5%"
    if rate < 0:
        return "-0.5%-0"
    if rate == 0:
        return "0"
    if rate < Decimal("0.005"):
        return "0-0.5%"
    if rate < Decimal("0.01"):
        return "0.5%-1%"
    return ">=1%"


def _positive_rate_bucket(value: Any) -> str:
    rate = _to_decimal(value, Decimal("0"))
    if rate == 0:
        return "0"
    if rate < Decimal("0.0025"):
        return "0-0.25%"
    if rate < Decimal("0.005"):
        return "0.25%-0.5%"
    if rate < Decimal("0.01"):
        return "0.5%-1%"
    if rate < Decimal("0.02"):
        return "1%-2%"
    return ">=2%"


def _hour_utc_bucket(value: Any) -> str:
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


def _entry_hour_bucket(cycle: Dict[str, Any]) -> str:
    ts = _parse_timestamp(cycle.get("entry_time"))
    if ts is None:
        return "unknown"
    hour = ts.hour
    if hour < 6:
        return "00-05"
    if hour < 12:
        return "06-11"
    if hour < 18:
        return "12-17"
    return "18-23"


def _entry_day_bucket(cycle: Dict[str, Any]) -> str:
    ts = _parse_timestamp(cycle.get("entry_time"))
    if ts is None:
        return "unknown"
    return ts.strftime("%a")


def _feature_value(cycle: Dict[str, Any], feature: str) -> str:
    if feature == "symbol":
        return str(cycle.get("symbol", "unknown"))
    if feature == "strategy":
        return str(cycle.get("strategy", "unknown"))
    if feature == "symbol_strategy":
        return f"{cycle.get('symbol', 'unknown')}|{cycle.get('strategy', 'unknown')}"
    if feature == "regime":
        return str(cycle.get("regime", "unknown"))
    if feature == "confidence_bucket":
        return _confidence_bucket(cycle.get("confidence"))
    if feature == "spread_bucket":
        return _spread_bucket(cycle.get("entry_spread_pct"))
    if feature == "entry_hour_bucket":
        return _entry_hour_bucket(cycle)
    if feature == "entry_day_bucket":
        return _entry_day_bucket(cycle)
    if feature == "notional_bucket":
        return _notional_bucket(cycle.get("notional"))
    if feature == "entry_basis":
        return str(cycle.get("entry_basis", "unknown"))
    if feature == "exit_reason":
        return _reason_bucket(cycle.get("exit_reason"))
    if feature == "pre_entry_return_3_bucket":
        return _signed_rate_bucket(cycle.get("pre_entry_return_3"))
    if feature == "pre_entry_return_6_bucket":
        return _signed_rate_bucket(cycle.get("pre_entry_return_6"))
    if feature == "pre_entry_return_12_bucket":
        return _signed_rate_bucket(cycle.get("pre_entry_return_12"))
    if feature == "pre_entry_volatility_12_bucket":
        return str(cycle.get("pre_entry_volatility_bucket") or _positive_rate_bucket(cycle.get("pre_entry_volatility_12")))
    if feature == "pre_entry_atr_bucket":
        return str(cycle.get("pre_entry_atr_bucket") or _positive_rate_bucket(cycle.get("pre_entry_atr_14")))
    if feature == "pre_entry_volume_ratio_12_bucket":
        return str(cycle.get("pre_entry_liquidity_bucket") or _positive_rate_bucket(cycle.get("pre_entry_volume_ratio_12")))
    if feature == "pre_entry_hour_utc_bucket":
        return _hour_utc_bucket(cycle.get("pre_entry_hour_utc"))
    return str(cycle.get(feature, "unknown"))


def _gross_stats(cycles: List[Dict[str, Any]]) -> Dict[str, Any]:
    gross_values = [_cycle_gross(cycle) for cycle in cycles]
    gross_total = _sum(gross_values)
    sample_size = len(cycles)
    winners = sum(1 for gross in gross_values if gross > 0)
    losers = sum(1 for gross in gross_values if gross < 0)
    avg = gross_total / sample_size if sample_size else Decimal("0")
    med = _median_decimal(gross_values)
    return {
        "sample_size": sample_size,
        "gross_total": _fmt_money(gross_total),
        "avg_gross": _fmt_money(avg),
        "median_gross": _fmt_money(med),
        "win_rate": _rate(winners, sample_size),
        "winner_count": winners,
        "loser_count": losers,
    }


def _concentration_warning(cycles: List[Dict[str, Any]]) -> bool:
    gross_values = sorted(_cycle_gross(cycle) for cycle in cycles)
    if not gross_values:
        return False
    gains = [value for value in gross_values if value > 0]
    losses = [abs(value) for value in gross_values if value < 0]
    if gains:
        top_winner_share = gross_values[-1] / _sum(gains)
        if top_winner_share > Decimal("0.50"):
            return True
    if gains and losses:
        worst_five = _sum(losses[-5:])
        if worst_five > _sum(gains):
            return True
    return False


def _group_stop_loss(cycles: List[Dict[str, Any]], feature: str) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for cycle in cycles:
        grouped[_feature_value(cycle, feature)].append(cycle)
    result: Dict[str, Dict[str, Any]] = {}
    for key, rows in sorted(grouped.items()):
        stop_rows = [cycle for cycle in rows if _is_stop_loss(cycle)]
        result[key] = {
            "cycles": len(rows),
            "stop_loss_count": len(stop_rows),
            "stop_loss_rate": _rate(len(stop_rows), len(rows)),
            "stop_loss_gross_total": _fmt_money(_sum(_cycle_gross(cycle) for cycle in stop_rows)),
            "total_gross": _fmt_money(_sum(_cycle_gross(cycle) for cycle in rows)),
        }
    return result


def _availability(cycles: List[Dict[str, Any]]) -> Dict[str, Any]:
    candidate_features = [
        "symbol",
        "strategy",
        "regime",
        "confidence",
        "entry_spread_pct",
        "entry_time",
        "notional",
        "entry_basis",
        "source_ohlcv_file",
        "pre_entry_return_1",
        "pre_entry_return_3",
        "pre_entry_return_6",
        "pre_entry_return_12",
        "pre_entry_volatility_6",
        "pre_entry_volatility_12",
        "pre_entry_atr_14",
        "pre_entry_range_pct_1",
        "pre_entry_range_pct_3",
        "pre_entry_volume",
        "pre_entry_volume_sma_12",
        "pre_entry_volume_ratio_12",
        "pre_entry_liquidity_bucket",
        "pre_entry_volatility_bucket",
        "pre_entry_momentum_bucket",
        "pre_entry_atr_bucket",
        "pre_entry_hour_utc",
        "pre_entry_day_of_week_utc",
        "pre_entry_session_bucket",
        "pre_entry_regime",
        "pre_entry_confidence",
        "pre_entry_symbol_strategy_key",
        "order_book_spread_available",
        "bid_ask_depth_available",
        "order_book_features_missing_reason",
    ]
    missing_candidates = [
        "order_book_spread",
        "bid_ask_depth",
        "maker_taker_fee_estimate",
        "order_book_liquidity_bucket",
    ]
    available = []
    for feature in candidate_features:
        if any(cycle.get(feature) not in (None, "") for cycle in cycles):
            available.append(feature)
    return {
        "available_features": available,
        "missing_features": missing_candidates,
        "enough_for_pre_entry_filter_design": {"symbol", "strategy", "entry_time"}.issubset(set(available)),
    }


def _enriched_availability(cycles: List[Dict[str, Any]]) -> Dict[str, Any]:
    availability = _availability(cycles)
    enriched_fields = [
        feature for feature in availability["available_features"]
        if feature.startswith("pre_entry_") or feature in {
            "order_book_spread_available",
            "bid_ask_depth_available",
            "order_book_features_missing_reason",
        }
    ]
    required = {
        "pre_entry_return_1",
        "pre_entry_return_3",
        "pre_entry_return_6",
        "pre_entry_return_12",
        "pre_entry_volatility_6",
        "pre_entry_volatility_12",
        "pre_entry_atr_14",
        "pre_entry_volume_ratio_12",
        "pre_entry_liquidity_bucket",
        "pre_entry_volatility_bucket",
        "pre_entry_momentum_bucket",
        "pre_entry_atr_bucket",
    }
    still_missing = [
        "order_book_spread",
        "bid_ask_depth",
        "maker_taker_fee_estimate",
        "order_book_liquidity_bucket",
    ]
    return {
        "available": enriched_fields,
        "missing": sorted(required - set(enriched_fields)) + still_missing,
        "still_unavailable_from_ohlcv_only": still_missing,
        "order_book_features_missing_reason": "OHLCV-only dataset",
        "enough_for_enriched_pre_entry_diagnostics": required.issubset(set(enriched_fields)),
    }


def _hypothesis(
    *,
    name: str,
    cycles: List[Dict[str, Any]],
    predicate: Callable[[Dict[str, Any]], bool],
    baseline_gross: Decimal,
    feature: str,
    removed_value: str,
    pre_entry_implementable: bool,
    leakage_risk: bool,
) -> Dict[str, Any]:
    stop_loss_total = sum(1 for cycle in cycles if _is_stop_loss(cycle))
    filtered = [cycle for cycle in cycles if predicate(cycle)]
    removed = [cycle for cycle in cycles if not predicate(cycle)]
    stop_loss_removed = sum(1 for cycle in removed if _is_stop_loss(cycle))
    stats = _gross_stats(filtered)
    gross_after = _to_decimal(stats["gross_total"])
    avg_after = _to_decimal(stats["avg_gross"])
    median_after = _to_decimal(stats["median_gross"])
    pct_removed = Decimal(stop_loss_removed) / Decimal(stop_loss_total) if stop_loss_total else Decimal("0")
    sample_size = int(stats["sample_size"])
    removal_rate = Decimal(len(removed)) / Decimal(len(cycles)) if cycles else Decimal("0")
    concentration = _concentration_warning(filtered)
    economically_better = gross_after > baseline_gross and avg_after > 0 and median_after >= 0
    win_rate_ok = Decimal(str(stats["win_rate"])) >= Decimal("0.50")
    data_quality_caveat = "ALGO gap caveat" if "ALGO" in removed_value else None
    implementation_candidate = (
        pre_entry_implementable
        and not leakage_risk
        and sample_size >= MINIMUM_SAMPLE_SIZE
        and pct_removed >= MEANINGFUL_STOP_LOSS_REMOVAL_RATE
        and removal_rate <= MAX_TRADE_REMOVAL_RATE
        and economically_better
        and win_rate_ok
        and not concentration
        and data_quality_caveat is None
    )
    return {
        "hypothesis": name,
        "feature": feature,
        "removed_value": removed_value,
        "sample_size_remaining": sample_size,
        "stop_loss_cycles_removed": stop_loss_removed,
        "percent_stop_loss_removed": _fmt_rate(pct_removed),
        "trade_removal_rate": _fmt_rate(removal_rate),
        "gross_after_filter": stats["gross_total"],
        "avg_gross_after_filter": stats["avg_gross"],
        "median_gross_after_filter": stats["median_gross"],
        "win_rate_after_filter": stats["win_rate"],
        "gross_delta_vs_baseline": _fmt_money(gross_after - baseline_gross),
        "concentration_warning": concentration,
        "overfit_warning": sample_size < PREFERRED_SAMPLE_SIZE or stop_loss_removed < 3,
        "data_quality_caveat": data_quality_caveat,
        "pre_entry_implementable": pre_entry_implementable,
        "leakage_risk": leakage_risk,
        "implementation_candidate": implementation_candidate,
        "implementation_authorized": False,
    }


def _build_hypotheses(
    cycles: List[Dict[str, Any]],
    baseline_gross: Decimal,
    *,
    pre_entry_features: Sequence[str],
    include_outcome_diagnostic: bool = True,
) -> List[Dict[str, Any]]:
    hypotheses: List[Dict[str, Any]] = []
    if include_outcome_diagnostic:
        hypotheses.append(
            _hypothesis(
                name="exclude_stop_loss_post_outcome",
                cycles=cycles,
                predicate=lambda cycle: not _is_stop_loss(cycle),
                baseline_gross=baseline_gross,
                feature="exit_reason",
                removed_value="stop_loss",
                pre_entry_implementable=False,
                leakage_risk=True,
            )
        )
    for feature in pre_entry_features:
        values = sorted({_feature_value(cycle, feature) for cycle in cycles})
        for value in values:
            removed_count = sum(1 for cycle in cycles if _feature_value(cycle, feature) == value)
            if removed_count == 0 or removed_count == len(cycles):
                continue
            hypotheses.append(
                _hypothesis(
                    name=f"avoid_{feature}_{value}",
                    cycles=cycles,
                    predicate=lambda cycle, feature=feature, value=value: _feature_value(cycle, feature) != value,
                    baseline_gross=baseline_gross,
                    feature=feature,
                    removed_value=value,
                    pre_entry_implementable=True,
                    leakage_risk=False,
                )
            )
    return sorted(
        hypotheses,
        key=lambda row: (
            row["implementation_candidate"],
            _to_decimal(row["gross_delta_vs_baseline"]),
            _to_decimal(row["percent_stop_loss_removed"]),
        ),
        reverse=True,
    )


def _source_summary(source_payload: Dict[str, Any]) -> Dict[str, Any]:
    gross_summary = source_payload.get("gross_summary", {})
    return {
        "bars_scanned": source_payload.get("bars_scanned", 0),
        "synthetic_cycles_count": source_payload.get("synthetic_cycles_count", 0),
        "baseline_gross": gross_summary.get("gross_total", "0.00000000"),
        "baseline_win_rate": gross_summary.get("win_rate", 0.0),
        "leakage_guards": source_payload.get("leakage_guards", {}),
    }


def _stop_loss_summary(cycles: List[Dict[str, Any]]) -> Dict[str, Any]:
    stop_loss_cycles = [cycle for cycle in cycles if _is_stop_loss(cycle)]
    non_stop_loss_cycles = [cycle for cycle in cycles if not _is_stop_loss(cycle)]
    stop_loss_gross_values = [_cycle_gross(cycle) for cycle in stop_loss_cycles]
    non_stop_loss_gross_values = [_cycle_gross(cycle) for cycle in non_stop_loss_cycles]
    stop_loss_gross = _sum(stop_loss_gross_values)
    non_stop_loss_gross = _sum(non_stop_loss_gross_values)
    return {
        "stop_loss_count": len(stop_loss_cycles),
        "non_stop_loss_count": len(non_stop_loss_cycles),
        "stop_loss_gross_total": _fmt_money(stop_loss_gross),
        "non_stop_loss_gross_total": _fmt_money(non_stop_loss_gross),
        "stop_loss_avg_gross": _fmt_money(stop_loss_gross / len(stop_loss_cycles)) if stop_loss_cycles else "0.00000000",
        "stop_loss_median_gross": _fmt_money(_median_decimal(stop_loss_gross_values)),
        "stop_loss_symbols": sorted({str(cycle.get("symbol", "unknown")) for cycle in stop_loss_cycles}),
        "stop_loss_strategies": sorted({str(cycle.get("strategy", "unknown")) for cycle in stop_loss_cycles}),
    }


def _diagnostic_answers(payload: Dict[str, Any]) -> Dict[str, Any]:
    stop_summary = payload["stop_loss_summary"]
    hypotheses = payload["pre_entry_hypothesis_results"]
    candidates = [row for row in hypotheses if row["implementation_candidate"]]
    keep_50 = [
        row for row in hypotheses
        if row["pre_entry_implementable"] and not row["leakage_risk"] and row["sample_size_remaining"] >= 50
        and _to_decimal(row["percent_stop_loss_removed"]) >= MEANINGFUL_STOP_LOSS_REMOVAL_RATE
    ]
    keep_30 = [
        row for row in hypotheses
        if row["pre_entry_implementable"] and not row["leakage_risk"] and row["sample_size_remaining"] >= 30
        and _to_decimal(row["percent_stop_loss_removed"]) >= MEANINGFUL_STOP_LOSS_REMOVAL_RATE
    ]
    return {
        "stop_loss_cycle_count": stop_summary["stop_loss_count"],
        "stop_loss_gross_contribution": stop_summary["stop_loss_gross_total"],
        "stop_loss_symbols": stop_summary["stop_loss_symbols"],
        "stop_loss_strategies": stop_summary["stop_loss_strategies"],
        "concentration_interpretation": (
            "Stop-loss cycles are concentrated enough to diagnose, but current pre-entry buckets must be treated as exploratory."
            if stop_summary["stop_loss_count"] else "No stop-loss cycles found."
        ),
        "lower_confidence_than_non_stop_loss": payload["pre_entry_comparison"]["confidence"]["stop_loss_avg"]
        < payload["pre_entry_comparison"]["confidence"]["non_stop_loss_avg"],
        "worse_spread_or_volatility_or_momentum": (
            "not_proven; enriched volatility and momentum buckets are diagnostic only, "
            "and order-book spread/depth remain unavailable in OHLCV"
        ),
        "pre_entry_rule_avoids_most_while_keeping_50_cycles": bool(keep_50),
        "pre_entry_rule_avoids_most_while_keeping_30_cycles": bool(keep_30),
        "likely_driver": (
            "post_entry_path_and_normal_strategy_risk_or_exit_policy; pre-entry evidence is not yet strong enough for implementation"
        ),
        "exclude_stop_loss_implementable_as_is": False,
        "additional_pre_entry_features_needed": payload["pre_entry_feature_availability"]["missing_features"],
        "best_candidate_summary": candidates[0] if candidates else None,
    }


def _avg_feature(cycles: List[Dict[str, Any]], feature: str) -> Decimal:
    values = [_to_decimal(cycle.get(feature), Decimal("-1")) for cycle in cycles]
    values = [value for value in values if value >= 0]
    if not values:
        return Decimal("0")
    return _sum(values) / len(values)


def build_stop_loss_diagnostics_report(
    *,
    data_dir: Optional[Path] = None,
    max_bars: Optional[int] = None,
    max_cycles: Optional[int] = None,
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
    stop_loss_cycles = [cycle for cycle in cycles if _is_stop_loss(cycle)]
    non_stop_loss_cycles = [cycle for cycle in cycles if not _is_stop_loss(cycle)]
    baseline_gross = _sum(_cycle_gross(cycle) for cycle in cycles)
    hypotheses = _build_hypotheses(
        cycles,
        baseline_gross,
        pre_entry_features=BASE_PRE_ENTRY_FEATURES,
        include_outcome_diagnostic=True,
    )
    enriched_hypotheses = _build_hypotheses(
        cycles,
        baseline_gross,
        pre_entry_features=ENRICHED_PRE_ENTRY_FEATURES,
        include_outcome_diagnostic=False,
    )
    pre_entry_results = hypotheses[: max(1, top_n)]
    candidate_rows = [row for row in hypotheses if row["implementation_candidate"]]
    best_candidate = candidate_rows[0] if candidate_rows else None
    enriched_results = enriched_hypotheses[: max(1, top_n)]
    enriched_candidate_rows = [row for row in enriched_hypotheses if row["implementation_candidate"]]
    best_enriched_candidate = enriched_candidate_rows[0] if enriched_candidate_rows else None

    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "report_class": "stop_loss_diagnostics",
        "source_synthetic_summary": _source_summary(source_payload),
        "stop_loss_summary": _stop_loss_summary(cycles),
        "leakage_assessment": {
            "exclude_stop_loss_is_post_outcome": True,
            "direct_live_filter_implementable": False,
            "pre_entry_predictor_required": True,
            "journal_exit_leakage": False,
            "future_path_leakage_for_filter": True,
        },
        "pre_entry_feature_availability": _availability(cycles),
        "enriched_pre_entry_feature_availability": _enriched_availability(cycles),
        "stop_loss_concentration": {
            "by_symbol": _group_stop_loss(cycles, "symbol"),
            "by_strategy": _group_stop_loss(cycles, "strategy"),
            "by_symbol_strategy": _group_stop_loss(cycles, "symbol_strategy"),
            "by_time_bucket": _group_stop_loss(cycles, "entry_hour_bucket"),
            "by_day_bucket": _group_stop_loss(cycles, "entry_day_bucket"),
            "by_confidence_bucket": _group_stop_loss(cycles, "confidence_bucket"),
            "by_spread_bucket": _group_stop_loss(cycles, "spread_bucket"),
            "by_pre_entry_return_3_bucket": _group_stop_loss(cycles, "pre_entry_return_3_bucket"),
            "by_pre_entry_return_6_bucket": _group_stop_loss(cycles, "pre_entry_return_6_bucket"),
            "by_pre_entry_return_12_bucket": _group_stop_loss(cycles, "pre_entry_return_12_bucket"),
            "by_pre_entry_volatility_12_bucket": _group_stop_loss(cycles, "pre_entry_volatility_12_bucket"),
            "by_pre_entry_atr_bucket": _group_stop_loss(cycles, "pre_entry_atr_bucket"),
            "by_pre_entry_volume_ratio_12_bucket": _group_stop_loss(cycles, "pre_entry_volume_ratio_12_bucket"),
            "by_pre_entry_liquidity_bucket": _group_stop_loss(cycles, "pre_entry_liquidity_bucket"),
            "by_pre_entry_hour_utc_bucket": _group_stop_loss(cycles, "pre_entry_hour_utc_bucket"),
            "by_pre_entry_day_of_week_utc": _group_stop_loss(cycles, "pre_entry_day_of_week_utc"),
            "by_pre_entry_session_bucket": _group_stop_loss(cycles, "pre_entry_session_bucket"),
            "by_pre_entry_symbol_strategy_key": _group_stop_loss(cycles, "pre_entry_symbol_strategy_key"),
            "by_regime": _group_stop_loss(cycles, "regime"),
            "by_notional_bucket": _group_stop_loss(cycles, "notional_bucket"),
            "by_entry_basis": _group_stop_loss(cycles, "entry_basis"),
        },
        "pre_entry_comparison": {
            "confidence": {
                "stop_loss_avg": float(_avg_feature(stop_loss_cycles, "confidence")),
                "non_stop_loss_avg": float(_avg_feature(non_stop_loss_cycles, "confidence")),
            },
            "entry_spread_pct": {
                "stop_loss_avg": float(_avg_feature(stop_loss_cycles, "entry_spread_pct")),
                "non_stop_loss_avg": float(_avg_feature(non_stop_loss_cycles, "entry_spread_pct")),
            },
            "volatility": {
                "available": any(cycle.get("pre_entry_volatility_12") not in (None, "") for cycle in cycles),
                "stop_loss_avg": float(_avg_feature(stop_loss_cycles, "pre_entry_volatility_12")),
                "non_stop_loss_avg": float(_avg_feature(non_stop_loss_cycles, "pre_entry_volatility_12")),
            },
            "recent_momentum": {
                "available": any(cycle.get("pre_entry_return_12") not in (None, "") for cycle in cycles),
                "stop_loss_avg": float(_avg_feature(stop_loss_cycles, "pre_entry_return_12")),
                "non_stop_loss_avg": float(_avg_feature(non_stop_loss_cycles, "pre_entry_return_12")),
            },
            "atr": {
                "available": any(cycle.get("pre_entry_atr_14") not in (None, "") for cycle in cycles),
                "stop_loss_avg": float(_avg_feature(stop_loss_cycles, "pre_entry_atr_14")),
                "non_stop_loss_avg": float(_avg_feature(non_stop_loss_cycles, "pre_entry_atr_14")),
            },
            "volume_ratio": {
                "available": any(cycle.get("pre_entry_volume_ratio_12") not in (None, "") for cycle in cycles),
                "stop_loss_avg": float(_avg_feature(stop_loss_cycles, "pre_entry_volume_ratio_12")),
                "non_stop_loss_avg": float(_avg_feature(non_stop_loss_cycles, "pre_entry_volume_ratio_12")),
            },
        },
        "pre_entry_hypothesis_results": pre_entry_results,
        "enriched_pre_entry_hypothesis_results": enriched_results,
        "best_enriched_pre_entry_candidate": best_enriched_candidate,
        "any_enriched_pre_entry_candidate_found": bool(best_enriched_candidate),
        "post_entry_outcome_diagnostics": {
            "non_implementable_fields": [
                "exit_reason",
                "exit_price",
                "hold_duration_minutes",
                "exit_basis",
                "post_entry_path_behavior",
            ],
            "exclude_stop_loss_gross_after_filter": next(
                (row["gross_after_filter"] for row in hypotheses if row["hypothesis"] == "exclude_stop_loss_post_outcome"),
                "0.00000000",
            ),
            "interpretation": "Useful for explaining outcome clusters, not directly usable as a live pre-entry rule.",
        },
        "implementability_verdict": {
            "stop_loss_exclusion_implementable_as_is": False,
            "any_pre_entry_candidate_found": bool(best_candidate),
            "best_pre_entry_candidate": best_candidate,
            "candidate_requires_more_data": True,
            "implementation_authorized": False,
            "paper_probe_authorized": False,
            "live_probe_authorized": False,
            "scaling_authorized": False,
        },
        "limitations": [
            "Synthetic cycles are offline candidates, not live fills.",
            "Stop-loss is an exit outcome and cannot be used directly as a live pre-entry filter.",
            "OHLCV-derived pre-entry features still lack order-book spread, depth, queue-position, and fee-aware liquidity fields.",
            "Pre-entry bucket hypotheses are exploratory and do not change live strategy behavior.",
        ],
        "next_step_recommendation": (
            "Use enriched offline pre-entry fields for P2-026B hypothesis testing before any implementation proposal."
        ),
    }
    payload["diagnostic_answers"] = _diagnostic_answers(payload)
    return payload


def write_report(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _human_summary(payload: Dict[str, Any]) -> str:
    source = payload["source_synthetic_summary"]
    stop_summary = payload["stop_loss_summary"]
    verdict = payload["implementability_verdict"]
    best = verdict.get("best_pre_entry_candidate")
    best_enriched = payload.get("best_enriched_pre_entry_candidate")
    lines = [
        "=== P2-026A STOP-LOSS DIAGNOSTICS WITH ENRICHED PRE-ENTRY FEATURES ===",
        f"bars_scanned={source['bars_scanned']}",
        f"synthetic_cycles_count={source['synthetic_cycles_count']}",
        f"baseline_gross={source['baseline_gross']} win_rate={source['baseline_win_rate']}",
        "",
        "Stop-loss summary:",
        f"  stop_loss_count={stop_summary['stop_loss_count']}",
        f"  non_stop_loss_count={stop_summary['non_stop_loss_count']}",
        f"  stop_loss_gross_total={stop_summary['stop_loss_gross_total']}",
        f"  non_stop_loss_gross_total={stop_summary['non_stop_loss_gross_total']}",
        f"  stop_loss_symbols={stop_summary['stop_loss_symbols']}",
        f"  stop_loss_strategies={stop_summary['stop_loss_strategies']}",
        "",
        "Leakage assessment:",
        "  exclude_stop_loss_is_post_outcome=true",
        "  direct_live_filter_implementable=false",
        "  pre_entry_predictor_required=true",
        "",
        "Top hypotheses:",
    ]
    for row in payload["pre_entry_hypothesis_results"][:10]:
        lines.append(
            f"  {row['hypothesis']}: N={row['sample_size_remaining']} "
            f"removed_stop={row['stop_loss_cycles_removed']} gross={row['gross_after_filter']} "
            f"delta={row['gross_delta_vs_baseline']} leakage={str(row['leakage_risk']).lower()} "
            f"candidate={str(row['implementation_candidate']).lower()}"
        )
    lines.extend(
        [
            "",
            f"any_pre_entry_candidate_found={str(verdict['any_pre_entry_candidate_found']).lower()}",
            f"best_pre_entry_candidate={best['hypothesis'] if best else None}",
            f"any_enriched_pre_entry_candidate_found={str(payload.get('any_enriched_pre_entry_candidate_found', False)).lower()}",
            f"best_enriched_pre_entry_candidate={best_enriched['hypothesis'] if best_enriched else None}",
            "Permission verdict: implementation=false paper=false live=false scaling=false",
            f"Next: {payload['next_step_recommendation']}",
            "=== END REPORT ===",
        ]
    )
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Stop-loss diagnostics report (offline only, P2-025Z)")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--max-bars", type=int, default=50000)
    parser.add_argument("--max-cycles", type=int, default=1000)
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON report output; no write by default")
    args = parser.parse_args(argv)

    payload = build_stop_loss_diagnostics_report(
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
