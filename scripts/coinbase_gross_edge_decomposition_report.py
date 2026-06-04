#!/usr/bin/env python3
"""
P2-025S gross-edge failure decomposition report.

Offline-only. Decomposes negative predictive gross edge by symbol, strategy,
entry context, exit reason, hold duration, and spread. Isolates why the
current strategy loses before fees.
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

SCHEMA_VERSION = "p2-025s.coinbase_gross_edge_decomposition.v1"
MONEY_QUANT = Decimal("0.00000001")


def _fmt_money(value: Decimal) -> str:
    return str(value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP))


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _bucket_duration(minutes: Optional[Decimal]) -> str:
    if minutes is None:
        return "unknown"
    if minutes <= 15:
        return "0-15min"
    if minutes <= 30:
        return "15-30min"
    if minutes <= 60:
        return "30-60min"
    if minutes <= 90:
        return "60-90min"
    return ">90min"


def _bucket_spread(spread_pct: Decimal) -> str:
    if spread_pct <= Decimal("0.05"):
        return "0.00-0.05%"
    if spread_pct <= Decimal("0.10"):
        return "0.05-0.10%"
    if spread_pct <= Decimal("0.15"):
        return "0.10-0.15%"
    if spread_pct <= Decimal("0.20"):
        return "0.15-0.20%"
    return ">0.20%"


def _bucket_notional(notional: Decimal) -> str:
    if notional <= Decimal("1.0"):
        return "<=$1"
    if notional <= Decimal("5.0"):
        return "$1-$5"
    if notional <= Decimal("10.0"):
        return "$5-$10"
    return ">$10"


def _bucket_confidence(conf: Decimal) -> str:
    if conf <= Decimal("0.65"):
        return "<=0.65"
    if conf <= Decimal("0.70"):
        return "0.65-0.70"
    if conf <= Decimal("0.75"):
        return "0.70-0.75"
    return ">0.75"


def _build_decomposition_cycles(
    *,
    journal_path: Path,
    ohlcv_fixture: Optional[Path],
    max_cycles: Optional[int],
    max_hold_minutes: int,
) -> Tuple[List[Dict[str, Any]], List[ModeCycle], int, float, Dict[str, int]]:
    all_cycles = parse_journal_cycles(journal_path)
    if max_cycles:
        all_cycles = all_cycles[:max_cycles]

    bars = _load_bars_for_journal(all_cycles, ohlcv_fixture=ohlcv_fixture)
    covered_cycles, _with_c, without_c, coverage_rate, skip_break = _compute_coverage_and_covered(all_cycles, bars)
    predictive_cycles: List[ModeCycle] = []
    
    # We need extra fields (spread, confidence) which parse_journal_cycles might skip.
    # Re-reading journal for these specific cycles.
    journal_rows = []
    try:
        import csv
        with open(journal_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            journal_rows = list(reader)
    except Exception:
        pass

    # Match covered cycles back to raw rows for extra metadata
    for idx, cycle in enumerate(covered_cycles):
        # find matching row in journal_rows
        # simple heuristic: matching timestamp and symbol
        meta = {}
        target_ts = cycle.get("raw_timestamp")
        target_sym = cycle.get("symbol")
        for row in journal_rows:
            if row.get("timestamp") == target_ts and row.get("symbol") == target_sym:
                meta = row
                break
        
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
        # Monkey patch extra metadata for decomposition
        mc.spread_pct = _to_decimal(meta.get("spread_pct", "0"))
        mc.confidence = _to_decimal(meta.get("confidence", "0"))
        predictive_cycles.append(mc)

    return all_cycles, predictive_cycles, len(covered_cycles) - len(predictive_cycles) + without_c, coverage_rate, skip_break


def _decompose(cycles: List[ModeCycle], key_fn) -> Dict[str, Any]:
    grouped: Dict[str, List[ModeCycle]] = defaultdict(list)
    for c in cycles:
        grouped[str(key_fn(c))].append(c)
    
    res = {}
    for key, rows in sorted(grouped.items(), key=lambda x: sum((c.mode_gross for c in x[1]), Decimal("0"))):
        gross_sum = sum((c.mode_gross for c in rows), Decimal("0"))
        wins = sum(1 for c in rows if c.mode_gross > 0)
        res[key] = {
            "count": len(rows),
            "gross_pnl_sum": _fmt_money(gross_sum),
            "win_rate": _rate(wins, len(rows)),
            "avg_gross": _fmt_money(gross_sum / len(rows)) if rows else "0.00",
        }
    return res


def _concentration_analysis(cycles: List[ModeCycle]) -> Dict[str, Any]:
    sorted_cycles = sorted(cycles, key=lambda c: c.mode_gross)
    total_gross = sum((c.mode_gross for c in cycles), Decimal("0"))
    
    def sum_n(n: int) -> Decimal:
        return sum((c.mode_gross for c in sorted_cycles[:n]), Decimal("0"))
    
    return {
        "worst_1_gross": _fmt_money(sum_n(1)),
        "worst_3_gross": _fmt_money(sum_n(3)),
        "worst_5_gross": _fmt_money(sum_n(5)),
        "worst_10_gross": _fmt_money(sum_n(10)),
        "total_gross": _fmt_money(total_gross),
    }


def _counterfactual_filters(cycles: List[ModeCycle]) -> Dict[str, Any]:
    total_gross = sum((c.mode_gross for c in cycles), Decimal("0"))
    
    filters = {
        "exclude_stop_loss": lambda c: _reason_bucket(c.mode_exit_reason) != "stop_loss",
        "exclude_timeout": lambda c: _reason_bucket(c.mode_exit_reason) != "timeout",
        "exclude_high_spread_gt_0.15": lambda c: (getattr(c, "spread_pct", Decimal("0")) or Decimal("0")) <= Decimal("0.15"),
        "exclude_low_confidence_le_0.70": lambda c: (getattr(c, "confidence", Decimal("0")) or Decimal("0")) > Decimal("0.70"),
        "exclude_strategy_mean_reversion": lambda c: c.strategy != "mean_reversion",
        "exclude_symbol_ETH/USD": lambda c: c.symbol != "ETH/USD",
        "exclude_symbol_ADA/USD": lambda c: c.symbol != "ADA/USD",
    }
    
    res = {}
    for name, filter_fn in filters.items():
        filtered = [c for c in cycles if filter_fn(c)]
        f_gross = sum((c.mode_gross for c in filtered), Decimal("0"))
        wins = sum(1 for c in filtered if c.mode_gross > 0)
        res[name] = {
            "count": len(filtered),
            "gross_pnl_sum": _fmt_money(f_gross),
            "gross_delta": _fmt_money(f_gross - total_gross),
            "win_rate": _rate(wins, len(filtered)),
            "overfit_risk": len(filtered) < 20
        }
    return res


def build_gross_edge_decomposition_report(
    *,
    journal_path: Optional[Path] = None,
    ohlcv_fixture: Optional[Path] = None,
    max_cycles: Optional[int] = None,
    max_hold_minutes: int = DEFAULT_MAX_HOLD_MINUTES,
) -> Dict[str, Any]:
    jpath = Path(journal_path) if journal_path else DEFAULT_JOURNAL
    all_cycles, predictive_cycles, total_skipped, coverage_rate, skip_break = _build_decomposition_cycles(
        journal_path=jpath,
        ohlcv_fixture=ohlcv_fixture,
        max_cycles=max_cycles,
        max_hold_minutes=max_hold_minutes,
    )

    total_gross = sum((c.mode_gross for c in predictive_cycles), Decimal("0"))
    wins = sum(1 for c in predictive_cycles if c.mode_gross > 0)
    
    sorted_by_gross = sorted(predictive_cycles, key=lambda c: c.mode_gross)
    top_losers = sorted_by_gross[:10]
    top_winners = sorted_by_gross[-10:][::-1]
    
    def cycle_summary(c: ModeCycle) -> Dict[str, Any]:
        d = {
            "symbol": c.symbol,
            "strategy": c.strategy,
            "exit_reason": c.mode_exit_reason,
            "gross": _fmt_money(c.mode_gross),
            "hold_duration_min": str(c.hold_duration_minutes) if c.hold_duration_minutes is not None else "0",
            "parity_delta_min": str(c.exit_timestamp_delta_minutes) if c.exit_timestamp_delta_minutes is not None else "0",
            "spread_pct": _fmt_money(getattr(c, "spread_pct", Decimal("0"))),
            "confidence": _fmt_money(getattr(c, "confidence", Decimal("0"))),
        }
        return d

    per_symbol = _decompose(predictive_cycles, lambda c: c.symbol)
    per_strategy = _decompose(predictive_cycles, lambda c: c.strategy)
    per_exit_reason = _decompose(predictive_cycles, lambda c: _reason_bucket(c.mode_exit_reason))
    per_hold_duration = _decompose(predictive_cycles, lambda c: _bucket_duration(c.hold_duration_minutes))
    per_parity_delta = _decompose(predictive_cycles, lambda c: _bucket_duration(c.exit_timestamp_delta_minutes))
    per_spread = _decompose(predictive_cycles, lambda c: _bucket_spread(getattr(c, "spread_pct", Decimal("0"))))
    per_notional = _decompose(predictive_cycles, lambda c: _bucket_notional(c.notional))
    per_confidence = _decompose(predictive_cycles, lambda c: _bucket_confidence(getattr(c, "confidence", Decimal("0"))))
    
    counterfactuals = _counterfactual_filters(predictive_cycles)
    
    # Verdict
    gross_edge_positive = total_gross > 0
    dominant_loss_driver = "unknown"
    if not gross_edge_positive:
        # Check if one category is dominant
        worst_symbol = next(iter(per_symbol.keys()))
        worst_strategy = next(iter(per_strategy.keys()))
        worst_exit = next(iter(per_exit_reason.keys()))
        
        if Decimal(per_exit_reason[worst_exit]["gross_pnl_sum"]) < total_gross * Decimal("0.5"):
             dominant_loss_driver = f"exit_reason_{worst_exit}"
        elif Decimal(per_symbol[worst_symbol]["gross_pnl_sum"]) < total_gross * Decimal("0.5"):
             dominant_loss_driver = f"symbol_{worst_symbol}"
        elif Decimal(per_strategy[worst_strategy]["gross_pnl_sum"]) < total_gross * Decimal("0.5"):
             dominant_loss_driver = f"strategy_{worst_strategy}"
        else:
             dominant_loss_driver = "diffuse_losses"

    candidate_filters = [name for name, d in counterfactuals.items() if Decimal(d["gross_pnl_sum"]) > total_gross and not d["overfit_risk"]]

    payload = {
        "schema_version": SCHEMA_VERSION,
        "report_class": "gross_edge_decomposition",
        "journal_path": str(jpath),
        "cycles_seen": len(all_cycles),
        "cycles_analyzed": len(predictive_cycles),
        "cycles_skipped": total_skipped,
        "coverage_rate": coverage_rate,
        "predictive_gross_total": _fmt_money(total_gross),
        "gross_edge_positive": gross_edge_positive,
        "win_rate": _rate(wins, len(predictive_cycles)),
        "avg_gross_per_cycle": _fmt_money(total_gross / len(predictive_cycles)) if predictive_cycles else "0",
        "median_gross_per_cycle": _fmt_money(Decimal(str(median([float(c.mode_gross) for c in predictive_cycles])))) if predictive_cycles else "0",
        "concentration": _concentration_analysis(predictive_cycles),
        "top_10_winners": [cycle_summary(c) for c in top_winners],
        "top_10_losers": [cycle_summary(c) for c in top_losers],
        "decomposition": {
            "per_symbol": per_symbol,
            "per_strategy": per_strategy,
            "per_exit_reason": per_exit_reason,
            "per_hold_duration": per_hold_duration,
            "per_parity_delta": per_parity_delta,
            "per_spread": per_spread,
            "per_notional": per_notional,
            "per_confidence": per_confidence,
        },
        "counterfactual_filters": counterfactuals,
        "dominant_loss_driver": dominant_loss_driver,
        "candidate_filters_for_future_backtest": candidate_filters,
        "verdict": {
            "gross_edge_positive": gross_edge_positive,
            "implementation_authorized": False,
            "paper_probe_authorized": False,
            "live_probe_authorized": False,
            "scaling_authorized": False,
        },
        "notes": [
            "Decomposes predictive gross edge by multiple dimensions.",
            "Counterfactual filters are hypotheses only; not for live implementation.",
            "Sample size < 20 cycles marked as overfit risk.",
            "Uses predictive candle-close replay basis from P2-025P/R.",
        ]
    }
    return payload


def median(values: List[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def _human_summary(payload: Dict[str, Any]) -> str:
    lines = [
        "=== GROSS-EDGE FAILURE DECOMPOSITION ===",
        f"cycles_analyzed={payload['cycles_analyzed']} coverage={payload['coverage_rate']}",
        f"predictive_gross_total={payload['predictive_gross_total']} win_rate={payload['win_rate']}",
        f"avg_gross={payload['avg_gross_per_cycle']} median_gross={payload['median_gross_per_cycle']}",
        "",
        "Concentration:",
        f"  worst 1: {payload['concentration']['worst_1_gross']}",
        f"  worst 3: {payload['concentration']['worst_3_gross']}",
        f"  worst 5: {payload['concentration']['worst_5_gross']}",
        f"  worst 10: {payload['concentration']['worst_10_gross']}",
        "",
        "Top Losers:",
    ]
    for c in payload["top_10_losers"]:
        lines.append(f"  {c['symbol']} {c['strategy']} {c['exit_reason']} gross={c['gross']} hold={c['hold_duration_min']}m delta={c['parity_delta_min']}m")
    
    lines.extend(["", "Decomposition by Exit Reason:"])
    for k, v in payload["decomposition"]["per_exit_reason"].items():
        lines.append(f"  {k}: count={v['count']} gross={v['gross_pnl_sum']} wr={v['win_rate']}")

    lines.extend(["", "Decomposition by Hold Duration:"])
    for k, v in sorted(payload["decomposition"]["per_hold_duration"].items()):
        lines.append(f"  {k}: count={v['count']} gross={v['gross_pnl_sum']} wr={v['win_rate']}")

    lines.extend(["", "Decomposition by Parity Delta:"])
    for k, v in sorted(payload["decomposition"]["per_parity_delta"].items()):
        lines.append(f"  {k}: count={v['count']} gross={v['gross_pnl_sum']} wr={v['win_rate']}")

    lines.extend(["", "Counterfactual Filters (Hypothetical):"])
    for k, v in payload["counterfactual_filters"].items():
        lines.append(f"  {k}: count={v['count']} gross={v['gross_pnl_sum']} delta={v['gross_delta']} overfit={v['overfit_risk']}")

    lines.extend([
        "",
        f"dominant_loss_driver={payload['dominant_loss_driver']}",
        f"candidate_filters={payload['candidate_filters_for_future_backtest']}",
        "",
        "Authorization: implementation=false paper=false live=false scaling=false",
        "=== END REPORT ===",
    ])
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Gross-edge decomposition report")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--journal", type=Path, default=None)
    parser.add_argument("--ohlcv-fixture", type=Path, default=None)
    parser.add_argument("--max-cycles", type=int, default=None)
    parser.add_argument("--max-hold-minutes", type=int, default=DEFAULT_MAX_HOLD_MINUTES)
    args = parser.parse_args(argv)

    payload = build_gross_edge_decomposition_report(
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
