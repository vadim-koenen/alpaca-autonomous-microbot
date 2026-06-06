#!/usr/bin/env python3
"""
P2-029 independent holdout validation for the fixed redesigned-entry candidate.

Offline diagnostic only. The candidate excludes entries at UTC hours 06 and 17
without searching for replacement hours or changing live strategy behavior.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
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

SCHEMA_VERSION = "p2-029.redesigned_entry_independent_holdout_validation.v1"
REPORT_CLASS = "redesigned_entry_independent_holdout_validation"
CANDIDATE_NAME = "session_avoid_06_17_utc"
CANDIDATE_FAMILY = "session_time_of_day_entry_gating"
EXCLUDED_UTC_HOURS = (6, 17)
INPUT_FIELDS = ["pre_entry_hour_utc", "entry_time"]
MONEY_QUANT = Decimal("0.00000001")
RATE_QUANT = Decimal("0.000001")
MAX_REMOVAL_RATE = Decimal("0.40")
MIN_RESULT_SAMPLE = 20
MIN_GROUP_SAMPLE = 5
RECENT_WINDOW_DAYS = 30
POST_ENTRY_FIELDS = {
    "exit_reason",
    "exit_price",
    "exit_time",
    "gross_pnl",
    "pnl_usd",
    "hold_duration_minutes",
}


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


def _parse_time(value: Any) -> datetime:
    normalized = str(value or "").replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _entry_sort_key(cycle: Dict[str, Any]) -> Tuple[datetime, str, str]:
    return (
        _parse_time(cycle.get("entry_time")),
        str(cycle.get("symbol", "")),
        str(cycle.get("strategy", "")),
    )


def _sorted_cycles(cycles: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(cycles, key=_entry_sort_key)


def _entry_hour_utc(cycle: Dict[str, Any]) -> int:
    raw = cycle.get("pre_entry_hour_utc")
    try:
        hour = int(raw)
        if 0 <= hour <= 23:
            return hour
    except Exception:
        pass
    return _parse_time(cycle.get("entry_time")).hour


def _cycle_gross(cycle: Dict[str, Any]) -> Decimal:
    return _to_decimal(cycle.get("gross_pnl", cycle.get("pnl_usd", "0")))


def _reason_bucket(cycle: Dict[str, Any]) -> str:
    reason = str(cycle.get("exit_reason", "")).lower()
    if "stop" in reason:
        return "stop_loss"
    if "max hold" in reason or "timeout" in reason:
        return "timeout"
    if "take-profit" in reason or "take profit" in reason:
        return "take_profit"
    return "other"


def _stats(cycles: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    values = [_cycle_gross(cycle) for cycle in cycles]
    total = _sum(values)
    sample_size = len(cycles)
    winners = sum(1 for value in values if value > 0)
    losers = sum(1 for value in values if value < 0)
    timeout_count = sum(1 for cycle in cycles if _reason_bucket(cycle) == "timeout")
    stop_loss_count = sum(1 for cycle in cycles if _reason_bucket(cycle) == "stop_loss")
    median_gross = Decimal(str(median([float(value) for value in values]))) if values else Decimal("0")
    return {
        "sample_size": sample_size,
        "gross_total": _fmt_money(total),
        "avg_gross": _fmt_money(total / sample_size) if sample_size else "0.00000000",
        "median_gross": _fmt_money(median_gross),
        "win_rate": _rate(winners, sample_size),
        "winners": winners,
        "losers": losers,
        "timeout_count": timeout_count,
        "timeout_rate": _rate(timeout_count, sample_size),
        "stop_loss_count": stop_loss_count,
        "stop_loss_rate": _rate(stop_loss_count, sample_size),
    }


def _single_winner_concentration(cycles: Sequence[Dict[str, Any]]) -> bool:
    gains = sorted(_cycle_gross(cycle) for cycle in cycles if _cycle_gross(cycle) > 0)
    if not gains:
        return False
    total = _sum(gains)
    return total > 0 and gains[-1] / total > Decimal("0.50")


def _is_excluded(cycle: Dict[str, Any], excluded_hours: Sequence[int] = EXCLUDED_UTC_HOURS) -> bool:
    return _entry_hour_utc(cycle) in set(excluded_hours)


def evaluate_candidate_result(
    *,
    label: str,
    cycles: Sequence[Dict[str, Any]],
    excluded_hours: Sequence[int] = EXCLUDED_UTC_HOURS,
    min_after: int = MIN_RESULT_SAMPLE,
) -> Dict[str, Any]:
    ordered = _sorted_cycles(cycles)
    removed = [cycle for cycle in ordered if _is_excluded(cycle, excluded_hours)]
    kept = [cycle for cycle in ordered if not _is_excluded(cycle, excluded_hours)]
    before = _stats(ordered)
    after = _stats(kept)
    before_count = len(ordered)
    after_count = len(kept)
    removed_count = len(removed)
    removal_rate = Decimal(removed_count) / Decimal(before_count) if before_count else Decimal("0")
    gross_delta = _to_decimal(after["gross_total"]) - _to_decimal(before["gross_total"])
    timeout_delta = _to_decimal(str(before["timeout_rate"])) - _to_decimal(str(after["timeout_rate"]))
    stop_loss_delta = _to_decimal(str(before["stop_loss_rate"])) - _to_decimal(str(after["stop_loss_rate"]))

    failed: List[str] = []
    if before_count == 0:
        failed.append("empty_sample")
    if removed_count == 0:
        failed.append("candidate_removed_no_trades")
    if after_count < min_after:
        failed.append(f"sample_size_after < {min_after}")
    if removal_rate > MAX_REMOVAL_RATE:
        failed.append("trade_removal_rate > 40%")
    if gross_delta <= 0:
        failed.append("gross_delta <= 0")
    if _to_decimal(after["avg_gross"]) <= 0:
        failed.append("avg_gross_after <= 0")
    if _to_decimal(after["median_gross"]) < 0:
        failed.append("median_gross_after < 0")
    if Decimal(str(after["win_rate"])) < Decimal("0.50"):
        failed.append("win_rate_after < 0.50")
    if timeout_delta < 0:
        failed.append("timeout_rate_worsened")
    if stop_loss_delta <= 0:
        failed.append("stop_loss_rate_not_reduced")
    if _single_winner_concentration(kept):
        failed.append("single_winner_concentration")

    return {
        "label": label,
        "excluded_utc_hours": list(excluded_hours),
        "sample_size_before": before_count,
        "sample_size_after": after_count,
        "trades_removed": removed_count,
        "trade_removal_rate": _fmt_rate(removal_rate),
        "gross_before": before["gross_total"],
        "gross_after": after["gross_total"],
        "gross_delta": _fmt_money(gross_delta),
        "avg_gross_before": before["avg_gross"],
        "avg_gross_after": after["avg_gross"],
        "median_gross_before": before["median_gross"],
        "median_gross_after": after["median_gross"],
        "win_rate_before": before["win_rate"],
        "win_rate_after": after["win_rate"],
        "timeout_count_before": before["timeout_count"],
        "timeout_count_after": after["timeout_count"],
        "timeout_rate_before": before["timeout_rate"],
        "timeout_rate_after": after["timeout_rate"],
        "timeout_rate_reduction": _fmt_rate(timeout_delta),
        "stop_loss_count_before": before["stop_loss_count"],
        "stop_loss_count_after": after["stop_loss_count"],
        "stop_loss_rate_before": before["stop_loss_rate"],
        "stop_loss_rate_after": after["stop_loss_rate"],
        "stop_loss_rate_reduction": _fmt_rate(stop_loss_delta),
        "passes_gate": not failed,
        "failed_gates": failed,
    }


def chronological_split(
    cycles: Sequence[Dict[str, Any]],
    train_fraction: Decimal = Decimal("0.70"),
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
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
    count = min(max(folds, 3), 5, len(ordered))
    base_size, remainder = divmod(len(ordered), count)
    rows: List[List[Dict[str, Any]]] = []
    start = 0
    for idx in range(count):
        size = base_size + (1 if idx < remainder else 0)
        rows.append(ordered[start : start + size])
        start += size
    return rows


def _recent_window(
    cycles: Sequence[Dict[str, Any]],
    days: int = RECENT_WINDOW_DAYS,
) -> Tuple[List[Dict[str, Any]], Optional[str], Optional[str]]:
    ordered = _sorted_cycles(cycles)
    valid_times = [_parse_time(cycle.get("entry_time")) for cycle in ordered]
    valid_times = [value for value in valid_times if value.year > 1]
    if not valid_times:
        return [], None, None
    end = max(valid_times)
    start = end - timedelta(days=max(days - 1, 0))
    selected = [
        cycle
        for cycle in ordered
        if start <= _parse_time(cycle.get("entry_time")) <= end
    ]
    return selected, start.isoformat(), end.isoformat()


def grouped_results(
    *,
    cycles: Sequence[Dict[str, Any]],
    key_fields: Sequence[str],
    key_name: str,
) -> List[Dict[str, Any]]:
    groups: Dict[Tuple[str, ...], List[Dict[str, Any]]] = defaultdict(list)
    for cycle in cycles:
        key = tuple(str(cycle.get(field, "unknown")) for field in key_fields)
        groups[key].append(cycle)
    rows = []
    for key, group_cycles in sorted(groups.items()):
        group_key = "|".join(key)
        row = evaluate_candidate_result(
            label=f"{key_name}={group_key}",
            cycles=group_cycles,
            min_after=MIN_GROUP_SAMPLE,
        )
        row[key_name] = group_key
        rows.append(row)
    return rows


def _positive_effect(row: Dict[str, Any]) -> bool:
    return (
        _to_decimal(row.get("gross_delta")) > 0
        and _to_decimal(row.get("stop_loss_rate_reduction")) >= 0
        and _to_decimal(row.get("timeout_rate_reduction")) >= 0
    )


def _stability_summary(
    *,
    fold_rows: Sequence[Dict[str, Any]],
    symbol_rows: Sequence[Dict[str, Any]],
    strategy_rows: Sequence[Dict[str, Any]],
    pair_rows: Sequence[Dict[str, Any]],
    session_rows: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    def summarize(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        positive = sum(1 for row in rows if _positive_effect(row))
        return {
            "group_count": len(rows),
            "positive_effect_count": positive,
            "positive_effect_rate": _rate(positive, len(rows)),
        }

    return {
        "rolling_folds": summarize(fold_rows),
        "symbols": summarize(symbol_rows),
        "strategies": summarize(strategy_rows),
        "symbol_strategies": summarize(pair_rows),
        "sessions": summarize(session_rows),
    }


def _sensitivity_analysis(cycles: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    scenarios = [
        ("fixed_candidate_hours_06_17", [6, 17], False),
        ("ablation_hour_06_only", [6], True),
        ("ablation_hour_17_only", [17], True),
        ("adjacent_hours_plus_minus_one", [5, 6, 7, 16, 17, 18], True),
        ("p2_028_broad_session_context", list(range(6, 18)), True),
    ]
    rows = []
    for label, hours, diagnostic_only in scenarios:
        row = evaluate_candidate_result(
            label=label,
            cycles=cycles,
            excluded_hours=hours,
        )
        row["diagnostic_only"] = diagnostic_only
        row["candidate_reoptimized"] = False
        row["selected_candidate"] = not diagnostic_only
        rows.append(row)
    return rows


def _holdout_verdict(
    *,
    full_result: Dict[str, Any],
    holdout_result: Dict[str, Any],
    independent_result: Dict[str, Any],
    stability: Dict[str, Any],
) -> Dict[str, Any]:
    full_pass = bool(full_result.get("passes_gate"))
    holdout_pass = bool(holdout_result.get("passes_gate"))
    independent_pass = bool(independent_result.get("passes_gate"))
    fold_rate = _to_decimal(stability["rolling_folds"]["positive_effect_rate"])
    symbol_rate = _to_decimal(stability["symbols"]["positive_effect_rate"])
    strategy_rate = _to_decimal(stability["strategies"]["positive_effect_rate"])
    enough_folds = stability["rolling_folds"]["group_count"] >= 3
    independently_validated = (
        full_pass
        and holdout_pass
        and independent_pass
        and enough_folds
        and fold_rate >= Decimal("0.75")
        and symbol_rate >= Decimal("0.50")
        and strategy_rate >= Decimal("0.50")
    )
    falsified = not full_pass and not holdout_pass and not independent_pass
    provisionally_stable = (
        not independently_validated
        and full_pass
        and (holdout_pass or independent_pass)
        and fold_rate >= Decimal("0.50")
    )
    if independently_validated:
        verdict = "independently_validated"
    elif falsified:
        verdict = "falsified"
    elif provisionally_stable:
        verdict = "provisionally_stable_needs_more_data"
    else:
        verdict = "still_unstable"
    return {
        "verdict": verdict,
        "independently_validated": independently_validated,
        "falsified": falsified,
        "likely_overfit": not independently_validated,
        "implementation_proposal_authorized": False,
        "implementation_authorized": False,
        "paper_probe_authorized": False,
        "live_probe_authorized": False,
        "scaling_authorized": False,
    }


def build_redesigned_entry_independent_holdout_validation(
    *,
    data_dir: Optional[Path] = None,
    max_bars: Optional[int] = 100000,
    max_cycles: Optional[int] = 2000,
    folds: int = 4,
    recent_window_days: int = RECENT_WINDOW_DAYS,
    source_payload: Optional[Dict[str, Any]] = None,
    synthetic_cycles: Optional[List[Dict[str, Any]]] = None,
    generated_at_utc: Optional[str] = None,
) -> Dict[str, Any]:
    if source_payload is None:
        source_payload = build_historical_signal_generator_report(
            data_dir=data_dir or DATA_DIR,
            max_bars=max_bars,
            max_cycles=max_cycles,
        )
    cycles = _sorted_cycles(
        synthetic_cycles if synthetic_cycles is not None else source_payload.get("synthetic_cycles", [])
    )
    _, holdout_cycles = chronological_split(cycles)
    recent_cycles, recent_start, recent_end = _recent_window(cycles, recent_window_days)

    full_result = evaluate_candidate_result(label="full_sample", cycles=cycles)
    holdout_result = evaluate_candidate_result(
        label="chronological_holdout_30pct",
        cycles=holdout_cycles,
    )
    independent_result = evaluate_candidate_result(
        label=f"independent_recent_window_{recent_window_days}d",
        cycles=recent_cycles,
    )
    independent_result["window_start_utc"] = recent_start
    independent_result["window_end_utc"] = recent_end
    independent_result["window_is_pristine_unseen_sample"] = False

    fold_rows = [
        evaluate_candidate_result(
            label=f"rolling_fold_{idx + 1}",
            cycles=fold_cycles,
            min_after=MIN_GROUP_SAMPLE,
        )
        | {"fold_index": idx + 1}
        for idx, fold_cycles in enumerate(rolling_folds(cycles, folds))
    ]
    symbol_rows = grouped_results(cycles=cycles, key_fields=["symbol"], key_name="symbol")
    strategy_rows = grouped_results(cycles=cycles, key_fields=["strategy"], key_name="strategy")
    pair_rows = grouped_results(
        cycles=cycles,
        key_fields=["symbol", "strategy"],
        key_name="symbol_strategy",
    )
    session_rows = grouped_results(
        cycles=cycles,
        key_fields=["pre_entry_session_bucket"],
        key_name="session",
    )
    sensitivity = _sensitivity_analysis(cycles)
    stability = _stability_summary(
        fold_rows=fold_rows,
        symbol_rows=symbol_rows,
        strategy_rows=strategy_rows,
        pair_rows=pair_rows,
        session_rows=session_rows,
    )
    verdict = _holdout_verdict(
        full_result=full_result,
        holdout_result=holdout_result,
        independent_result=independent_result,
        stability=stability,
    )
    baseline = _stats(cycles)
    symbols = sorted({str(cycle.get("symbol", "unknown")) for cycle in cycles})
    strategies = sorted({str(cycle.get("strategy", "unknown")) for cycle in cycles})

    return {
        "schema_version": SCHEMA_VERSION,
        "report_class": REPORT_CLASS,
        "generated_at_utc": generated_at_utc or datetime.now(timezone.utc).isoformat(),
        "candidate": {
            "candidate_name": CANDIDATE_NAME,
            "family": CANDIDATE_FAMILY,
            "rule_description": "Exclude entries whose fixed pre-entry UTC hour is 06 or 17.",
            "input_fields": list(INPUT_FIELDS),
            "excluded_utc_hours": list(EXCLUDED_UTC_HOURS),
            "pre_entry_only": True,
            "leakage_risk": any(field in POST_ENTRY_FIELDS for field in INPUT_FIELDS),
            "threshold_reoptimized": False,
        },
        "prior_result_summary": {
            "p2_028_status": "validation_ready",
            "p2_028_gross_delta_vs_baseline": "0.55992776",
            "p2_028_win_rate": 0.533333,
            "p2_028_sample_size": 90,
            "definition_caveat": (
                "P2-028 excluded broad 06-11 and 12-17 session buckets; "
                "P2-029 follows the approved exact-hour [6, 17] specification."
            ),
        },
        "data_summary": {
            "bars_scanned": source_payload.get("bars_scanned", 0),
            "synthetic_cycles_count": len(cycles),
            "symbols": symbols,
            "strategies": strategies,
            "date_range": source_payload.get("date_range"),
            "data_dir": source_payload.get("data_dir", str(data_dir or DATA_DIR)),
            "data_offline_ohlcv_untracked_expected": True,
        },
        "baseline_performance": baseline,
        "candidate_full_sample_result": full_result,
        "chronological_holdout_result": holdout_result,
        "independent_window_result": independent_result,
        "rolling_fold_results": fold_rows,
        "symbol_stability": symbol_rows,
        "strategy_stability": strategy_rows,
        "symbol_strategy_stability": pair_rows,
        "session_stability": session_rows,
        "sensitivity_analysis": sensitivity,
        "timeout_reduction_diagnostics": {
            "full_sample": {
                "before": full_result["timeout_rate_before"],
                "after": full_result["timeout_rate_after"],
                "reduction": full_result["timeout_rate_reduction"],
            },
            "chronological_holdout": {
                "before": holdout_result["timeout_rate_before"],
                "after": holdout_result["timeout_rate_after"],
                "reduction": holdout_result["timeout_rate_reduction"],
            },
            "independent_window": {
                "before": independent_result["timeout_rate_before"],
                "after": independent_result["timeout_rate_after"],
                "reduction": independent_result["timeout_rate_reduction"],
            },
        },
        "stop_loss_reduction_diagnostics": {
            "full_sample": {
                "before": full_result["stop_loss_rate_before"],
                "after": full_result["stop_loss_rate_after"],
                "reduction": full_result["stop_loss_rate_reduction"],
            },
            "chronological_holdout": {
                "before": holdout_result["stop_loss_rate_before"],
                "after": holdout_result["stop_loss_rate_after"],
                "reduction": holdout_result["stop_loss_rate_reduction"],
            },
            "independent_window": {
                "before": independent_result["stop_loss_rate_before"],
                "after": independent_result["stop_loss_rate_after"],
                "reduction": independent_result["stop_loss_rate_reduction"],
            },
        },
        "overfit_risk_summary": {
            **stability,
            "threshold_reoptimized": False,
            "fixed_excluded_utc_hours": list(EXCLUDED_UTC_HOURS),
            "recent_window_is_pristine_unseen_sample": False,
            "overfit_risk": "high" if verdict["likely_overfit"] else "reduced_but_not_eliminated",
        },
        "holdout_verdict": verdict,
        "limitations": [
            "Synthetic cycles are not live broker fills or broker-backed net profit.",
            "P2-028 selected a related session concept from the same overall data corpus.",
            "The recent window is a fixed date slice, not a newly acquired pristine sample.",
            "P2-028 used broad session buckets while this approved P2-029 contract uses exact hours 06 and 17.",
            "Small symbol, strategy, and fold samples can make stability estimates noisy.",
            "OHLCV does not model order-book depth, queue position, realized fees, or slippage.",
        ],
        "next_step_recommendation": {
            "patch_id": "P2-030",
            "action": (
                "If falsified or unstable, return to offline entry redesign with a corrected candidate definition. "
                "If provisionally stable or independently validated, prepare an offline implementation-proposal review only."
            ),
            "live_implementation_authorized": False,
        },
    }


def write_report(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _human_summary(payload: Dict[str, Any]) -> str:
    full = payload["candidate_full_sample_result"]
    holdout = payload["chronological_holdout_result"]
    independent = payload["independent_window_result"]
    verdict = payload["holdout_verdict"]
    return "\n".join(
        [
            "=== P2-029 REDESIGNED ENTRY INDEPENDENT HOLDOUT VALIDATION ===",
            f"candidate={payload['candidate']['candidate_name']}",
            f"excluded_utc_hours={payload['candidate']['excluded_utc_hours']}",
            f"threshold_reoptimized={str(payload['candidate']['threshold_reoptimized']).lower()}",
            f"bars_scanned={payload['data_summary']['bars_scanned']}",
            f"synthetic_cycles_count={payload['data_summary']['synthetic_cycles_count']}",
            (
                f"full_sample passes={str(full['passes_gate']).lower()} "
                f"gross_delta={full['gross_delta']} win_rate_after={full['win_rate_after']}"
            ),
            (
                f"chronological_holdout passes={str(holdout['passes_gate']).lower()} "
                f"gross_delta={holdout['gross_delta']} win_rate_after={holdout['win_rate_after']}"
            ),
            (
                f"independent_window passes={str(independent['passes_gate']).lower()} "
                f"gross_delta={independent['gross_delta']} win_rate_after={independent['win_rate_after']}"
            ),
            f"verdict={verdict['verdict']}",
            f"independently_validated={str(verdict['independently_validated']).lower()}",
            f"falsified={str(verdict['falsified']).lower()}",
            f"likely_overfit={str(verdict['likely_overfit']).lower()}",
            "authorization: implementation_proposal=false implementation=false paper=false live=false scaling=false",
            f"next_patch={payload['next_step_recommendation']['patch_id']}",
            "=== END REPORT ===",
        ]
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="P2-029 redesigned-entry independent holdout validation")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--max-bars", type=int, default=100000)
    parser.add_argument("--max-cycles", type=int, default=2000)
    parser.add_argument("--folds", type=int, default=4)
    parser.add_argument("--recent-window-days", type=int, default=RECENT_WINDOW_DAYS)
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output; no write by default")
    args = parser.parse_args(argv)

    payload = build_redesigned_entry_independent_holdout_validation(
        data_dir=args.data_dir,
        max_bars=args.max_bars,
        max_cycles=args.max_cycles,
        folds=args.folds,
        recent_window_days=args.recent_window_days,
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
