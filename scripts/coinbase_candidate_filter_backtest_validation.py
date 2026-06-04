#!/usr/bin/env python3
"""
P2-025T candidate filter backtest validation report.

Offline-only. Evaluates whether candidate filters (from P2-025S) improve
predictive gross edge over the historical window. Labels results as 
exploratory/provisional until supported by sufficient sample size.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coinbase_offline_backtest import (  # noqa: E402
    DEFAULT_MAX_HOLD_MINUTES,
    DEFAULT_STOP_LOSS_PCT,
    DEFAULT_TAKE_PROFIT_PCT,
    _normalize_symbol,
    parse_journal_cycles,
)
from scripts.coinbase_live_exit_policy_parity_report import (  # noqa: E402
    DEFAULT_JOURNAL,
    ModeCycle,
    _fmt_decimal,
    _make_mode_cycle,
    _predictive_live_exit,
    _reason_bucket,
)
from scripts.coinbase_replay_economics_report import (  # noqa: E402
    _compute_coverage_and_covered,
    _load_bars_for_journal,
    _to_decimal,
)

SCHEMA_VERSION = "p2-025t.coinbase_candidate_filter_backtest_validation.v1"
MONEY_QUANT = Decimal("0.00000001")

# Validation Gates
GATE_MIN_SAMPLE_SIZE_PREFERRED = 50
GATE_MIN_SAMPLE_SIZE_MINIMUM = 30
GATE_MIN_GROSS_WIN_RATE = 0.45


def _fmt_money(value: Decimal) -> str:
    return str(value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP))


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _evaluate_scenario(name: str, cycles: List[ModeCycle], filter_fn) -> Dict[str, Any]:
    filtered = [c for c in cycles if filter_fn(c)]
    count = len(filtered)
    
    total_gross = sum((c.mode_gross for c in filtered), Decimal("0"))
    wins = sum(1 for c in filtered if c.mode_gross > 0)
    win_rate = _rate(wins, count)
    avg_gross = total_gross / count if count > 0 else Decimal("0")
    
    # concentration
    sorted_cycles = sorted(filtered, key=lambda c: c.mode_gross)
    worst_10_sum = sum((c.mode_gross for c in sorted_cycles[:10]), Decimal("0"))
    top_10_sum = sum((c.mode_gross for c in sorted_cycles[-10:]), Decimal("0"))
    
    # gates
    sample_size_ok = count >= GATE_MIN_SAMPLE_SIZE_MINIMUM
    gross_positive = total_gross > 0
    avg_gross_positive = avg_gross > 0
    win_rate_ok = win_rate >= GATE_MIN_GROSS_WIN_RATE
    
    failed_gates = []
    if count < GATE_MIN_SAMPLE_SIZE_PREFERRED:
        failed_gates.append(f"sample_size < {GATE_MIN_SAMPLE_SIZE_PREFERRED} (got {count})")
    if not gross_positive:
        failed_gates.append(f"predictive_gross <= 0 (got {_fmt_money(total_gross)})")
    if not avg_gross_positive:
        failed_gates.append(f"avg_gross <= 0 (got {_fmt_money(avg_gross)})")
    if not win_rate_ok:
        failed_gates.append(f"win_rate < {GATE_MIN_GROSS_WIN_RATE} (got {win_rate})")
    
    # concentration check: if top 10 winners are responsible for ALL gains and total is barely positive
    concentration_warning = False
    if gross_positive and top_10_sum >= total_gross and count > 10:
        concentration_warning = True

    validated = len(failed_gates) == 0 and not concentration_warning
    
    status = "validated" if validated else "provisional"
    if count < GATE_MIN_SAMPLE_SIZE_MINIMUM:
        status = "weak/exploratory"
    if count == 0:
        status = "no_data"

    return {
        "scenario_name": name,
        "status": status,
        "sample_size": count,
        "predictive_gross_total": _fmt_money(total_gross),
        "avg_gross": _fmt_money(avg_gross),
        "win_rate": win_rate,
        "concentration_worst_10": _fmt_money(worst_10_sum),
        "concentration_top_10": _fmt_money(top_10_sum),
        "concentration_warning": concentration_warning,
        "candidate_filter_validated": validated,
        "failed_gates": failed_gates,
        "overfit_risk": count < 20
    }


def build_candidate_filter_validation_report(
    *,
    journal_path: Optional[Path] = None,
    ohlcv_fixture: Optional[Path] = None,
    max_cycles: Optional[int] = None,
    max_hold_minutes: int = DEFAULT_MAX_HOLD_MINUTES,
) -> Dict[str, Any]:
    jpath = Path(journal_path) if journal_path else DEFAULT_JOURNAL
    all_cycles = parse_journal_cycles(jpath)
    if max_cycles:
        all_cycles = all_cycles[:max_cycles]

    bars = _load_bars_for_journal(all_cycles, ohlcv_fixture=ohlcv_fixture)
    covered_cycles, _with_c, without_c, coverage_rate, skip_break = _compute_coverage_and_covered(all_cycles, bars)
    predictive_cycles: List[ModeCycle] = []
    
    # Re-read journal for extra metadata (strategy name, etc. - parse_journal_cycles has most but let's be sure)
    for idx, cycle in enumerate(covered_cycles):
        pred_price, pred_time, pred_reason, pred_basis = _predictive_live_exit(
            bars,
            cycle,
            max_hold_minutes=max_hold_minutes,
            take_profit_pct=DEFAULT_TAKE_PROFIT_PCT,
            stop_loss_pct=DEFAULT_STOP_LOSS_PCT,
        )
        if pred_price is None:
            continue
            
        mc = _make_mode_cycle(
            idx,
            cycle,
            mode_exit_reason=pred_reason,
            mode_exit_time=pred_time,
            mode_exit_price=pred_price,
            used_journal_exit_price=False,
            used_journal_exit_time_for_prediction=False,
            used_high_low_for_timeout=False,
            basis=pred_basis,
        )
        predictive_cycles.append(mc)

    # Scenarios
    scenarios = {
        "baseline_all_cycles": lambda c: True,
        "exclude_stop_loss": lambda c: _reason_bucket(c.mode_exit_reason) != "stop_loss",
        "exclude_strategy_mean_reversion": lambda c: c.strategy != "mean_reversion",
        "exclude_symbol_ETH/USD": lambda c: c.symbol != "ETH/USD",
        "exclude_symbol_ADA/USD": lambda c: c.symbol != "ADA/USD",
        "combo_exclude_ETH_and_stop_loss": lambda c: c.symbol != "ETH/USD" and _reason_bucket(c.mode_exit_reason) != "stop_loss",
        "combo_exclude_ETH_and_mean_reversion": lambda c: c.symbol != "ETH/USD" and c.strategy != "mean_reversion",
        "combo_exclude_ETH_and_ADA": lambda c: c.symbol != "ETH/USD" and c.symbol != "ADA/USD",
    }

    results = []
    for name, fn in scenarios.items():
        results.append(_evaluate_scenario(name, predictive_cycles, fn))

    validated_filters = [r["scenario_name"] for r in results if r["candidate_filter_validated"]]
    
    # Data range info
    start_ts = min((c.journal_entry_time for c in predictive_cycles if c.journal_entry_time), default=None)
    end_ts = max((c.mode_exit_time for c in predictive_cycles if c.mode_exit_time), default=None)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "report_class": "candidate_filter_backtest_validation",
        "journal_path": str(jpath),
        "data_window": {
            "start": start_ts.isoformat() if start_ts else None,
            "end": end_ts.isoformat() if end_ts else None,
            "cycle_count": len(predictive_cycles),
            "coverage_rate": coverage_rate,
        },
        "validation_gates": {
            "min_sample_size_preferred": GATE_MIN_SAMPLE_SIZE_PREFERRED,
            "min_sample_size_minimum": GATE_MIN_SAMPLE_SIZE_MINIMUM,
            "min_gross_win_rate": GATE_MIN_GROSS_WIN_RATE,
        },
        "scenarios": results,
        "validated_filters": validated_filters,
        "verdict": {
            "any_filter_validated": len(validated_filters) > 0,
            "implementation_authorized": False,
            "paper_probe_authorized": False,
            "live_probe_authorized": False,
            "scaling_authorized": False,
        },
        "acquisition_plan_for_larger_history": {
            "next_data_needed": "OHLCV data for period BEFORE 2026-05-25 to increase sample size.",
            "safe_command": "python3 scripts/coinbase_public_ohlcv_fetch.py --symbol ETH/USD --start 2026-05-01 --end 2026-05-25 --granularity 5m --fetch --write",
            "note": "Fetcher requires no auth/secrets. Do not fetch without signals to test against."
        },
        "notes": [
            "Validation of candidate filters from P2-025S.",
            "Results with < 30 cycles are labeled weak/exploratory.",
            "Results with < 50 cycles are provisional.",
            "This report DOES NOT authorize live implementation of these filters.",
            "Current evidence is limited to the 50-cycle journal window."
        ]
    }
    return payload


def _human_summary(payload: Dict[str, Any]) -> str:
    lines = [
        "=== CANDIDATE FILTER BACKTEST VALIDATION ===",
        f"window: {payload['data_window']['start']} to {payload['data_window']['end']}",
        f"cycles_analyzed: {payload['data_window']['cycle_count']} coverage: {payload['data_window']['coverage_rate']}",
        "",
        "Scenario Validation Table:",
        f"{'Scenario':<40} | {'Count':<5} | {'Gross':<12} | {'WR':<6} | {'Status':<15}",
        "-" * 85,
    ]
    for s in payload["scenarios"]:
        lines.append(f"{s['scenario_name']:<40} | {s['sample_size']:<5} | {s['predictive_gross_total']:<12} | {s['win_rate']:<6.4} | {s['status']:<15}")
    
    lines.extend([
        "",
        f"validated_filters: {payload['validated_filters']}",
        f"any_filter_validated: {payload['verdict']['any_filter_validated']}",
        "",
        "Acquisition Plan for Larger History:",
        f"  {payload['acquisition_plan_for_larger_history']['next_data_needed']}",
        f"  Command: {payload['acquisition_plan_for_larger_history']['safe_command']}",
        "",
        "Authorization: implementation=false paper=false live=false scaling=false",
        "=== END REPORT ===",
    ])
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Candidate filter backtest validation report")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--journal", type=Path, default=None)
    parser.add_argument("--ohlcv-fixture", type=Path, default=None)
    parser.add_argument("--max-cycles", type=int, default=None)
    parser.add_argument("--max-hold-minutes", type=int, default=DEFAULT_MAX_HOLD_MINUTES)
    args = parser.parse_args(argv)

    payload = build_candidate_filter_validation_report(
        journal_path=args.journal,
        ohlcv_fixture=args.ohlcv_fixture,
        max_cycles=args.max_cycles,
        max_hold_minutes=args.max_hold_minutes,
    )
    if args.json:
        json.dump(payload, sys.stdout, indent=2)
        print()
    else:
        print(_human_summary(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
