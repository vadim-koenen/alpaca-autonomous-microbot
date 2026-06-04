#!/usr/bin/env python3
"""
P2-025P predictive live exit-policy parity report.

Offline-only diagnostic. Compares:
- original simulated TP/SL high-low replay from the existing harness
- journal-exit-aligned control from P2-025O
- predictive live-exit-policy approximation that uses entry facts plus future
  candle-close scan decisions, never journal exit price/time for prediction

No broker clients, no .env, no network, no orders, no runtime mutation.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coinbase_offline_backtest import (
    DEFAULT_MAX_HOLD_MINUTES,
    DEFAULT_STOP_LOSS_PCT,
    DEFAULT_TAKE_PROFIT_PCT,
    Bar,
    _normalize_symbol,
    normalize_exit_reason,
    parse_journal_cycles,
    run_journal_window_replay,
)
from scripts.coinbase_live_exit_policy_fidelity import _compute_gross_from_prices
from scripts.coinbase_replay_economics_report import (
    _compute_coverage_and_covered,
    _fmt_money,
    _load_bars_for_journal,
    _to_decimal,
)
from scripts.coinbase_replay_price_basis_reconciliation import _is_timeout_exit

SCHEMA_VERSION = "p2-025p.coinbase_live_exit_policy_parity.v1"
DEFAULT_JOURNAL = ROOT / "journal_coinbase_crypto.csv"
MONEY_QUANT = Decimal("0.00000001")

PREDICTIVE_GATES = {
    "direction_match_min": Decimal("0.90"),
    "exit_reason_match_rate_min": Decimal("0.90"),
    "timeout_exit_match_rate_min": Decimal("0.95"),
    "abs_signed_gross_residual_max": Decimal("0.10"),
    "timeout_abs_signed_gross_residual_max": Decimal("0.05"),
    "exit_timestamp_delta_median_max_minutes": Decimal("5"),
}


@dataclass
class ModeCycle:
    cycle_index: int
    symbol: str
    strategy: str
    journal_exit_reason: str
    journal_entry_time: Optional[datetime]
    journal_exit_time: Optional[datetime]
    journal_entry_price: Decimal
    journal_exit_price: Decimal
    journal_gross: Decimal
    journal_fees: Decimal
    journal_net: Decimal
    notional: Decimal
    mode_exit_reason: str
    mode_exit_time: Optional[datetime]
    mode_exit_price: Decimal
    mode_gross: Decimal
    used_journal_exit_price: bool = False
    used_journal_exit_time_for_prediction: bool = False
    used_high_low_for_timeout: bool = False
    basis: str = ""

    @property
    def gross_residual(self) -> Decimal:
        return self.mode_gross - self.journal_gross

    @property
    def net_residual_using_journal_fees(self) -> Decimal:
        return (self.mode_gross - self.journal_fees) - self.journal_net

    @property
    def direction_match(self) -> Optional[bool]:
        mode_net = self.mode_gross - self.journal_fees
        if mode_net == 0 and self.journal_net == 0:
            return None
        return (mode_net > 0) == (self.journal_net > 0)

    @property
    def exit_reason_match(self) -> bool:
        return _reason_bucket(self.mode_exit_reason) == _reason_bucket(self.journal_exit_reason)

    @property
    def exit_timestamp_delta_minutes(self) -> Optional[Decimal]:
        if not self.mode_exit_time or not self.journal_exit_time:
            return None
        delta = abs((self.mode_exit_time - self.journal_exit_time).total_seconds()) / 60.0
        return Decimal(str(delta))

    @property
    def hold_duration_minutes(self) -> Optional[Decimal]:
        if not self.mode_exit_time or not self.journal_entry_time:
            return None
        delta = (self.mode_exit_time - self.journal_entry_time).total_seconds() / 60.0
        return Decimal(str(delta))


def _fmt_decimal(value: Decimal) -> str:
    return str(value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP))


def _rate(numer: int, denom: int) -> Optional[float]:
    if denom <= 0:
        return None
    return round(numer / denom, 6)


def _reason_bucket(reason: str) -> str:
    normalized = normalize_exit_reason(reason or "")
    lower = normalized.lower()
    if "max hold" in lower or "timeout" in lower or "end_of_data" in lower:
        return "timeout"
    if "stop-loss" in lower or "stop loss" in lower or lower == "stop_loss":
        return "stop_loss"
    if "take-profit" in lower or "take profit" in lower or lower == "take_profit":
        return "take_profit"
    return normalized or "unknown"


def _mode_reason_from_replay(reason: str) -> str:
    lower = (reason or "").lower()
    if lower == "take_profit":
        return "take-profit hit"
    if lower == "stop_loss":
        return "stop-loss hit"
    if lower in {"max_hold_time_exceeded", "end_of_data"}:
        return "max hold time 90min exceeded"
    return normalize_exit_reason(reason or "unknown")


def _p90(values: List[Decimal]) -> Optional[Decimal]:
    if not values:
        return None
    ordered = sorted(values)
    idx = int(Decimal("0.90") * Decimal(len(ordered) - 1))
    return ordered[idx]


def _median(values: List[Decimal]) -> Optional[Decimal]:
    if not values:
        return None
    return Decimal(str(median([float(v) for v in values])))


def _find_symbol_bars(bars: Sequence[Bar], symbol: str) -> List[Bar]:
    nsym = _normalize_symbol(symbol)
    return sorted([b for b in bars if _normalize_symbol(b.symbol) == nsym], key=lambda b: b.t)


def _first_bar_at_or_after(bars: Sequence[Bar], when: datetime) -> Optional[Bar]:
    for bar in bars:
        if bar.t >= when:
            return bar
    return None


def _predictive_live_exit(
    bars: Sequence[Bar],
    cycle: Dict[str, Any],
    *,
    max_hold_minutes: int,
    take_profit_pct: Decimal,
    stop_loss_pct: Decimal,
) -> Tuple[Optional[Decimal], Optional[datetime], str, str]:
    symbol = cycle.get("symbol", "")
    entry_time = cycle.get("entry_time")
    entry_price = _to_decimal(cycle.get("entry_price"))
    if not entry_time or entry_price <= 0:
        return None, None, "missing_entry_fields", "missing_entry_fields"

    symbol_bars = _find_symbol_bars(bars, symbol)
    if not symbol_bars:
        return None, None, "missing_symbol_bars", "missing_symbol_bars"

    target_time = entry_time + timedelta(minutes=max_hold_minutes)
    take_profit_level = entry_price * (Decimal("1") + (take_profit_pct / Decimal("100")))
    stop_loss_level = entry_price * (Decimal("1") - (stop_loss_pct / Decimal("100")))
    fallback_bar: Optional[Bar] = None

    for bar in symbol_bars:
        if bar.t <= entry_time:
            continue
        fallback_bar = bar
        price = bar.c
        if price <= stop_loss_level:
            return price, bar.t, "stop-loss hit", "scan_candle_close_stop_loss"
        if price >= take_profit_level:
            return price, bar.t, "take-profit hit", "scan_candle_close_take_profit"
        if bar.t >= target_time:
            return price, bar.t, f"max hold time {max_hold_minutes}min exceeded", "scan_candle_close_at_or_after_entry_plus_max_hold"

    if fallback_bar:
        return fallback_bar.c, fallback_bar.t, "end_of_data", "last_available_candle_close_before_decision"
    return None, None, "insufficient_bars_after_entry", "insufficient_bars_after_entry"


def _cycle_common(cycle_index: int, cycle: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "cycle_index": cycle_index,
        "symbol": cycle.get("symbol", "UNKNOWN"),
        "strategy": cycle.get("strategy", "unknown"),
        "journal_exit_reason": cycle.get("exit_reason", "unknown"),
        "journal_entry_time": cycle.get("entry_time"),
        "journal_exit_time": cycle.get("exit_time"),
        "journal_entry_price": _to_decimal(cycle.get("entry_price")),
        "journal_exit_price": _to_decimal(cycle.get("exit_price")),
        "journal_gross": _to_decimal(cycle.get("gross_pnl_recorded")),
        "journal_fees": _to_decimal(cycle.get("fees_recorded")),
        "journal_net": _to_decimal(cycle.get("net_pnl_recorded")),
        "notional": _to_decimal(cycle.get("notional"), Decimal("5")),
    }


def _make_mode_cycle(
    cycle_index: int,
    cycle: Dict[str, Any],
    *,
    mode_exit_reason: str,
    mode_exit_time: Optional[datetime],
    mode_exit_price: Decimal,
    used_journal_exit_price: bool,
    used_journal_exit_time_for_prediction: bool,
    used_high_low_for_timeout: bool,
    basis: str,
) -> ModeCycle:
    common = _cycle_common(cycle_index, cycle)
    gross = _compute_gross_from_prices(common["journal_entry_price"], mode_exit_price, common["notional"])
    return ModeCycle(
        **common,
        mode_exit_reason=mode_exit_reason,
        mode_exit_time=mode_exit_time,
        mode_exit_price=mode_exit_price,
        mode_gross=gross,
        used_journal_exit_price=used_journal_exit_price,
        used_journal_exit_time_for_prediction=used_journal_exit_time_for_prediction,
        used_high_low_for_timeout=used_high_low_for_timeout,
        basis=basis,
    )


def _mode_summary(name: str, cycles: List[ModeCycle], *, control_only: bool = False) -> Dict[str, Any]:
    gross_residuals = [c.gross_residual for c in cycles]
    net_residuals = [c.net_residual_using_journal_fees for c in cycles]
    abs_residuals = [abs(v) for v in gross_residuals]
    direction_values = [c.direction_match for c in cycles if c.direction_match is not None]
    reason_matches = [c.exit_reason_match for c in cycles]
    timeout_journal = [c for c in cycles if _reason_bucket(c.journal_exit_reason) == "timeout"]
    stop_journal = [c for c in cycles if _reason_bucket(c.journal_exit_reason) == "stop_loss"]
    take_journal = [c for c in cycles if _reason_bucket(c.journal_exit_reason) == "take_profit"]
    deltas = [c.exit_timestamp_delta_minutes for c in cycles if c.exit_timestamp_delta_minutes is not None]
    timeout_residual = sum((c.gross_residual for c in timeout_journal), Decimal("0"))

    by_symbol: Dict[str, Dict[str, Any]] = {}
    by_reason: Dict[str, Dict[str, Any]] = {}
    for key, grouped in _group_by(cycles, lambda c: c.symbol).items():
        vals = [c.gross_residual for c in grouped]
        by_symbol[key] = {
            "cycles": len(grouped),
            "signed_gross_residual": _fmt_money(sum(vals, Decimal("0"))),
            "median_abs_residual": _fmt_money(_median([abs(v) for v in vals]) or Decimal("0")),
        }
    for key, grouped in _group_by(cycles, lambda c: _reason_bucket(c.journal_exit_reason)).items():
        vals = [c.gross_residual for c in grouped]
        by_reason[key] = {
            "cycles": len(grouped),
            "signed_gross_residual": _fmt_money(sum(vals, Decimal("0"))),
            "direction_match": _rate(sum(1 for c in grouped if c.direction_match is True), sum(1 for c in grouped if c.direction_match is not None)),
        }

    return {
        "mode_name": name,
        "control_only": control_only,
        "cycles_analyzed": len(cycles),
        "direction_match": _rate(sum(1 for v in direction_values if v), len(direction_values)),
        "gross_residual": _fmt_money(sum(gross_residuals, Decimal("0"))),
        "net_residual_using_journal_fees": _fmt_money(sum(net_residuals, Decimal("0"))),
        "median_abs_residual": _fmt_money(_median(abs_residuals) or Decimal("0")),
        "p90_abs_residual": _fmt_money(_p90(abs_residuals) or Decimal("0")),
        "exit_reason_match_rate": _rate(sum(1 for v in reason_matches if v), len(reason_matches)),
        "timeout_exit_match_rate": _rate(sum(1 for c in timeout_journal if _reason_bucket(c.mode_exit_reason) == "timeout"), len(timeout_journal)),
        "stop_loss_match_rate": _rate(sum(1 for c in stop_journal if _reason_bucket(c.mode_exit_reason) == "stop_loss"), len(stop_journal)),
        "take_profit_match_rate": _rate(sum(1 for c in take_journal if _reason_bucket(c.mode_exit_reason) == "take_profit"), len(take_journal)),
        "exit_timestamp_delta_median": str((_median(deltas) or Decimal("0")).quantize(Decimal("0.000001"))) if deltas else None,
        "exit_timestamp_delta_p90": str((_p90(deltas) or Decimal("0")).quantize(Decimal("0.000001"))) if deltas else None,
        "timeout_residual": _fmt_money(timeout_residual),
        "by_symbol_residual": by_symbol,
        "by_exit_reason_residual": by_reason,
        "used_journal_exit_price_count": sum(1 for c in cycles if c.used_journal_exit_price),
        "used_journal_exit_time_for_prediction_count": sum(1 for c in cycles if c.used_journal_exit_time_for_prediction),
        "used_high_low_for_timeout_count": sum(1 for c in cycles if c.used_high_low_for_timeout),
    }


def _group_by(cycles: Iterable[ModeCycle], key_fn) -> Dict[str, List[ModeCycle]]:
    grouped: Dict[str, List[ModeCycle]] = defaultdict(list)
    for cycle in cycles:
        grouped[str(key_fn(cycle))].append(cycle)
    return dict(grouped)


def _evaluate_predictive_gates(summary: Dict[str, Any]) -> Tuple[bool, List[str]]:
    failed: List[str] = []

    def dec_value(key: str, default: str = "0") -> Decimal:
        value = summary.get(key)
        if value is None:
            return Decimal(default)
        return Decimal(str(value))

    direction = dec_value("direction_match", "-1")
    if direction < PREDICTIVE_GATES["direction_match_min"]:
        failed.append(f"direction_match < 0.90 (got {summary.get('direction_match')})")
    reason_match = dec_value("exit_reason_match_rate", "-1")
    if reason_match < PREDICTIVE_GATES["exit_reason_match_rate_min"]:
        failed.append(f"exit_reason_match_rate < 0.90 (got {summary.get('exit_reason_match_rate')})")
    timeout_match = dec_value("timeout_exit_match_rate", "-1")
    if timeout_match < PREDICTIVE_GATES["timeout_exit_match_rate_min"]:
        failed.append(f"timeout_exit_match_rate < 0.95 (got {summary.get('timeout_exit_match_rate')})")
    if abs(Decimal(str(summary.get("gross_residual", "0")))) > PREDICTIVE_GATES["abs_signed_gross_residual_max"]:
        failed.append(f"abs signed gross residual > 0.10 (got {summary.get('gross_residual')})")
    if abs(Decimal(str(summary.get("timeout_residual", "0")))) > PREDICTIVE_GATES["timeout_abs_signed_gross_residual_max"]:
        failed.append(f"timeout residual > 0.05 (got {summary.get('timeout_residual')})")
    median_delta = summary.get("exit_timestamp_delta_median")
    if median_delta is None or Decimal(str(median_delta)) > PREDICTIVE_GATES["exit_timestamp_delta_median_max_minutes"]:
        failed.append(f"exit timestamp median delta > one scan interval (got {median_delta})")
    if summary.get("used_journal_exit_time_for_prediction_count") != 0:
        failed.append("journal exit time used for prediction")
    if summary.get("used_journal_exit_price_count") != 0:
        failed.append("journal exit price used for prediction")
    if summary.get("used_high_low_for_timeout_count") != 0:
        failed.append("high/low used for timeout")

    return not failed, failed


def _cycle_to_dict(cycle: ModeCycle) -> Dict[str, Any]:
    return {
        "cycle_index": cycle.cycle_index,
        "symbol": cycle.symbol,
        "strategy": cycle.strategy,
        "journal_exit_reason": cycle.journal_exit_reason,
        "mode_exit_reason": cycle.mode_exit_reason,
        "journal_entry_time": cycle.journal_entry_time.isoformat() if cycle.journal_entry_time else None,
        "journal_exit_time": cycle.journal_exit_time.isoformat() if cycle.journal_exit_time else None,
        "mode_exit_time": cycle.mode_exit_time.isoformat() if cycle.mode_exit_time else None,
        "journal_entry_price": str(cycle.journal_entry_price),
        "journal_exit_price": str(cycle.journal_exit_price),
        "mode_exit_price": str(cycle.mode_exit_price),
        "journal_gross": str(cycle.journal_gross),
        "mode_gross": str(cycle.mode_gross),
        "gross_residual": str(cycle.gross_residual),
        "net_residual_using_journal_fees": str(cycle.net_residual_using_journal_fees),
        "direction_match": cycle.direction_match,
        "exit_reason_match": cycle.exit_reason_match,
        "exit_timestamp_delta_minutes": str(cycle.exit_timestamp_delta_minutes) if cycle.exit_timestamp_delta_minutes is not None else None,
        "notional": str(cycle.notional),
        "used_journal_exit_price": cycle.used_journal_exit_price,
        "used_journal_exit_time_for_prediction": cycle.used_journal_exit_time_for_prediction,
        "used_high_low_for_timeout": cycle.used_high_low_for_timeout,
        "basis": cycle.basis,
    }


def _dominant_driver(predictive_summary: Dict[str, Any]) -> str:
    reason_match = predictive_summary.get("exit_reason_match_rate")
    timeout_match = predictive_summary.get("timeout_exit_match_rate")
    gross_res = abs(Decimal(str(predictive_summary.get("gross_residual", "0"))))
    timeout_res = abs(Decimal(str(predictive_summary.get("timeout_residual", "0"))))
    if timeout_match is not None and Decimal(str(timeout_match)) < PREDICTIVE_GATES["timeout_exit_match_rate_min"]:
        return "timeout_policy_parity_gap"
    if reason_match is not None and Decimal(str(reason_match)) < PREDICTIVE_GATES["exit_reason_match_rate_min"]:
        return "exit_reason_policy_gap"
    if timeout_res > PREDICTIVE_GATES["timeout_abs_signed_gross_residual_max"]:
        return "timeout_price_basis_gap"
    if gross_res > PREDICTIVE_GATES["abs_signed_gross_residual_max"]:
        return "predictive_price_basis_gap"
    return "no_dominant_gap_detected"


def build_live_exit_policy_parity_report(
    *,
    journal_path: Optional[Path] = None,
    ohlcv_fixture: Optional[Path] = None,
    max_cycles: Optional[int] = None,
    top_n: int = 20,
    max_hold_minutes: int = DEFAULT_MAX_HOLD_MINUTES,
) -> Dict[str, Any]:
    jpath = Path(journal_path) if journal_path else DEFAULT_JOURNAL
    all_cycles = parse_journal_cycles(jpath)
    if max_cycles:
        all_cycles = all_cycles[:max_cycles]

    bars = _load_bars_for_journal(all_cycles, ohlcv_fixture=ohlcv_fixture)
    covered_cycles, _with_c, without_c, coverage_rate, skip_break = _compute_coverage_and_covered(all_cycles, bars)
    zero_run = run_journal_window_replay(
        bars,
        covered_cycles,
        entry_fee_rate=Decimal("0"),
        exit_fee_rate=Decimal("0"),
        fee_scenario="zero_fee",
    )

    skipped_details: List[Dict[str, Any]] = []
    covered_ids = {id(c) for c in covered_cycles}
    for c in all_cycles:
        if id(c) not in covered_ids:
            skipped_details.append({
                "symbol": c.get("symbol", "UNKNOWN"),
                "strategy": c.get("strategy", "unknown"),
                "entry_time": c.get("entry_time").isoformat() if c.get("entry_time") else None,
                "exit_time": c.get("exit_time").isoformat() if c.get("exit_time") else None,
                "reason": "no_ohlcv_in_window",
            })

    original_cycles: List[ModeCycle] = []
    aligned_cycles: List[ModeCycle] = []
    predictive_cycles: List[ModeCycle] = []
    predictive_skips: List[Dict[str, Any]] = []

    for idx, cycle in enumerate(covered_cycles):
        pc = zero_run.get("per_cycle", [{}])[idx] if idx < len(zero_run.get("per_cycle", [])) else {}
        if pc.get("replayed") is False:
            continue

        replay_exit_price = _to_decimal(pc.get("replayed_exit_price"))
        if replay_exit_price <= 0:
            replay_gross = _to_decimal(pc.get("replayed_gross"))
            entry_price = _to_decimal(cycle.get("entry_price"))
            notional = _to_decimal(cycle.get("notional"), Decimal("5"))
            replay_exit_price = entry_price + ((replay_gross / (notional / entry_price)) if entry_price > 0 and notional > 0 else Decimal("0"))

        original_reason = _mode_reason_from_replay(pc.get("replayed_exit_reason", "unknown"))
        original_cycles.append(_make_mode_cycle(
            idx,
            cycle,
            mode_exit_reason=original_reason,
            mode_exit_time=_parse_time(pc.get("exit_time") or pc.get("replayed_exit_time")),
            mode_exit_price=replay_exit_price,
            used_journal_exit_price=False,
            used_journal_exit_time_for_prediction=False,
            used_high_low_for_timeout=_reason_bucket(original_reason) == "timeout",
            basis="existing_replay_tp_sl_high_low_or_timeout_close",
        ))

        journal_exit_price = _to_decimal(cycle.get("exit_price"))
        if journal_exit_price <= 0:
            journal_exit_price = _to_decimal(cycle.get("entry_price"))
        aligned_cycles.append(_make_mode_cycle(
            idx,
            cycle,
            mode_exit_reason=cycle.get("exit_reason", "unknown"),
            mode_exit_time=cycle.get("exit_time"),
            mode_exit_price=journal_exit_price,
            used_journal_exit_price=True,
            used_journal_exit_time_for_prediction=True,
            used_high_low_for_timeout=False,
            basis="journal_exit_aligned_control_not_predictive",
        ))

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

    original_summary = _mode_summary("original_simulated_tp_sl_high_low", original_cycles)
    aligned_summary = _mode_summary("journal_exit_aligned_control", aligned_cycles, control_only=True)
    predictive_summary = _mode_summary("predictive_live_exit_policy", predictive_cycles)
    predictive_trustworthy, failed_gates = _evaluate_predictive_gates(predictive_summary)

    original_gross = Decimal(str(original_summary["gross_residual"]))
    predictive_gross = Decimal(str(predictive_summary["gross_residual"]))
    aligned_gross = Decimal(str(aligned_summary["gross_residual"]))

    top_residual = sorted(predictive_cycles, key=lambda c: abs(c.gross_residual), reverse=True)[:top_n]
    top_mismatch = [
        c for c in predictive_cycles
        if c.direction_match is False or not c.exit_reason_match
    ][:top_n]

    payload = {
        "schema_version": SCHEMA_VERSION,
        "report_class": "predictive_live_exit_policy_parity",
        "journal_path": str(jpath),
        "ohlcv_fixture": str(ohlcv_fixture) if ohlcv_fixture else None,
        "cycles_seen": len(all_cycles),
        "cycles_analyzed": len(predictive_cycles),
        "cycles_skipped": without_c + len(predictive_skips),
        "coverage_rate": coverage_rate,
        "skip_reason_breakdown": {**skip_break, **dict(Counter(s["reason"] for s in predictive_skips))},
        "skipped_cycle_details": skipped_details + predictive_skips,
        "mode_order": [
            "original_simulated_tp_sl_high_low",
            "journal_exit_aligned_control",
            "predictive_live_exit_policy",
        ],
        "modes": {
            "original_simulated_tp_sl_high_low": original_summary,
            "journal_exit_aligned_control": aligned_summary,
            "predictive_live_exit_policy": predictive_summary,
        },
        "comparisons": {
            "predictive_vs_original_residual_delta": _fmt_money(predictive_gross - original_gross),
            "predictive_vs_journal_aligned_gap": _fmt_money(predictive_gross - aligned_gross),
            "original_vs_journal_aligned_gap": _fmt_money(original_gross - aligned_gross),
        },
        "predictive_replay_trustworthy": predictive_trustworthy,
        "failed_predictive_gates": failed_gates,
        "predictive_gate_thresholds": {
            "direction_match_min": "0.90",
            "exit_reason_match_rate_min": "0.90",
            "timeout_exit_match_rate_min": "0.95",
            "abs_signed_gross_residual_max": "0.10",
            "timeout_abs_signed_gross_residual_max": "0.05",
            "exit_timestamp_delta_median_max_minutes": "5",
        },
        "forward_looking_fields_used": False,
        "aligned_mode_used_for_prediction": False,
        "aligned_replay_trustworthy": True,
        "aligned_replay_trustworthy_scope": "reconciliation_control_only_not_predictive_backtest_evidence",
        "original_replay_behavior_modified": False,
        "top_residual_cycles": [_cycle_to_dict(c) for c in top_residual],
        "top_mismatch_cycles": [_cycle_to_dict(c) for c in top_mismatch],
        "dominant_residual_driver": _dominant_driver(predictive_summary),
        "next_required_action": _next_required_action(
            predictive_trustworthy=predictive_trustworthy,
            cycles_skipped=without_c + len(predictive_skips),
        ),
        "trade_permission": "none",
        "scaling_allowed": False,
        "risk_increase": "not_approved",
        "notes": [
            "Pure offline diagnostic; no broker access and no runtime changes.",
            "Journal-exit-aligned mode is a reconciliation control only and is never used for predictive decisions.",
            "Predictive mode uses journal entry price/time, candle close scan decisions, configured TP/SL constants, and max-hold timeout.",
            "Predictive timeout exits do not use candle high/low or journal exit price/timestamp.",
            "Original simulated replay behavior is consumed as-is and not modified.",
        ],
    }
    return payload


def _next_required_action(*, predictive_trustworthy: bool, cycles_skipped: int) -> str:
    if not predictive_trustworthy:
        return (
            "Do not implement maker/post-only or exit tuning yet. First close predictive parity gaps by extracting "
            "current live exit decision semantics into an offline-pure simulator and rerun until predictive gates pass."
        )
    if cycles_skipped > 0:
        return (
            "Predictive parity gates passed on covered cycles, but coverage is incomplete. Close skipped OHLCV gaps "
            "and rerun to 50/50 coverage before scoping maker/post-only feasibility; do not implement maker/post-only yet."
        )
    return (
        "Predictive parity gates passed with complete coverage. A future review may scope maker/post-only feasibility "
        "without live implementation; do not implement maker/post-only in this patch."
    )


def _parse_time(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _human_summary(payload: Dict[str, Any]) -> str:
    predictive = payload["modes"]["predictive_live_exit_policy"]
    original = payload["modes"]["original_simulated_tp_sl_high_low"]
    aligned = payload["modes"]["journal_exit_aligned_control"]
    lines = [
        "=== P2-025P PREDICTIVE LIVE EXIT-POLICY PARITY ===",
        f"cycles_seen={payload['cycles_seen']} cycles_analyzed={payload['cycles_analyzed']} cycles_skipped={payload['cycles_skipped']}",
        "",
        "Original simulated TP/SL high-low replay:",
        f"  direction_match={original['direction_match']} gross_residual={original['gross_residual']} exit_reason_match_rate={original['exit_reason_match_rate']}",
        "Journal-exit-aligned control (not predictive evidence):",
        f"  direction_match={aligned['direction_match']} gross_residual={aligned['gross_residual']} control_only={aligned['control_only']}",
        "Predictive live exit-policy approximation:",
        f"  direction_match={predictive['direction_match']} gross_residual={predictive['gross_residual']} timeout_residual={predictive['timeout_residual']}",
        f"  exit_reason_match_rate={predictive['exit_reason_match_rate']} timeout_exit_match_rate={predictive['timeout_exit_match_rate']}",
        f"  exit_timestamp_delta_median={predictive['exit_timestamp_delta_median']} p90={predictive['exit_timestamp_delta_p90']}",
        "",
        f"predictive_replay_trustworthy={payload['predictive_replay_trustworthy']}",
        f"failed_predictive_gates={payload['failed_predictive_gates']}",
        f"dominant_residual_driver={payload['dominant_residual_driver']}",
        f"next_required_action={payload['next_required_action']}",
        "",
        "Safety: trade_permission=none scaling_allowed=false risk_increase=not_approved",
        "No live broker calls, no live-read-only, no launchctl, no orders, no config/risk changes.",
        "=== END REPORT ===",
    ]
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Predictive live exit-policy parity report (P2-025P, offline only)")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--journal", type=Path, default=None)
    parser.add_argument("--ohlcv-fixture", type=Path, default=None)
    parser.add_argument("--max-cycles", type=int, default=None)
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--max-hold-minutes", type=int, default=DEFAULT_MAX_HOLD_MINUTES)
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON write path; no write by default")
    args = parser.parse_args(argv)

    payload = build_live_exit_policy_parity_report(
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
