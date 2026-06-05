#!/usr/bin/env python3
"""
P2-025X synthetic-cycle filter validation report.

Offline-only. Generates or consumes synthetic cycles from P2-025W and evaluates
candidate selectivity filters without modifying live strategy, config, runtime,
or broker state.
"""

from __future__ import annotations

import argparse
import json
import sys
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

SCHEMA_VERSION = "p2-025x.coinbase_synthetic_cycle_filter_validation.v1"
MONEY_QUANT = Decimal("0.00000001")
GATE_MIN_SAMPLE_SIZE_PREFERRED = 50
GATE_MIN_SAMPLE_SIZE_MINIMUM = 30
GATE_MIN_WIN_RATE = 0.45
TOP_WINNER_CONCENTRATION_LIMIT = Decimal("0.50")
WORST_5_LOSS_TO_GAIN_LIMIT = Decimal("1.00")


def _to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return default


def _fmt_money(value: Decimal) -> str:
    return str(value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP))


def _fmt_ratio(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _sample_size_status(sample_size: int) -> str:
    if sample_size < GATE_MIN_SAMPLE_SIZE_MINIMUM:
        return "weak"
    if sample_size < GATE_MIN_SAMPLE_SIZE_PREFERRED:
        return "provisional"
    return "preferred"


def _cycle_gross(cycle: Dict[str, Any]) -> Decimal:
    return _to_decimal(cycle.get("gross_pnl", cycle.get("pnl_usd", "0")))


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


def _median_decimal(values: List[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    return Decimal(str(median([float(v) for v in values])))


def _sum(values: Iterable[Decimal]) -> Decimal:
    total = Decimal("0")
    for value in values:
        total += value
    return total


def _concentration(cycles: List[Dict[str, Any]]) -> Dict[str, Any]:
    gross_values = sorted((_cycle_gross(cycle) for cycle in cycles))
    if not gross_values:
        return {
            "worst_cycle_gross": "0.00000000",
            "best_cycle_gross": "0.00000000",
            "worst_3_concentration": 0.0,
            "worst_5_concentration": 0.0,
            "top_winner_concentration": 0.0,
            "worst_3_gross": "0.00000000",
            "worst_5_gross": "0.00000000",
            "top_winner_gross": "0.00000000",
        }
    losses_abs = [_to_decimal(abs(value)) for value in gross_values if value < 0]
    gains = [value for value in gross_values if value > 0]
    total_loss_abs = _sum(losses_abs)
    total_gain = _sum(gains)
    worst_3 = _sum(gross_values[:3])
    worst_5 = _sum(gross_values[:5])
    top_winner = gross_values[-1]
    worst_3_abs = abs(worst_3)
    worst_5_abs = abs(worst_5)
    return {
        "worst_cycle_gross": _fmt_money(gross_values[0]),
        "best_cycle_gross": _fmt_money(gross_values[-1]),
        "worst_3_concentration": _fmt_ratio(worst_3_abs / total_loss_abs) if total_loss_abs > 0 else 0.0,
        "worst_5_concentration": _fmt_ratio(worst_5_abs / total_loss_abs) if total_loss_abs > 0 else 0.0,
        "top_winner_concentration": _fmt_ratio(top_winner / total_gain) if total_gain > 0 and top_winner > 0 else 0.0,
        "worst_3_gross": _fmt_money(worst_3),
        "worst_5_gross": _fmt_money(worst_5),
        "top_winner_gross": _fmt_money(top_winner),
    }


def _all_leakage_guards_ok(cycles: List[Dict[str, Any]]) -> bool:
    for cycle in cycles:
        guard = cycle.get("leakage_guard") or {}
        if guard.get("no_future_bars_for_signal") is not True:
            return False
        if guard.get("exit_after_entry_only") is not True:
            return False
        if guard.get("no_journal_exit_leakage") is not True:
            return False
    return True


def _evaluate_scenario(
    *,
    scenario_name: str,
    cycles: List[Dict[str, Any]],
    filter_fn: Callable[[Dict[str, Any]], bool],
    baseline_gross: Decimal,
    exploratory: bool = False,
) -> Dict[str, Any]:
    filtered = [cycle for cycle in cycles if filter_fn(cycle)]
    gross_values = [_cycle_gross(cycle) for cycle in filtered]
    sample_size = len(filtered)
    gross_total = _sum(gross_values)
    avg_gross = gross_total / sample_size if sample_size else Decimal("0")
    median_gross = _median_decimal(gross_values)
    winners = sum(1 for gross in gross_values if gross > 0)
    losers = sum(1 for gross in gross_values if gross < 0)
    win_rate = _rate(winners, sample_size)
    concentration = _concentration(filtered)
    sample_status = _sample_size_status(sample_size)
    leakage_ok = _all_leakage_guards_ok(filtered)

    top_winner_concentration = Decimal(str(concentration["top_winner_concentration"]))
    worst_5_concentration = Decimal(str(concentration["worst_5_concentration"]))
    total_gain = _sum(gross for gross in gross_values if gross > 0)
    concentration_warning = False
    if gross_total > 0 and top_winner_concentration > TOP_WINNER_CONCENTRATION_LIMIT:
        concentration_warning = True
    if gross_total > 0 and total_gain > 0:
        worst_5_loss_abs = abs(_to_decimal(concentration["worst_5_gross"]))
        if worst_5_loss_abs > (total_gain * WORST_5_LOSS_TO_GAIN_LIMIT):
            concentration_warning = True
    if sample_size > 0 and sample_size < 10 and worst_5_concentration >= Decimal("0.80"):
        concentration_warning = True

    failed_gates: List[str] = []
    if sample_size < GATE_MIN_SAMPLE_SIZE_PREFERRED:
        failed_gates.append(f"sample_size < {GATE_MIN_SAMPLE_SIZE_PREFERRED} preferred (got {sample_size})")
    if sample_size < GATE_MIN_SAMPLE_SIZE_MINIMUM:
        failed_gates.append(f"sample_size < {GATE_MIN_SAMPLE_SIZE_MINIMUM} minimum (got {sample_size})")
    if gross_total <= 0:
        failed_gates.append(f"synthetic_gross_total <= 0 (got {_fmt_money(gross_total)})")
    if avg_gross <= 0:
        failed_gates.append(f"avg_gross <= 0 (got {_fmt_money(avg_gross)})")
    if median_gross < 0:
        failed_gates.append(f"median_gross < 0 (got {_fmt_money(median_gross)})")
    if win_rate < GATE_MIN_WIN_RATE:
        failed_gates.append(f"win_rate < {GATE_MIN_WIN_RATE} (got {win_rate})")
    if concentration_warning:
        failed_gates.append("concentration warning active")
    if not leakage_ok:
        failed_gates.append("leakage guard failed")

    economic_gates_pass = gross_total > 0 and avg_gross > 0 and median_gross >= 0 and win_rate >= GATE_MIN_WIN_RATE
    candidate_filter_validated = (
        sample_size >= GATE_MIN_SAMPLE_SIZE_PREFERRED
        and economic_gates_pass
        and not concentration_warning
        and leakage_ok
    )
    provisional_positive = (
        not candidate_filter_validated
        and GATE_MIN_SAMPLE_SIZE_MINIMUM <= sample_size < GATE_MIN_SAMPLE_SIZE_PREFERRED
        and economic_gates_pass
        and not concentration_warning
        and leakage_ok
    )

    if candidate_filter_validated:
        validation_status = "validated"
    elif provisional_positive:
        validation_status = "provisional_positive"
    else:
        validation_status = "rejected"
    if sample_size == 0:
        validation_status = "no_data"

    return {
        "scenario": scenario_name,
        "sample_size": sample_size,
        "synthetic_gross_total": _fmt_money(gross_total),
        "avg_gross": _fmt_money(avg_gross),
        "median_gross": _fmt_money(median_gross),
        "win_rate": win_rate,
        "winner_count": winners,
        "loser_count": losers,
        "worst_cycle_gross": concentration["worst_cycle_gross"],
        "best_cycle_gross": concentration["best_cycle_gross"],
        "worst_3_concentration": concentration["worst_3_concentration"],
        "worst_5_concentration": concentration["worst_5_concentration"],
        "top_winner_concentration": concentration["top_winner_concentration"],
        "worst_3_gross": concentration["worst_3_gross"],
        "worst_5_gross": concentration["worst_5_gross"],
        "top_winner_gross": concentration["top_winner_gross"],
        "gross_delta_vs_baseline": _fmt_money(gross_total - baseline_gross),
        "sample_size_status": sample_status,
        "exploratory": exploratory,
        "overfit_warning": exploratory or sample_size < GATE_MIN_SAMPLE_SIZE_PREFERRED,
        "concentration_warning": concentration_warning,
        "candidate_filter_validated": candidate_filter_validated,
        "provisional_positive": provisional_positive,
        "validation_status": validation_status,
        "failed_gates": failed_gates,
    }


def _base_scenarios(cycles: List[Dict[str, Any]]) -> List[Tuple[str, Callable[[Dict[str, Any]], bool], bool]]:
    scenarios: List[Tuple[str, Callable[[Dict[str, Any]], bool], bool]] = [
        ("baseline_all_synthetic_cycles", lambda c: True, False),
        ("exclude_stop_loss", lambda c: _reason_bucket(c.get("exit_reason")) != "stop_loss", False),
        ("exclude_strategy_mean_reversion", lambda c: c.get("strategy") != "mean_reversion", False),
        ("exclude_symbol_ETH/USD", lambda c: c.get("symbol") != "ETH/USD", False),
        ("exclude_symbol_ADA/USD", lambda c: c.get("symbol") != "ADA/USD", False),
        ("exclude_symbol_ALGO/USD", lambda c: c.get("symbol") != "ALGO/USD", False),
        ("exclude_symbol_BTC/USD", lambda c: c.get("symbol") != "BTC/USD", False),
        ("exclude_symbol_SOL/USD", lambda c: c.get("symbol") != "SOL/USD", False),
    ]
    for symbol in sorted({str(c.get("symbol", "unknown")) for c in cycles}):
        name = f"dynamic_exclude_symbol_{symbol}"
        if name.replace("dynamic_", "") not in {s[0] for s in scenarios}:
            scenarios.append((name, lambda c, symbol=symbol: c.get("symbol") != symbol, False))
    for strategy in sorted({str(c.get("strategy", "unknown")) for c in cycles}):
        scenarios.append((f"dynamic_exclude_strategy_{strategy}", lambda c, strategy=strategy: c.get("strategy") != strategy, False))
    for bucket in sorted({_reason_bucket(c.get("exit_reason")) for c in cycles}):
        scenarios.append((f"dynamic_exclude_exit_reason_{bucket}", lambda c, bucket=bucket: _reason_bucket(c.get("exit_reason")) != bucket, False))
    return scenarios


def _combination_scenarios(
    cycles: List[Dict[str, Any]],
    base_results: List[Dict[str, Any]],
) -> List[Tuple[str, Callable[[Dict[str, Any]], bool], bool]]:
    combos: List[Tuple[str, Callable[[Dict[str, Any]], bool], bool]] = [
        ("exclude_ALGO_and_ETH", lambda c: c.get("symbol") not in {"ALGO/USD", "ETH/USD"}, True),
        (
            "exclude_ALGO_and_stop_loss",
            lambda c: c.get("symbol") != "ALGO/USD" and _reason_bucket(c.get("exit_reason")) != "stop_loss",
            True,
        ),
        (
            "exclude_ALGO_and_mean_reversion",
            lambda c: c.get("symbol") != "ALGO/USD" and c.get("strategy") != "mean_reversion",
            True,
        ),
    ]

    symbol_results = [r for r in base_results if r["scenario"].startswith("dynamic_exclude_symbol_")]
    strategy_results = [r for r in base_results if r["scenario"].startswith("dynamic_exclude_strategy_")]
    if symbol_results and strategy_results:
        best_symbol = max(symbol_results, key=lambda r: _to_decimal(r["gross_delta_vs_baseline"]))
        best_strategy = max(strategy_results, key=lambda r: _to_decimal(r["gross_delta_vs_baseline"]))
        symbol = best_symbol["scenario"].replace("dynamic_exclude_symbol_", "")
        strategy = best_strategy["scenario"].replace("dynamic_exclude_strategy_", "")
        combos.append(
            (
                f"combo_best_symbol_exclusion_{symbol}_and_best_strategy_exclusion_{strategy}",
                lambda c, symbol=symbol, strategy=strategy: c.get("symbol") != symbol and c.get("strategy") != strategy,
                True,
            )
        )

    meaningful: List[Tuple[str, Callable[[Dict[str, Any]], bool], bool]] = []
    for name, fn, exploratory in combos:
        if sum(1 for cycle in cycles if fn(cycle)) >= GATE_MIN_SAMPLE_SIZE_MINIMUM:
            meaningful.append((name, fn, exploratory))
    return meaningful


def _summarize_generator(source_payload: Dict[str, Any]) -> Dict[str, Any]:
    gross_summary = source_payload.get("gross_summary", {})
    return {
        "bars_scanned": source_payload.get("bars_scanned", 0),
        "synthetic_cycles_count": source_payload.get("synthetic_cycles_count", 0),
        "symbols_scanned": source_payload.get("symbols_scanned", []),
        "gross_total": gross_summary.get("gross_total", "0.00000000"),
        "win_rate": gross_summary.get("win_rate", 0.0),
    }


def _leakage_summary(cycles: List[Dict[str, Any]], source_payload: Dict[str, Any]) -> Dict[str, Any]:
    source_guards = source_payload.get("leakage_guards", {})
    no_future = source_guards.get("no_future_bars_for_signal")
    exit_after = source_guards.get("exit_after_entry_only")
    no_journal = source_guards.get("no_journal_exit_leakage")
    if no_future is None:
        no_future = all((c.get("leakage_guard") or {}).get("no_future_bars_for_signal") is True for c in cycles)
    if exit_after is None:
        exit_after = all((c.get("leakage_guard") or {}).get("exit_after_entry_only") is True for c in cycles)
    if no_journal is None:
        no_journal = all((c.get("leakage_guard") or {}).get("no_journal_exit_leakage") is True for c in cycles)
    return {
        "no_future_bars_for_signal": bool(no_future),
        "exit_after_entry_only": bool(exit_after),
        "no_journal_exit_leakage": bool(no_journal),
    }


def build_synthetic_cycle_filter_validation_report(
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
    source_summary = _summarize_generator(source_payload)

    baseline_gross = _sum(_cycle_gross(cycle) for cycle in cycles)
    base_results = [
        _evaluate_scenario(
            scenario_name=name,
            cycles=cycles,
            filter_fn=fn,
            baseline_gross=baseline_gross,
            exploratory=exploratory,
        )
        for name, fn, exploratory in _base_scenarios(cycles)
    ]
    combo_results = [
        _evaluate_scenario(
            scenario_name=name,
            cycles=cycles,
            filter_fn=fn,
            baseline_gross=baseline_gross,
            exploratory=exploratory,
        )
        for name, fn, exploratory in _combination_scenarios(cycles, base_results)
    ]
    scenario_results = base_results + combo_results
    baseline_summary = next((r for r in scenario_results if r["scenario"] == "baseline_all_synthetic_cycles"), None)
    best_scenarios = sorted(
        scenario_results,
        key=lambda r: _to_decimal(r["gross_delta_vs_baseline"]),
        reverse=True,
    )[: max(1, top_n)]
    validated_filters = [r["scenario"] for r in scenario_results if r["candidate_filter_validated"]]
    provisional_positive_filters = [r["scenario"] for r in scenario_results if r["provisional_positive"]]
    rejected_filters = [r["scenario"] for r in scenario_results if r["validation_status"] == "rejected"]
    leakage_guard_summary = _leakage_summary(cycles, source_payload)

    any_validated = bool(validated_filters)
    any_provisional = bool(provisional_positive_filters)
    if any_validated:
        next_action = "Review validated filters offline before any separate implementation proposal."
    elif any_provisional:
        next_action = "Increase sample size before considering any implementation proposal for provisional filters."
    else:
        next_action = "Expand synthetic sample size and continue offline-only filter research; do not implement filters yet."

    payload = {
        "schema_version": SCHEMA_VERSION,
        "report_class": "synthetic_cycle_filter_validation",
        "source_generator_summary": source_summary,
        "validation_gates": {
            "min_sample_size_preferred": GATE_MIN_SAMPLE_SIZE_PREFERRED,
            "min_sample_size_minimum": GATE_MIN_SAMPLE_SIZE_MINIMUM,
            "min_win_rate": GATE_MIN_WIN_RATE,
            "top_winner_concentration_limit": float(TOP_WINNER_CONCENTRATION_LIMIT),
            "worst_5_loss_to_gain_limit": float(WORST_5_LOSS_TO_GAIN_LIMIT),
        },
        "baseline_summary": baseline_summary,
        "scenario_results": scenario_results,
        "best_scenarios_by_gross_delta": best_scenarios,
        "validated_filters": validated_filters,
        "provisional_positive_filters": provisional_positive_filters,
        "rejected_filters": rejected_filters,
        "sample_size_limitations": {
            "current_synthetic_cycle_count": len(cycles),
            "sample_size_status": _sample_size_status(len(cycles)),
            "fully_validated_requires_at_least": GATE_MIN_SAMPLE_SIZE_PREFERRED,
            "provisional_positive_requires_at_least": GATE_MIN_SAMPLE_SIZE_MINIMUM,
            "note": "Scenarios below 50 cycles cannot be fully validated.",
        },
        "leakage_guard_summary": leakage_guard_summary,
        "limitations": [
            "Synthetic cycles are offline candidates, not live broker results.",
            "Current generated sample is small and gross-negative at baseline.",
            "Scenario filters are counterfactual diagnostics, not live strategy code.",
            "Exploratory combinations are especially overfit-prone.",
            "No paper or live probe is authorized by this report.",
        ],
        "verdict": {
            "any_filter_validated": any_validated,
            "any_filter_provisionally_positive": any_provisional,
            "implementation_authorized": False,
            "paper_probe_authorized": False,
            "live_probe_authorized": False,
            "scaling_authorized": False,
        },
        "next_step_recommendation": next_action,
    }
    return payload


def write_report(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _human_summary(payload: Dict[str, Any]) -> str:
    source = payload["source_generator_summary"]
    baseline = payload["baseline_summary"] or {}
    lines = [
        "=== P2-025X SYNTHETIC CYCLE FILTER VALIDATION ===",
        f"symbols_scanned={source['symbols_scanned']}",
        f"bars_scanned={source['bars_scanned']}",
        f"synthetic_cycles_count={source['synthetic_cycles_count']}",
        f"baseline_gross={baseline.get('synthetic_gross_total')} win_rate={baseline.get('win_rate')}",
        "",
        "Scenario table:",
        f"{'Scenario':<70} | {'N':>3} | {'Gross':>12} | {'WR':>7} | {'Status':<22} | {'Validated':<9}",
        "-" * 136,
    ]
    for scenario in payload["scenario_results"]:
        lines.append(
            f"{scenario['scenario']:<70} | "
            f"{scenario['sample_size']:>3} | "
            f"{scenario['synthetic_gross_total']:>12} | "
            f"{scenario['win_rate']:>7.4f} | "
            f"{scenario['validation_status']:<22} | "
            f"{str(scenario['candidate_filter_validated']).lower():<9}"
        )
    lines.extend(
        [
            "",
            f"validated_filters={payload['validated_filters']}",
            f"provisional_positive_filters={payload['provisional_positive_filters']}",
            f"rejected_filters={payload['rejected_filters']}",
            f"leakage_guard_summary={payload['leakage_guard_summary']}",
            "Permission verdict: implementation=false paper=false live=false scaling=false",
            f"Next: {payload['next_step_recommendation']}",
            "=== END REPORT ===",
        ]
    )
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Synthetic-cycle filter validation (offline only, P2-025X)")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--max-bars", type=int, default=10000)
    parser.add_argument("--max-cycles", type=int, default=500)
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON report output; no write by default")
    args = parser.parse_args(argv)

    payload = build_synthetic_cycle_filter_validation_report(
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
