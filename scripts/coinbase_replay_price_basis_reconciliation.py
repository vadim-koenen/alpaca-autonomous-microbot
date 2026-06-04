#!/usr/bin/env python3
"""
scripts/coinbase_replay_price_basis_reconciliation.py — P2-025N Replay Price-Basis / Fill-Basis Reconciliation.

Offline-only drilldown of per-cycle entry/exit price residuals (replay vs journal fills) vs
nearest OHLCV candles. Attributes gross residual to entry_price vs exit_price vs timeout vs unknown.
Classifies candle high/low containment for journal fills and replay basis (close/open/hl/nearest/inferred).
Flags large residuals. Produces aggregates, by-sym/exit/timeout attribution, top-10 lists, dominant driver.

Reuses: parse_journal_cycles, run_journal_window_replay (zero-fee), load_bars_from_fixture,
_compute_coverage_and_covered, _load_bars_for_journal, _to_decimal, _fmt_money, _normalize_symbol,
and small inference helpers from fidelity (no dup parsing, no exit logic changes).

Pure offline. No broker, no orders, no mutation, no .env, no secrets, no live, no network.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coinbase_offline_backtest import (
    _normalize_symbol,
    load_bars_from_fixture,
    parse_journal_cycles,
    run_journal_window_replay,
)

from scripts.coinbase_replay_economics_report import (
    _compute_coverage_and_covered,
    _load_bars_for_journal,
    _to_decimal,
    _fmt_money,
)

# Reuse small pure helpers from fidelity for consistency (no reimplementation of residual math)
from scripts.coinbase_replay_fidelity_reconciliation import (
    _compute_replay_exit_price,
    _infer_replay_exit_basis,
)

SCHEMA_VERSION = "p2-025n.coinbase_replay_price_basis_reconciliation.v1"
DEFAULT_JOURNAL = ROOT / "journal_coinbase_crypto.csv"
DATA_DIR = ROOT / "data" / "offline_ohlcv" / "coinbase"


def _price_within_candle(p: Decimal, bar: Optional[Any]) -> bool:
    if not bar or p <= 0:
        return False
    try:
        return (bar.l <= p <= bar.h)
    except Exception:
        return False


def _find_nearest_bar(bars: List[Any], target_ts: Any, symbol: Optional[str] = None) -> Optional[Any]:
    if not bars or not target_ts:
        return None
    norm = _normalize_symbol(symbol) if symbol else None
    candidates = bars
    if norm:
        candidates = [b for b in bars if _normalize_symbol(getattr(b, "symbol", "") or "") == norm]
    if not candidates:
        candidates = bars
    best = None
    best_delta = None
    for b in candidates:
        try:
            if not hasattr(b, "t") or b.t is None:
                continue
            delta = abs((b.t - target_ts).total_seconds())
            if best is None or (best_delta is None or delta < best_delta):
                best = b
                best_delta = delta
        except Exception:
            continue
    return best


def _classify_replay_basis(replayed_exit_reason: str) -> str:
    return _infer_replay_exit_basis(replayed_exit_reason)


def _classify_residual_driver(
    j_entry_p: Decimal,
    j_exit_p: Decimal,
    r_entry_p: Decimal,
    r_exit_p: Optional[Decimal],
    entry_candle: Optional[Any],
    exit_candle: Optional[Any],
    entry_ts: Any,
    exit_ts: Any,
    replayed_exit_reason: str,
    gross_res: Decimal,
    entry_res: Decimal,
    exit_res: Decimal,
) -> str:
    if j_entry_p <= 0 or j_exit_p <= 0:
        return "missing_journal_price"
    if not entry_candle or not exit_candle:
        return "missing_ohlcv_window"
    # timestamp alignment: if nearest is > 1 bar away for typical 5m (~10min tolerance)
    try:
        if entry_candle and hasattr(entry_candle, "t"):
            if abs((entry_candle.t - entry_ts).total_seconds()) > 600:
                return "timestamp_alignment_issue"
        if exit_candle and hasattr(exit_candle, "t"):
            if abs((exit_candle.t - exit_ts).total_seconds()) > 600:
                return "timestamp_alignment_issue"
    except Exception:
        pass
    # entry vs exit bias (use small epsilon for float/Decimal noise)
    eps = Decimal("1e-8")
    has_entry_bias = abs(entry_res) > eps
    has_exit_bias = abs(exit_res) > eps
    if has_entry_bias and has_exit_bias:
        return "both_entry_and_exit_bias"
    if has_entry_bias:
        return "entry_price_bias"
    if has_exit_bias:
        r = (replayed_exit_reason or "").lower()
        if "max_hold" in r or "max hold" in r or "timeout" in r:
            return "timeout_exit_basis_issue"
        return "exit_price_bias"
    # no price res but still possible basis mismatch vs fill
    if not _price_within_candle(j_entry_p, entry_candle) or not _price_within_candle(j_exit_p, exit_candle):
        return "candle_close_vs_fill_issue"
    return "unknown"


def _is_timeout_exit(reason: str) -> bool:
    r = (reason or "").lower()
    return "max hold" in r or "max_hold" in r or "timeout" in r or "max_hold_time_exceeded" in r


def build_replay_price_basis_report(
    *,
    journal_path: Optional[Path] = None,
    ohlcv_fixture: Optional[Path] = None,
    max_cycles: Optional[int] = None,
    top_n: int = 10,
) -> Dict[str, Any]:
    jpath = Path(journal_path) if journal_path else DEFAULT_JOURNAL
    all_cycles = parse_journal_cycles(jpath)
    if max_cycles:
        all_cycles = all_cycles[:max_cycles]

    total_seen = len(all_cycles)
    bars = _load_bars_for_journal(all_cycles, ohlcv_fixture=ohlcv_fixture)
    covered_cycles, with_c, without_c, cov_rate, skip_break = _compute_coverage_and_covered(all_cycles, bars)

    # Zero-fee replay for pure gross + per-cycle replay details (replayed_gross, replayed_exit_reason, direction_match)
    zero_run = run_journal_window_replay(
        bars, covered_cycles, entry_fee_rate=Decimal("0"), exit_fee_rate=Decimal("0"), fee_scenario="zero_fee"
    )

    per_cycle_pb: List[Dict[str, Any]] = []
    skipped_details: List[Dict[str, Any]] = []

    # Skipped details (from coverage + any in run marked replayed=False)
    covered_set = set(id(c) for c in covered_cycles)
    for c in all_cycles:
        if id(c) in covered_set:
            continue
        skipped_details.append({
            "symbol": c.get("symbol", "UNKNOWN"),
            "strategy": c.get("strategy", "unknown"),
            "entry_time": str(c.get("entry_time")) if c.get("entry_time") else None,
            "exit_time": str(c.get("exit_time")) if c.get("exit_time") else None,
            "missing_ohlcv_window_reason": "no_ohlcv_in_window",
            "gap_fixable_by_re_fetch": True,
            "recorded_net": str(c.get("net_pnl_recorded", "0")),
        })

    # For analyzed (covered that replayed successfully)
    gross_res_list: List[Decimal] = []
    entry_res_list: List[Decimal] = []
    exit_res_list: List[Decimal] = []
    direction_matches: List[bool] = []
    abs_gross_res: List[Decimal] = []

    by_sym: Dict[str, Dict] = defaultdict(lambda: {
        "analyzed": 0, "skipped": 0,
        "signed_gross_res": Decimal("0"),
        "signed_entry_res_contrib": Decimal("0"),
        "signed_exit_res_contrib": Decimal("0"),
        "abs_gross_res": [], "dir_match": 0,
    })
    by_exit: Dict[str, Dict] = defaultdict(lambda: {
        "analyzed": 0, "signed_gross_res": Decimal("0"),
        "signed_entry_res_contrib": Decimal("0"),
        "signed_exit_res_contrib": Decimal("0"),
        "dir_match": 0,
    })
    timeout_only = {
        "count": 0,
        "signed_gross_res": Decimal("0"),
        "signed_entry_res_contrib": Decimal("0"),
        "signed_exit_res_contrib": Decimal("0"),
        "dir_match_count": 0,
    }

    driver_counts: Dict[str, int] = defaultdict(int)
    large_flags = 0

    replayed_count = 0
    for i, c in enumerate(covered_cycles):
        pc = zero_run.get("per_cycle", [{}])[i] if i < len(zero_run.get("per_cycle", [])) else {}
        if pc.get("replayed") is False:
            continue
        replayed_count += 1

        sym = c.get("symbol", "UNKNOWN")
        strat = c.get("strategy", "unknown")
        rec_exit = c.get("exit_reason", "unknown")
        is_timeout = _is_timeout_exit(rec_exit)

        j_g = _to_decimal(c.get("gross_pnl_recorded", "0"))
        j_f = _to_decimal(c.get("fees_recorded", "0"))
        j_n = _to_decimal(c.get("net_pnl_recorded", "0"))
        j_entry_p = _to_decimal(c.get("entry_price", "0"))
        j_exit_p = _to_decimal(c.get("exit_price", "0"))
        ntnl = _to_decimal(c.get("notional", "5"))
        et = c.get("entry_time")
        xt = c.get("exit_time")

        r_g = _to_decimal(pc.get("replayed_gross", "0"))
        r_reason = pc.get("replayed_exit_reason", "unknown")
        dir_m = pc.get("direction_match")

        r_entry_p = j_entry_p
        r_exit_p = _compute_replay_exit_price(j_entry_p, r_g, ntnl)

        entry_res = (r_entry_p - j_entry_p) if j_entry_p > 0 else Decimal("0")
        exit_res = (r_exit_p - j_exit_p) if (r_exit_p and j_exit_p > 0) else Decimal("0")
        gross_res = r_g - j_g

        # Nearest candles (independent of window subslice; use full loaded bars)
        entry_c = _find_nearest_bar(bars, et, sym)
        exit_c = _find_nearest_bar(bars, xt, sym)

        j_ent_in = _price_within_candle(j_entry_p, entry_c)
        j_exi_in = _price_within_candle(j_exit_p, exit_c)

        entry_basis = "journal exact (fill_price from journal; not derived from candle)"
        exit_basis = _classify_replay_basis(r_reason)

        driver = _classify_residual_driver(
            j_entry_p, j_exit_p, r_entry_p, r_exit_p,
            entry_c, exit_c, et, xt, r_reason, gross_res, entry_res, exit_res
        )
        driver_counts[driver] += 1

        is_large = (abs(gross_res) > Decimal("0.05")
                    or (j_entry_p > 0 and abs(entry_res) / j_entry_p > Decimal("0.005"))
                    or (j_exit_p > 0 and abs(exit_res) / j_exit_p > Decimal("0.005")))

        if is_large:
            large_flags += 1

        # qty for contrib (use journal entry for same qty model as harness)
        qty = (ntnl / j_entry_p) if j_entry_p > 0 else Decimal("0")
        entry_contrib = entry_res * qty
        exit_contrib = exit_res * qty   # gross_res should be very close to this

        gross_res_list.append(gross_res)
        entry_res_list.append(entry_res)
        exit_res_list.append(exit_res)
        abs_gross_res.append(abs(gross_res))
        if dir_m is not None:
            direction_matches.append(bool(dir_m))

        row = {
            "cycle_index": i,
            "symbol": sym,
            "strategy": strat,
            "exit_reason_journal": rec_exit,
            "entry_time": str(et) if et else None,
            "exit_time": str(xt) if xt else None,
            "journal_exit_fill_ts": c.get("raw_timestamp"),
            "journal_entry_ts_derived": str(et) if et else None,
            "journal_entry_price": str(j_entry_p) if j_entry_p else None,
            "journal_exit_price": str(j_exit_p) if j_exit_p else None,
            "replay_entry_price": str(r_entry_p) if r_entry_p else None,
            "replay_exit_price": str(r_exit_p) if r_exit_p else None,
            "nearest_candle_entry_ts": str(entry_c.t) if entry_c and hasattr(entry_c, "t") else None,
            "nearest_candle_exit_ts": str(exit_c.t) if exit_c and hasattr(exit_c, "t") else None,
            "entry_candle_ohlcv": {
                "open": str(entry_c.o), "high": str(entry_c.h), "low": str(entry_c.l),
                "close": str(entry_c.c), "volume": str(getattr(entry_c, "v", "0")),
            } if entry_c else None,
            "exit_candle_ohlcv": {
                "open": str(exit_c.o), "high": str(exit_c.h), "low": str(exit_c.l),
                "close": str(exit_c.c), "volume": str(getattr(exit_c, "v", "0")),
            } if exit_c else None,
            "entry_price_residual": str(entry_res),
            "exit_price_residual": str(exit_res),
            "gross_residual": str(gross_res),
            "residual_driver": driver,
            "journal_entry_within_candle_hl": j_ent_in,
            "journal_exit_within_candle_hl": j_exi_in,
            "replay_entry_basis": entry_basis,
            "replay_exit_basis": exit_basis,
            "is_timeout_exit": is_timeout,
            "is_large_residual": is_large,
            "direction_match_from_replay_run": dir_m,
            "notional": str(ntnl),
        }
        per_cycle_pb.append(row)

        # aggregates
        by_sym[sym]["analyzed"] += 1
        by_sym[sym]["signed_gross_res"] += gross_res
        by_sym[sym]["signed_entry_res_contrib"] += entry_contrib
        by_sym[sym]["signed_exit_res_contrib"] += exit_contrib
        by_sym[sym]["abs_gross_res"].append(abs(gross_res))
        if dir_m:
            by_sym[sym]["dir_match"] += 1

        by_exit[rec_exit]["analyzed"] += 1
        by_exit[rec_exit]["signed_gross_res"] += gross_res
        by_exit[rec_exit]["signed_entry_res_contrib"] += entry_contrib
        by_exit[rec_exit]["signed_exit_res_contrib"] += exit_contrib
        if dir_m:
            by_exit[rec_exit]["dir_match"] += 1

        if is_timeout:
            timeout_only["count"] += 1
            timeout_only["signed_gross_res"] += gross_res
            timeout_only["signed_entry_res_contrib"] += entry_contrib
            timeout_only["signed_exit_res_contrib"] += exit_contrib
            if dir_m:
                timeout_only["dir_match_count"] += 1

    analyzed = len(per_cycle_pb)

    # overall attribution
    signed_gross_total = sum(gross_res_list) if gross_res_list else Decimal("0")
    signed_entry_total = sum(entry_res_list) if entry_res_list else Decimal("0")  # usually 0
    # recompute via contribs for accuracy (qty * delta)
    signed_entry_contrib_total = sum( (Decimal(r["entry_price_residual"]) * ( _to_decimal(r.get("notional","5")) / Decimal(r.get("journal_entry_price","1")) if Decimal(r.get("journal_entry_price","0"))>0 else Decimal("0")) ) for r in per_cycle_pb ) if per_cycle_pb else Decimal("0")
    signed_exit_contrib_total = sum( (Decimal(r["exit_price_residual"]) * ( _to_decimal(r.get("notional","5")) / Decimal(r.get("journal_entry_price","1")) if Decimal(r.get("journal_entry_price","0"))>0 else Decimal("0")) ) for r in per_cycle_pb ) if per_cycle_pb else Decimal("0")
    unattrib = signed_gross_total - signed_entry_contrib_total - signed_exit_contrib_total

    dir_match = round(sum(1 for m in direction_matches if m) / len(direction_matches), 6) if direction_matches else None
    mismatch_count = sum(1 for m in direction_matches if not m) if direction_matches else 0

    # by-sym output with attribution
    by_sym_out = {}
    for k, v in sorted(by_sym.items()):
        dmatch = round(v["dir_match"] / v["analyzed"], 6) if v["analyzed"] > 0 else None
        med_abs = median([float(x) for x in v["abs_gross_res"]]) if v["abs_gross_res"] else 0.0
        by_sym_out[k] = {
            "analyzed": v["analyzed"],
            "skipped": v.get("skipped", 0),
            "direction_match": dmatch,
            "signed_gross_residual": _fmt_money(v["signed_gross_res"]),
            "signed_entry_price_residual_contrib": _fmt_money(v["signed_entry_res_contrib"]),
            "signed_exit_price_residual_contrib": _fmt_money(v["signed_exit_res_contrib"]),
            "median_abs_gross_residual": _fmt_money(Decimal(str(med_abs))),
        }

    by_exit_out = {}
    for k, v in sorted(by_exit.items()):
        dmatch = round(v["dir_match"] / v["analyzed"], 6) if v["analyzed"] > 0 else None
        by_exit_out[k] = {
            "analyzed": v["analyzed"],
            "direction_match": dmatch,
            "signed_gross_residual": _fmt_money(v["signed_gross_res"]),
            "signed_entry_price_residual_contrib": _fmt_money(v["signed_entry_res_contrib"]),
            "signed_exit_price_residual_contrib": _fmt_money(v["signed_exit_res_contrib"]),
        }

    timeout_out = {
        "count": timeout_only["count"],
        "share_of_analyzed": round(timeout_only["count"] / analyzed, 6) if analyzed > 0 else 0.0,
        "signed_gross_residual": _fmt_money(timeout_only["signed_gross_res"]),
        "signed_entry_price_residual_contrib": _fmt_money(timeout_only["signed_entry_res_contrib"]),
        "signed_exit_price_residual_contrib": _fmt_money(timeout_only["signed_exit_res_contrib"]),
        "direction_match": round(timeout_only["dir_match_count"] / timeout_only["count"], 6) if timeout_only["count"] > 0 else None,
    }

    # top lists (worst first for residuals; mismatches)
    def _abs_key(r):
        try:
            return abs(Decimal(r.get("gross_residual", "0")))
        except Exception:
            return Decimal("0")

    worst_sorted = sorted(per_cycle_pb, key=_abs_key, reverse=True)
    top_worst = worst_sorted[:top_n]

    mismatch_rows = [r for r in per_cycle_pb if r.get("direction_match_from_replay_run") is False]
    top_mismatches = mismatch_rows[:top_n]

    # dominant driver
    if driver_counts:
        dominant_driver = max(driver_counts.items(), key=lambda x: x[1])[0]
    else:
        dominant_driver = "unknown"
    # also check if timeout dominates the residual magnitude
    if timeout_only["count"] > 0 and abs(timeout_only["signed_gross_res"]) > abs(signed_gross_total) * Decimal("0.5"):
        dominant_driver = "timeout_exit_basis_issue (close-vs-fill on max-hold exits)"

    # most residual appears ...
    entry_mag = abs(signed_entry_contrib_total)
    exit_mag = abs(signed_exit_contrib_total)
    if exit_mag > entry_mag * Decimal("2"):
        residual_appears = "exit-driven (primarily timeout close-vs-fill vs journal exit fills)"
    elif entry_mag > exit_mag * Decimal("2"):
        residual_appears = "entry-driven"
    elif timeout_only["count"] > (analyzed * 0.7 if analyzed else 0):
        residual_appears = "timeout-driven (close-vs-fill amplified by max-hold dominance)"
    else:
        residual_appears = "unknown / mixed"

    # journal prices within candle ranges overall
    within_entry = sum(1 for r in per_cycle_pb if r.get("journal_entry_within_candle_hl"))
    within_exit = sum(1 for r in per_cycle_pb if r.get("journal_exit_within_candle_hl"))
    within_entry_rate = round(within_entry / analyzed, 6) if analyzed > 0 else None
    within_exit_rate = round(within_exit / analyzed, 6) if analyzed > 0 else None

    # replay basis summary (count of types)
    replay_entry_basis_counts: Dict[str, int] = defaultdict(int)
    replay_exit_basis_counts: Dict[str, int] = defaultdict(int)
    for r in per_cycle_pb:
        replay_entry_basis_counts[r.get("replay_entry_basis", "unknown")] += 1
        replay_exit_basis_counts[r.get("replay_exit_basis", "unknown")] += 1

    # replay_trustworthy remains false unless gates (we do not re-eval full gates here; fidelity is source of truth)
    # but report current status for context
    replay_trustworthy = False  # per 025M; price basis explains why

    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "report_class": "replay_price_basis_reconciliation",
        "journal_path": str(jpath),
        "ohlcv_fixture": str(ohlcv_fixture) if ohlcv_fixture else None,
        "cycles_seen": total_seen,
        "cycles_analyzed": analyzed,
        "cycles_skipped": without_c,
        "coverage_rate": cov_rate,
        "skip_reason_breakdown": skip_break,
        "skipped_cycle_details": skipped_details,
        "required_symbols": sorted(list(set(_normalize_symbol(c.get("symbol", "")) for c in all_cycles if c.get("symbol")))),
        "trade_permission": "none",
        "risk_increase": "not_approved",
        "scaling_allowed": False,
        "notes": [
            "Offline price/fill-basis reconciliation. Entry in replay uses journal fill_price exactly (by harness design).",
            "Exit in replay derived from window bars (high/low for TP/SL, close+slip for timeout/max_hold).",
            "Residual attribution uses qty * price_delta for entry vs exit contributions to gross P/L diff.",
            "Candle high/low containment checks whether journal recorded fills were inside the nearest 5m bar range.",
            "Timeout exits (~98% in baseline) amplify any close-vs-fill mismatch between replay simulation and broker fills.",
            "replay_trustworthy remains false (per P2-025M gates) until entry/exit basis reconciled and gates pass.",
        ],
        "per_cycle": per_cycle_pb,
        "mismatch_cycles_first": [r for r in per_cycle_pb if r.get("direction_match_from_replay_run") is False][:max(20, top_n)],
        "residual_attribution": {
            "signed_gross_residual": _fmt_money(signed_gross_total),
            "attributed_to_entry_price": _fmt_money(signed_entry_contrib_total),
            "attributed_to_exit_price": _fmt_money(signed_exit_contrib_total),
            "unattributed_or_unknown": _fmt_money(unattrib),
            "residual_appears_mostly": residual_appears,
        },
        "direction_fidelity": {
            "direction_match": dir_match,
            "mismatch_count": mismatch_count,
        },
        "by_symbol": by_sym_out,
        "by_exit_reason": by_exit_out,
        "timeout_specific": timeout_out,
        "top_worst_residual_cycles": top_worst,
        "top_direction_mismatches": top_mismatches,
        "driver_classification": {
            "counts": dict(driver_counts),
            "dominant": dominant_driver,
        },
        "candle_containment": {
            "journal_entry_within_hl_count": within_entry,
            "journal_entry_within_hl_rate": within_entry_rate,
            "journal_exit_within_hl_count": within_exit,
            "journal_exit_within_hl_rate": within_exit_rate,
            "note": "True means journal fill price fell inside nearest candle [low,high]. False may indicate fill at different micro-price, different bar, or data granularity mismatch.",
        },
        "replay_basis_summary": {
            "entry_basis_counts": dict(replay_entry_basis_counts),
            "exit_basis_counts": dict(replay_exit_basis_counts),
            "note": "Entry is always journal exact (harness design). Exit basis inferred from replayed exit_reason (close for timeout, high/low for tp/sl).",
        },
        "large_residual_flags": large_flags,
        "replay_trustworthy": replay_trustworthy,
        "replay_trustworthy_note": "Verdict and gates from P2-025M fidelity report remain authoritative. This report isolates the price basis drivers of the observed residual.",
        "senior_consultant_note": "P2-025M failed gates (dir<0.85, abs net res >$0.10). Do not proceed to maker/post-only or exit tuning until price-basis residual is closed (e.g. via better bar granularity, fill timestamp alignment, or explicit close-vs-fill model) and fidelity gates pass on re-run.",
    }

    # top level convenience (context only; detailed attribution is authoritative)
    try:
        jg = sum(Decimal(r.get("journal_gross", "0")) for r in per_cycle_pb) if per_cycle_pb else Decimal("0")
        payload["journal_analyzed_gross"] = _fmt_money(jg)
    except Exception:
        payload["journal_analyzed_gross"] = None
    try:
        payload["replay_gross_pnl_sum"] = zero_run.get("gross_pnl_sum")
    except Exception:
        pass

    payload["trade_permission"] = "none"
    payload["risk_increase"] = "not_approved"
    payload["scaling_allowed"] = False

    return payload


def _human_summary(payload: Dict[str, Any], top_n: int = 10) -> str:
    lines = []
    lines.append("=== REPLAY PRICE-BASIS / FILL-BASIS RECONCILIATION (P2-025N) ===")
    lines.append(f"Journal: {payload.get('journal_path')}")
    lines.append(f"Coverage: seen={payload['cycles_seen']} analyzed={payload['cycles_analyzed']} skipped={payload['cycles_skipped']} rate={payload['coverage_rate']}")
    lines.append(f"Skip breakdown: {payload.get('skip_reason_breakdown')}")
    lines.append("")
    lines.append("Skipped cycle details (gaps do not block analysis of covered cycles):")
    for s in payload.get("skipped_cycle_details", [])[:5]:
        lines.append(f"  {s['symbol']} entry={s['entry_time']} exit={s['exit_time']} reason={s['missing_ohlcv_window_reason']}")
    if len(payload.get("skipped_cycle_details", [])) > 5:
        lines.append("  ...")
    lines.append("")
    ra = payload.get("residual_attribution", {})
    lines.append("Residual attribution (gross):")
    lines.append(f"  signed_gross={ra.get('signed_gross_residual')} entry_attrib={ra.get('attributed_to_entry_price')} exit_attrib={ra.get('attributed_to_exit_price')} unattrib={ra.get('unattributed_or_unknown')}")
    lines.append(f"  residual_appears_mostly: {ra.get('residual_appears_mostly')}")
    lines.append("")
    df = payload.get("direction_fidelity", {})
    lines.append(f"Direction: match={df.get('direction_match')} mismatch_count={df.get('mismatch_count')}")
    lines.append("")
    lines.append("By symbol (analyzed, dir_match, signed_gross, entry_contrib, exit_contrib):")
    for k, v in payload.get("by_symbol", {}).items():
        lines.append(f"  {k}: analyzed={v['analyzed']} match={v['direction_match']} gross_res={v['signed_gross_residual']} entry_c={v.get('signed_entry_price_residual_contrib')} exit_c={v.get('signed_exit_price_residual_contrib')}")
    lines.append("")
    lines.append("By exit reason (analyzed, dir_match, signed_gross, entry_c, exit_c):")
    for k, v in payload.get("by_exit_reason", {}).items():
        lines.append(f"  {k}: analyzed={v['analyzed']} match={v['direction_match']} gross={v['signed_gross_residual']} entry_c={v.get('signed_entry_price_residual_contrib')} exit_c={v.get('signed_exit_price_residual_contrib')}")
    lines.append("")
    to = payload.get("timeout_specific", {})
    lines.append(f"Timeout-specific: count={to.get('count')} share={to.get('share_of_analyzed')} gross_res={to.get('signed_gross_residual')} entry_c={to.get('signed_entry_price_residual_contrib')} exit_c={to.get('signed_exit_price_residual_contrib')} dir_match={to.get('direction_match')}")
    lines.append("")
    lines.append(f"Large residual cycles flagged (abs gross>$0.05 or >0.5% entry/exit price res): {payload.get('large_residual_flags')}")
    lines.append("")
    dc = payload.get("driver_classification", {})
    lines.append(f"Driver counts: {dc.get('counts')}")
    lines.append(f"Dominant driver: {dc.get('dominant')}")
    lines.append("")
    cc = payload.get("candle_containment", {})
    lines.append("Candle high/low containment (journal fills vs nearest candle):")
    lines.append(f"  entry_within_hl: {cc.get('journal_entry_within_hl_count')}/{payload['cycles_analyzed']} rate={cc.get('journal_entry_within_hl_rate')}")
    lines.append(f"  exit_within_hl: {cc.get('journal_exit_within_hl_count')}/{payload['cycles_analyzed']} rate={cc.get('journal_exit_within_hl_rate')}")
    lines.append(f"  note: {cc.get('note')}")
    lines.append("")
    bs = payload.get("replay_basis_summary", {})
    lines.append(f"Replay basis (entry always journal exact): entry={bs.get('entry_basis_counts')}")
    lines.append(f"Replay exit basis counts: {bs.get('exit_basis_counts')}")
    lines.append("")
    lines.append("Top worst residual cycles (by |gross_residual|):")
    for r in payload.get("top_worst_residual_cycles", [])[:top_n]:
        lines.append(f"  [{r.get('cycle_index')}] {r.get('symbol')} gross_res={r.get('gross_residual')} driver={r.get('residual_driver')} timeout={r.get('is_timeout_exit')} entry_res={r.get('entry_price_residual')} exit_res={r.get('exit_price_residual')} journal_entry_in_hl={r.get('journal_entry_within_candle_hl')} journal_exit_in_hl={r.get('journal_exit_within_candle_hl')}")
    lines.append("")
    lines.append("Top direction mismatches (first N):")
    for r in payload.get("top_direction_mismatches", [])[:top_n]:
        lines.append(f"  [{r.get('cycle_index')}] {r.get('symbol')} dir_match={r.get('direction_match_from_replay_run')} gross_res={r.get('gross_residual')} driver={r.get('residual_driver')}")
    lines.append("")
    lines.append(f"replay_trustworthy: {payload.get('replay_trustworthy')} (see P2-025M gates; remains false)")
    lines.append(f"  note: {payload.get('replay_trustworthy_note')}")
    lines.append("")
    lines.append("Safety: trade_permission=none, risk_increase=not_approved, scaling_allowed=false")
    lines.append("This is offline diagnostic only. Does not authorize live trading, sizing, maker studies, or exit changes.")
    lines.append("=== END REPORT ===")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Replay price-basis / fill-basis reconciliation (P2-025N, offline only)")
    ap.add_argument("--json", action="store_true", help="Emit JSON")
    ap.add_argument("--journal", type=Path, default=None)
    ap.add_argument("--ohlcv-fixture", type=Path, default=None)
    ap.add_argument("--max-cycles", type=int, default=None)
    ap.add_argument("--top-n", type=int, default=10, help="Limit for top lists (default 10)")
    ap.add_argument("--output", type=Path, default=None, help="Optional write path for JSON (no write by default)")
    args = ap.parse_args(argv)

    payload = build_replay_price_basis_report(
        journal_path=args.journal,
        ohlcv_fixture=args.ohlcv_fixture,
        max_cycles=args.max_cycles,
        top_n=args.top_n,
    )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if args.json:
        json.dump(payload, sys.stdout, indent=2)
        print()
    else:
        print(_human_summary(payload, top_n=args.top_n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
