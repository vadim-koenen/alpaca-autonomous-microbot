#!/usr/bin/env python3
"""
P2-025R maker/post-only feasibility report.

Offline-only model. Uses predictive live-exit-policy replay as the basis for
fee-scenario, non-fill, and adverse-selection diagnostics. It does not
implement maker/post-only execution and does not authorize paper/live probes.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
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
    PREDICTIVE_GATES,
    ModeCycle,
    _fmt_decimal,
    _make_mode_cycle,
    _predictive_live_exit,
    build_live_exit_policy_parity_report,
)
from scripts.coinbase_replay_economics_report import (  # noqa: E402
    MAKER_ENTRY,
    MAKER_EXIT,
    TAKER_ENTRY,
    TAKER_EXIT,
    _compute_coverage_and_covered,
    _load_bars_for_journal,
    _to_decimal,
)

SCHEMA_VERSION = "p2-025r.coinbase_maker_post_only_feasibility.v1"

FEE_SCENARIOS = {
    "journal_recorded_fees": (None, None),
    "taker/taker": (TAKER_ENTRY, TAKER_EXIT),
    "maker/maker": (MAKER_ENTRY, MAKER_EXIT),
    "maker_entry_taker_exit": (MAKER_ENTRY, TAKER_EXIT),
    "taker_entry_maker_exit": (TAKER_ENTRY, MAKER_EXIT),
    "zero_fee_theoretical": (Decimal("0"), Decimal("0")),
}

HAIRCUT_RATES = [Decimal("0"), Decimal("0.10"), Decimal("0.20"), Decimal("0.30"), Decimal("0.50")]
NON_FILL_RATES = [Decimal("0"), Decimal("0.10"), Decimal("0.30"), Decimal("0.50")]
NOTIONAL_TARGETS = [Decimal("0.50"), Decimal("1"), Decimal("5"), Decimal("10")]
MONEY_QUANT = Decimal("0.00000001")
RATE_QUANT = Decimal("0.000001")


def _fmt_money(value: Decimal) -> str:
    return str(value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP))


def _fmt_rate(value: Decimal) -> str:
    return str(value.quantize(RATE_QUANT, rounding=ROUND_HALF_UP))


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _compute_fees_and_net(
    gross: Decimal,
    notional: Decimal,
    entry_rate: Decimal,
    exit_rate: Decimal,
) -> Tuple[Decimal, Decimal]:
    exit_notional = notional + gross
    fees = (notional * entry_rate) + (exit_notional * exit_rate)
    return fees, gross - fees


def _apply_adverse_selection_haircut(gross: Decimal, haircut_rate: Decimal) -> Decimal:
    """Conservative haircut: reduce favorable gross only; leave losses intact."""
    if gross <= 0:
        return gross
    return gross * (Decimal("1") - haircut_rate)


def _apply_non_fill_haircut(net: Decimal, non_fill_rate: Decimal) -> Decimal:
    """Conservative non-fill model: remove winning contribution only."""
    if net <= 0:
        return net
    return net * (Decimal("1") - non_fill_rate)


def _scenario_net_for_cycle(
    cycle: ModeCycle,
    *,
    scenario_name: str,
    entry_rate: Optional[Decimal],
    exit_rate: Optional[Decimal],
    adverse_selection_haircut: Decimal = Decimal("0"),
    non_fill_rate: Decimal = Decimal("0"),
    target_notional: Optional[Decimal] = None,
) -> Tuple[Decimal, Decimal, Decimal]:
    original_notional = cycle.notional if cycle.notional > 0 else Decimal("5")
    notional = target_notional or original_notional
    gross = cycle.mode_gross
    if target_notional is not None and original_notional > 0:
        gross = gross * (target_notional / original_notional)
    gross = _apply_adverse_selection_haircut(gross, adverse_selection_haircut)

    if scenario_name == "journal_recorded_fees":
        fees = cycle.journal_fees
        if target_notional is not None and original_notional > 0:
            fees = fees * (target_notional / original_notional)
        net = gross - fees
    else:
        fees, net = _compute_fees_and_net(gross, notional, entry_rate or Decimal("0"), exit_rate or Decimal("0"))

    net = _apply_non_fill_haircut(net, non_fill_rate)
    return gross, fees, net


def _build_predictive_cycles(
    *,
    journal_path: Path,
    ohlcv_fixture: Optional[Path],
    max_cycles: Optional[int],
    max_hold_minutes: int,
) -> Tuple[List[Dict[str, Any]], List[ModeCycle], int, float, Dict[str, int], List[Dict[str, Any]]]:
    all_cycles = parse_journal_cycles(journal_path)
    if max_cycles:
        all_cycles = all_cycles[:max_cycles]

    bars = _load_bars_for_journal(all_cycles, ohlcv_fixture=ohlcv_fixture)
    covered_cycles, _with_c, without_c, coverage_rate, skip_break = _compute_coverage_and_covered(all_cycles, bars)
    predictive_cycles: List[ModeCycle] = []
    predictive_skips: List[Dict[str, Any]] = []

    for idx, cycle in enumerate(covered_cycles):
        pred_price, pred_time, pred_reason, pred_basis = _predictive_live_exit(
            bars,
            cycle,
            max_hold_minutes=max_hold_minutes,
            take_profit_pct=DEFAULT_TAKE_PROFIT_PCT,
            stop_loss_pct=DEFAULT_STOP_LOSS_PCT,
        )
        if pred_price is None:
            predictive_skips.append({
                "cycle_index": idx,
                "symbol": cycle.get("symbol", "UNKNOWN"),
                "reason": pred_reason,
            })
            continue
        predictive_cycles.append(_make_mode_cycle(
            idx,
            cycle,
            mode_exit_reason=pred_reason,
            mode_exit_time=pred_time,
            mode_exit_price=pred_price,
            used_journal_exit_price=False,
            used_journal_exit_time_for_prediction=False,
            used_high_low_for_timeout=False,
            basis=pred_basis,
        ))

    total_skipped = without_c + len(predictive_skips)
    return all_cycles, predictive_cycles, total_skipped, coverage_rate, skip_break, predictive_skips


def _grouped_summary(cycles: Iterable[ModeCycle], scenario_name: str, entry_rate: Optional[Decimal], exit_rate: Optional[Decimal], key_fn) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, List[ModeCycle]] = defaultdict(list)
    for cycle in cycles:
        grouped[str(key_fn(cycle))].append(cycle)

    payload: Dict[str, Dict[str, Any]] = {}
    for key, rows in sorted(grouped.items()):
        gross_sum = Decimal("0")
        fees_sum = Decimal("0")
        net_sum = Decimal("0")
        wins = 0
        losses = 0
        for row in rows:
            gross, fees, net = _scenario_net_for_cycle(
                row,
                scenario_name=scenario_name,
                entry_rate=entry_rate,
                exit_rate=exit_rate,
            )
            gross_sum += gross
            fees_sum += fees
            net_sum += net
            if net > 0:
                wins += 1
            elif net < 0:
                losses += 1
        payload[key] = {
            "cycles": len(rows),
            "gross_pnl_sum": _fmt_money(gross_sum),
            "fee_sum": _fmt_money(fees_sum),
            "net_pnl_sum": _fmt_money(net_sum),
            "wins": wins,
            "losses": losses,
            "win_rate": _rate(wins, len(rows)),
        }
    return payload


def _scenario_summary(cycles: List[ModeCycle], scenario_name: str, entry_rate: Optional[Decimal], exit_rate: Optional[Decimal]) -> Dict[str, Any]:
    gross_sum = Decimal("0")
    fees_sum = Decimal("0")
    net_sum = Decimal("0")
    wins = 0
    losses = 0
    for cycle in cycles:
        gross, fees, net = _scenario_net_for_cycle(
            cycle,
            scenario_name=scenario_name,
            entry_rate=entry_rate,
            exit_rate=exit_rate,
        )
        gross_sum += gross
        fees_sum += fees
        net_sum += net
        if net > 0:
            wins += 1
        elif net < 0:
            losses += 1
    return {
        "gross_pnl_sum": _fmt_money(gross_sum),
        "fee_sum": _fmt_money(fees_sum),
        "net_pnl_sum": _fmt_money(net_sum),
        "wins": wins,
        "losses": losses,
        "breakeven": len(cycles) - wins - losses,
        "win_rate": _rate(wins, len(cycles)),
    }


def _haircut_table(cycles: List[ModeCycle]) -> Dict[str, Any]:
    table: Dict[str, Any] = {}
    for adverse in HAIRCUT_RATES:
        adverse_key = f"adverse_selection_{int(adverse * 100)}pct"
        table[adverse_key] = {}
        for non_fill in NON_FILL_RATES:
            gross_sum = Decimal("0")
            fees_sum = Decimal("0")
            net_sum = Decimal("0")
            wins = 0
            losses = 0
            for cycle in cycles:
                gross, fees, net = _scenario_net_for_cycle(
                    cycle,
                    scenario_name="maker/maker",
                    entry_rate=MAKER_ENTRY,
                    exit_rate=MAKER_EXIT,
                    adverse_selection_haircut=adverse,
                    non_fill_rate=non_fill,
                )
                gross_sum += gross
                fees_sum += fees
                net_sum += net
                if net > 0:
                    wins += 1
                elif net < 0:
                    losses += 1
            table[adverse_key][f"non_fill_{int(non_fill * 100)}pct"] = {
                "gross_pnl_sum": _fmt_money(gross_sum),
                "fee_sum": _fmt_money(fees_sum),
                "net_pnl_sum": _fmt_money(net_sum),
                "wins": wins,
                "losses": losses,
                "win_rate": _rate(wins, len(cycles)),
            }
    return table


def _notional_sensitivity(cycles: List[ModeCycle]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for target in NOTIONAL_TARGETS:
        entry: Dict[str, Any] = {}
        for name in ["taker/taker", "maker/maker", "zero_fee_theoretical"]:
            entry_rate, exit_rate = FEE_SCENARIOS[name]
            gross_sum = Decimal("0")
            fees_sum = Decimal("0")
            net_sum = Decimal("0")
            for cycle in cycles:
                gross, fees, net = _scenario_net_for_cycle(
                    cycle,
                    scenario_name=name,
                    entry_rate=entry_rate,
                    exit_rate=exit_rate,
                    target_notional=target,
                )
                gross_sum += gross
                fees_sum += fees
                net_sum += net
            entry[name] = {
                "gross_pnl_sum": _fmt_money(gross_sum),
                "fee_sum": _fmt_money(fees_sum),
                "net_pnl_sum": _fmt_money(net_sum),
            }
        payload[f"${target}"] = entry
    return payload


def _fee_break_even_threshold(cycles: List[ModeCycle]) -> Optional[str]:
    gross_sum = Decimal("0")
    denominator = Decimal("0")
    for cycle in cycles:
        gross_sum += cycle.mode_gross
        denominator += cycle.notional + (cycle.notional + cycle.mode_gross)
    if gross_sum <= 0 or denominator <= 0:
        return None
    return _fmt_rate(gross_sum / denominator)


def _journal_recorded_summary(cycles: List[ModeCycle]) -> Dict[str, Any]:
    gross = sum((c.journal_gross for c in cycles), Decimal("0"))
    fees = sum((c.journal_fees for c in cycles), Decimal("0"))
    net = sum((c.journal_net for c in cycles), Decimal("0"))
    wins = sum(1 for c in cycles if c.journal_net > 0)
    losses = sum(1 for c in cycles if c.journal_net < 0)
    return {
        "gross_pnl_sum": _fmt_money(gross),
        "fee_sum": _fmt_money(fees),
        "net_pnl_sum": _fmt_money(net),
        "wins": wins,
        "losses": losses,
        "breakeven": len(cycles) - wins - losses,
        "win_rate": _rate(wins, len(cycles)),
    }


def _evaluate_feasibility(
    *,
    parity_payload: Dict[str, Any],
    maker_summary: Dict[str, Any],
    haircut_30_net: Decimal,
    cycles_analyzed: int,
) -> Tuple[bool, List[str], List[str]]:
    failed: List[str] = []
    warnings: List[str] = []
    predictive = parity_payload["modes"]["predictive_live_exit_policy"]

    if not parity_payload.get("predictive_replay_trustworthy"):
        failed.append("predictive_replay_trustworthy is false")
    if parity_payload.get("cycles_skipped") != 0:
        failed.append(f"cycles_skipped must be 0 (got {parity_payload.get('cycles_skipped')})")
    if Decimal(str(maker_summary["net_pnl_sum"])) <= 0:
        failed.append(f"maker/maker net must be positive (got {maker_summary['net_pnl_sum']})")
    if haircut_30_net <= 0:
        failed.append(f"maker/maker net after 30pct non-fill/adverse-selection haircut must be positive (got {_fmt_money(haircut_30_net)})")
    if Decimal(str(maker_summary["win_rate"])) < Decimal("0.45"):
        failed.append(f"maker/maker net win rate must be >= 0.45 (got {maker_summary['win_rate']})")
    if abs(Decimal(str(predictive.get("gross_residual", "0")))) > PREDICTIVE_GATES["abs_signed_gross_residual_max"]:
        failed.append(f"signed gross residual outside predictive tolerance (got {predictive.get('gross_residual')})")
    if parity_payload.get("forward_looking_fields_used") is not False:
        failed.append("forward_looking_fields_used must be false")
    if parity_payload.get("aligned_mode_used_for_prediction") is not False:
        failed.append("aligned_mode_used_for_prediction must be false")
    if cycles_analyzed < 50:
        failed.append(f"sample size must be at least 50 cycles (got {cycles_analyzed})")
        warnings.append("sample_size_warning: fewer than 50 cycles")

    return not failed, failed, warnings


def build_maker_post_only_feasibility_report(
    *,
    journal_path: Optional[Path] = None,
    ohlcv_fixture: Optional[Path] = None,
    max_cycles: Optional[int] = None,
    top_n: int = 20,
    max_hold_minutes: int = DEFAULT_MAX_HOLD_MINUTES,
) -> Dict[str, Any]:
    jpath = Path(journal_path) if journal_path else DEFAULT_JOURNAL
    parity = build_live_exit_policy_parity_report(
        journal_path=jpath,
        ohlcv_fixture=ohlcv_fixture,
        max_cycles=max_cycles,
        top_n=top_n,
        max_hold_minutes=max_hold_minutes,
    )
    all_cycles, predictive_cycles, total_skipped, coverage_rate, skip_break, predictive_skips = _build_predictive_cycles(
        journal_path=jpath,
        ohlcv_fixture=ohlcv_fixture,
        max_cycles=max_cycles,
        max_hold_minutes=max_hold_minutes,
    )

    scenario_summaries = {
        name: _scenario_summary(predictive_cycles, name, rates[0], rates[1])
        for name, rates in FEE_SCENARIOS.items()
    }
    haircuts = _haircut_table(predictive_cycles)
    haircut_30_net = _to_decimal(
        haircuts["adverse_selection_30pct"]["non_fill_30pct"]["net_pnl_sum"],
        Decimal("0"),
    )
    maker_summary = scenario_summaries["maker/maker"]
    feasible, failed_gates, warnings = _evaluate_feasibility(
        parity_payload=parity,
        maker_summary=maker_summary,
        haircut_30_net=haircut_30_net,
        cycles_analyzed=len(predictive_cycles),
    )

    predictive_gross = sum((c.mode_gross for c in predictive_cycles), Decimal("0"))
    journal_summary = _journal_recorded_summary(predictive_cycles)
    if predictive_gross <= 0:
        fee_fix_verdict = "fees_alone_cannot_fix_negative_predictive_gross"
    elif Decimal(str(maker_summary["net_pnl_sum"])) <= 0:
        fee_fix_verdict = "gross_edge_too_thin_for_maker_fees"
    elif haircut_30_net <= 0:
        fee_fix_verdict = "maker_fees_help_but_do_not_survive_fill_haircuts"
    else:
        fee_fix_verdict = "maker_fees_plausibly_help_offline_but_not_authorized"

    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "report_class": "maker_post_only_feasibility_offline_model",
        "journal_path": str(jpath),
        "ohlcv_fixture": str(ohlcv_fixture) if ohlcv_fixture else None,
        "cycles_seen": len(all_cycles),
        "cycles_analyzed": len(predictive_cycles),
        "cycles_skipped": total_skipped,
        "coverage_rate": coverage_rate,
        "skip_reason_breakdown": {**skip_break, **dict(Counter(s["reason"] for s in predictive_skips))},
        "predictive_replay_baseline": {
            "predictive_replay_trustworthy": parity["predictive_replay_trustworthy"],
            "failed_predictive_gates": parity["failed_predictive_gates"],
            "signed_gross_residual": parity["modes"]["predictive_live_exit_policy"]["gross_residual"],
            "timeout_residual": parity["modes"]["predictive_live_exit_policy"]["timeout_residual"],
            "direction_match": parity["modes"]["predictive_live_exit_policy"]["direction_match"],
            "exit_reason_match_rate": parity["modes"]["predictive_live_exit_policy"]["exit_reason_match_rate"],
            "timeout_exit_match_rate": parity["modes"]["predictive_live_exit_policy"]["timeout_exit_match_rate"],
            "forward_looking_fields_used": parity["forward_looking_fields_used"],
            "aligned_mode_used_for_prediction": parity["aligned_mode_used_for_prediction"],
        },
        "journal_recorded_on_analyzed_cycles": journal_summary,
        "predictive_gross_pnl_sum": _fmt_money(predictive_gross),
        "fee_scenarios": scenario_summaries,
        "non_fill_adverse_selection_table": haircuts,
        "notional_sensitivity": _notional_sensitivity(predictive_cycles),
        "fee_break_even_threshold": _fee_break_even_threshold(predictive_cycles),
        "fee_break_even_note": "Symmetric entry=exit rate that would make predictive gross net to zero; null when predictive gross <= 0.",
        "per_symbol": _grouped_summary(predictive_cycles, "maker/maker", MAKER_ENTRY, MAKER_EXIT, lambda c: _normalize_symbol(c.symbol)),
        "per_strategy": _grouped_summary(predictive_cycles, "maker/maker", MAKER_ENTRY, MAKER_EXIT, lambda c: c.strategy),
        "per_exit_reason": _grouped_summary(predictive_cycles, "maker/maker", MAKER_ENTRY, MAKER_EXIT, lambda c: c.journal_exit_reason),
        "sample_size_warnings": warnings,
        "fee_fix_verdict": fee_fix_verdict,
        "maker_feasible_offline": feasible,
        "failed_feasibility_gates": failed_gates,
        "implementation_authorized": False,
        "paper_probe_authorized": False,
        "live_probe_authorized": False,
        "scaling_authorized": False,
        "trade_permission": "none",
        "scaling_allowed": False,
        "risk_increase": "not_approved",
        "maker_post_only_implementation_added": False,
        "live_config_risk_runtime_changed": False,
        "notes": [
            "Pure offline feasibility model over predictive live-exit-policy replay.",
            "Adverse-selection haircuts reduce favorable gross only; losses remain intact.",
            "Non-fill haircuts remove winning net contribution only; losses remain intact.",
            "This report does not implement maker/post-only logic and does not authorize paper or live probes.",
        ],
        "next_required_action": (
            "Do not implement maker/post-only. Fees alone are not sufficient under the current gate; continue offline economics review."
            if not feasible
            else "Maker/post-only may be scoped in a later implementation design review only; no paper/live probe is authorized by this report."
        ),
    }
    return payload


def _human_summary(payload: Dict[str, Any]) -> str:
    scenarios = payload["fee_scenarios"]
    haircuts = payload["non_fill_adverse_selection_table"]
    lines = [
        "=== P2-025R MAKER/POST-ONLY FEASIBILITY MODEL ===",
        f"cycles_seen={payload['cycles_seen']} cycles_analyzed={payload['cycles_analyzed']} cycles_skipped={payload['cycles_skipped']} coverage_rate={payload['coverage_rate']}",
        f"predictive_replay_trustworthy={payload['predictive_replay_baseline']['predictive_replay_trustworthy']} failed_predictive_gates={payload['predictive_replay_baseline']['failed_predictive_gates']}",
        f"predictive_gross_pnl_sum={payload['predictive_gross_pnl_sum']} signed_gross_residual={payload['predictive_replay_baseline']['signed_gross_residual']}",
        "",
        "Fee scenarios:",
    ]
    for name, scenario in scenarios.items():
        lines.append(
            f"  {name}: gross={scenario['gross_pnl_sum']} fees={scenario['fee_sum']} "
            f"net={scenario['net_pnl_sum']} win_rate={scenario['win_rate']}"
        )
    lines.extend([
        "",
        "Maker/maker haircuts:",
        f"  30pct adverse + 30pct non-fill net={haircuts['adverse_selection_30pct']['non_fill_30pct']['net_pnl_sum']}",
        f"  50pct adverse + 50pct non-fill net={haircuts['adverse_selection_50pct']['non_fill_50pct']['net_pnl_sum']}",
        f"fee_break_even_threshold={payload['fee_break_even_threshold']}",
        f"fee_fix_verdict={payload['fee_fix_verdict']}",
        f"maker_feasible_offline={str(payload['maker_feasible_offline']).lower()}",
        f"failed_feasibility_gates={payload['failed_feasibility_gates']}",
        "",
        "Authorization flags:",
        f"  implementation_authorized={str(payload['implementation_authorized']).lower()}",
        f"  paper_probe_authorized={str(payload['paper_probe_authorized']).lower()}",
        f"  live_probe_authorized={str(payload['live_probe_authorized']).lower()}",
        f"  scaling_authorized={str(payload['scaling_authorized']).lower()}",
        "Safety: trade_permission=none scaling_allowed=false risk_increase=not_approved",
        f"next_required_action={payload['next_required_action']}",
        "=== END REPORT ===",
    ])
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Maker/post-only feasibility report (P2-025R, offline only)")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--journal", type=Path, default=None)
    parser.add_argument("--ohlcv-fixture", type=Path, default=None)
    parser.add_argument("--max-cycles", type=int, default=None)
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--max-hold-minutes", type=int, default=DEFAULT_MAX_HOLD_MINUTES)
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON write path; no write by default")
    args = parser.parse_args(argv)

    payload = build_maker_post_only_feasibility_report(
        journal_path=args.journal,
        ohlcv_fixture=args.ohlcv_fixture,
        max_cycles=args.max_cycles,
        top_n=args.top_n,
        max_hold_minutes=args.max_hold_minutes,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if args.json:
        json.dump(payload, sys.stdout, indent=2)
        print()
    else:
        print(_human_summary(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
