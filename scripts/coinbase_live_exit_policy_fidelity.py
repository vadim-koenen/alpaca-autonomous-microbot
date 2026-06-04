#!/usr/bin/env python3
"""
scripts/coinbase_live_exit_policy_fidelity.py — P2-025O Live Exit-Policy Fidelity / Journal-Exit-Aligned Replay Mode.

Offline-only comparison of current simulated replay (TP/SL/high-low/close + slip) vs journal-exit-aligned mode
that uses the actual journal exit timestamp/reason/price (for timeout/max-hold) or nearest candle close fallback.

Purpose: measure whether aligning replay exit basis to live journal exit policy reconciles replay gross/net
to journal-recorded reality. Instrumentation/diagnostic only. No changes to existing replay or live exit logic.

Reuses: parse_journal_cycles, run_journal_window_replay (zero-fee for simulated), load_bars_from_fixture,
_compute_coverage_and_covered, _load_bars_for_journal, _to_decimal, _fmt_money, _normalize_symbol,
and helpers from price_basis (no dup parsing, no modification of existing replay behavior).

Pure offline. No broker, no orders, no mutation, no .env, no secrets, no live, no network.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
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

# Reuse helpers from price-basis (no reimplementation, no changes to replay)
from scripts.coinbase_replay_price_basis_reconciliation import (
    _find_nearest_bar,
    _is_timeout_exit,
    _price_within_candle,
)

# For consistency with simulated exit inference (not used for aligned)
from scripts.coinbase_replay_fidelity_reconciliation import (
    _compute_replay_exit_price,
)

SCHEMA_VERSION = "p2-025o.coinbase_live_exit_policy_fidelity.v1"
DEFAULT_JOURNAL = ROOT / "journal_coinbase_crypto.csv"
DATA_DIR = ROOT / "data" / "offline_ohlcv" / "coinbase"


def _compute_gross_from_prices(entry_p: Decimal, exit_p: Decimal, notional: Decimal) -> Decimal:
    if entry_p <= 0 or notional <= 0:
        return Decimal("0")
    qty = notional / entry_p
    return (exit_p - entry_p) * qty


def build_live_exit_policy_fidelity_report(
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

    # Simulated: zero-fee run using current TP/SL/timeout simulation (existing behavior, unmodified)
    zero_run = run_journal_window_replay(
        bars, covered_cycles, entry_fee_rate=Decimal("0"), exit_fee_rate=Decimal("0"), fee_scenario="zero_fee"
    )

    per_cycle: List[Dict[str, Any]] = []
    skipped_details: List[Dict[str, Any]] = []

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

    simulated_gross_res: List[Decimal] = []
    aligned_gross_res: List[Decimal] = []
    simulated_net_res_jf: List[Decimal] = []
    aligned_net_res_jf: List[Decimal] = []
    simulated_dir_matches: List[bool] = []
    aligned_dir_matches: List[bool] = []
    abs_sim_res: List[Decimal] = []
    abs_ali_res: List[Decimal] = []
    pct_of_notional_sim: List[Decimal] = []
    pct_of_notional_ali: List[Decimal] = []

    by_sym_sim: Dict[str, Dict] = defaultdict(lambda: {"analyzed": 0, "signed_gross_res": Decimal("0"), "dir_match": 0, "abs_res": []})
    by_sym_ali: Dict[str, Dict] = defaultdict(lambda: {"analyzed": 0, "signed_gross_res": Decimal("0"), "dir_match": 0, "abs_res": []})

    by_exit_sim: Dict[str, Dict] = defaultdict(lambda: {"analyzed": 0, "signed_gross_res": Decimal("0"), "dir_match": 0})
    by_exit_ali: Dict[str, Dict] = defaultdict(lambda: {"analyzed": 0, "signed_gross_res": Decimal("0"), "dir_match": 0})

    timeout_sim_res = Decimal("0")
    timeout_ali_res = Decimal("0")
    timeout_count = 0
    timeout_sim_dir = 0
    timeout_ali_dir = 0

    simulated_large = 0
    aligned_large = 0

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

        # Simulated (from existing zero-fee run, unmodified behavior)
        r_g = _to_decimal(pc.get("replayed_gross", "0"))
        r_reason = pc.get("replayed_exit_reason", "unknown")
        dir_m_sim = pc.get("direction_match")

        r_entry_p = j_entry_p
        r_exit_p = _compute_replay_exit_price(j_entry_p, r_g, ntnl) if r_g is not None else None

        gross_res_sim = r_g - j_g
        simulated_gross_res.append(gross_res_sim)
        abs_sim_res.append(abs(gross_res_sim))
        net_res_sim = (r_g - j_f) - j_n
        simulated_net_res_jf.append(net_res_sim)
        if ntnl > 0:
            pct_of_notional_sim.append(abs(gross_res_sim) / ntnl)
        if dir_m_sim is not None:
            simulated_dir_matches.append(bool(dir_m_sim))

        # Aligned: use journal exit price/reason when present (for timeout/max-hold or any with exit_price)
        # If journal exit_price missing/zero, fallback to nearest candle close at journal exit ts
        if j_exit_p > 0:
            ali_exit_p = j_exit_p
            ali_reason = rec_exit
            used_journal_exit_price = True
            fallback_note = None
        else:
            exit_c = _find_nearest_bar(bars, xt, sym)
            ali_exit_p = exit_c.c if exit_c and exit_c.c > 0 else j_entry_p
            ali_reason = (rec_exit or "unknown") + " (nearest candle close fallback)"
            used_journal_exit_price = False
            fallback_note = "candle_close_fallback"

        ali_g = _compute_gross_from_prices(j_entry_p, ali_exit_p, ntnl)
        gross_res_ali = ali_g - j_g
        aligned_gross_res.append(gross_res_ali)
        abs_ali_res.append(abs(gross_res_ali))
        net_res_ali = (ali_g - j_f) - j_n
        aligned_net_res_jf.append(net_res_ali)
        if ntnl > 0:
            pct_of_notional_ali.append(abs(gross_res_ali) / ntnl)

        # Aligned direction: compute analogous to simulated (use aligned gross sign vs journal gross for sign_match,
        # and for "direction_match" use aligned_net = ali_g - j_f vs rec net sign, matching run logic)
        sign_match_ali = None
        if j_g != 0 or ali_g != 0:
            sign_match_ali = (ali_g > 0) == (j_g > 0)

        ali_net_with_j_fees = ali_g - j_f
        dir_m_ali = (ali_net_with_j_fees > 0) == (j_n > 0) if (j_n != 0 or ali_net_with_j_fees != 0) else None
        if dir_m_ali is not None:
            aligned_dir_matches.append(bool(dir_m_ali))

        # large flags
        if abs(gross_res_sim) > Decimal("0.05") or (ntnl > 0 and abs(gross_res_sim) / ntnl > Decimal("0.10")):
            simulated_large += 1
        if abs(gross_res_ali) > Decimal("0.05") or (ntnl > 0 and abs(gross_res_ali) / ntnl > Decimal("0.10")):
            aligned_large += 1

        # by sym
        by_sym_sim[sym]["analyzed"] += 1
        by_sym_sim[sym]["signed_gross_res"] += gross_res_sim
        by_sym_sim[sym]["abs_res"].append(abs(gross_res_sim))
        if dir_m_sim:
            by_sym_sim[sym]["dir_match"] += 1

        by_sym_ali[sym]["analyzed"] += 1
        by_sym_ali[sym]["signed_gross_res"] += gross_res_ali
        by_sym_ali[sym]["abs_res"].append(abs(gross_res_ali))
        if dir_m_ali:
            by_sym_ali[sym]["dir_match"] += 1

        # by exit (journal reason)
        by_exit_sim[rec_exit]["analyzed"] += 1
        by_exit_sim[rec_exit]["signed_gross_res"] += gross_res_sim
        if dir_m_sim:
            by_exit_sim[rec_exit]["dir_match"] += 1

        by_exit_ali[rec_exit]["analyzed"] += 1
        by_exit_ali[rec_exit]["signed_gross_res"] += gross_res_ali
        if dir_m_ali:
            by_exit_ali[rec_exit]["dir_match"] += 1

        # timeout specific
        if is_timeout:
            timeout_count += 1
            timeout_sim_res += gross_res_sim
            timeout_ali_res += gross_res_ali
            if dir_m_sim:
                timeout_sim_dir += 1
            if dir_m_ali:
                timeout_ali_dir += 1

        row = {
            "symbol": sym,
            "strategy": strat,
            "journal_exit_reason": rec_exit,
            "simulated_replay_exit_reason": r_reason,
            "journal_entry_price": str(j_entry_p) if j_entry_p else None,
            "journal_exit_price": str(j_exit_p) if j_exit_p else None,
            "simulated_replay_exit_price": str(r_exit_p) if r_exit_p else None,
            "aligned_replay_exit_price": str(ali_exit_p) if ali_exit_p else None,
            "journal_gross": str(j_g),
            "simulated_replay_gross": str(r_g),
            "aligned_replay_gross": str(ali_g),
            "simulated_gross_residual": str(gross_res_sim),
            "aligned_gross_residual": str(gross_res_ali),
            "simulated_direction_match": dir_m_sim,
            "aligned_direction_match": dir_m_ali,
            "aligned_used_journal_exit_price": used_journal_exit_price,
            "aligned_fallback_note": fallback_note,
            "journal_exit_within_candle_hl": _price_within_candle(j_exit_p, _find_nearest_bar(bars, xt, sym)) if j_exit_p > 0 else None,
            "is_timeout_exit": is_timeout,
            "notional": str(ntnl),
            "residual_improved": ("improved" if abs(gross_res_ali) < abs(gross_res_sim) else ("worsened" if abs(gross_res_ali) > abs(gross_res_sim) else "unchanged")),
        }
        per_cycle.append(row)

    analyzed = len(per_cycle)

    # Aggregates
    sim_signed = sum(simulated_gross_res) if simulated_gross_res else Decimal("0")
    ali_signed = sum(aligned_gross_res) if aligned_gross_res else Decimal("0")
    sim_net_signed = sum(simulated_net_res_jf) if simulated_net_res_jf else Decimal("0")
    ali_net_signed = sum(aligned_net_res_jf) if aligned_net_res_jf else Decimal("0")
    sim_med_abs = median([float(x) for x in abs_sim_res]) if abs_sim_res else 0.0
    ali_med_abs = median([float(x) for x in abs_ali_res]) if abs_ali_res else 0.0
    sim_p90 = sorted([float(x) for x in abs_sim_res])[int(0.9 * (len(abs_sim_res)-1))] if len(abs_sim_res) > 1 else (float(abs_sim_res[0]) if abs_sim_res else 0.0)
    ali_p90 = sorted([float(x) for x in abs_ali_res])[int(0.9 * (len(abs_ali_res)-1))] if len(abs_ali_res) > 1 else (float(abs_ali_res[0]) if abs_ali_res else 0.0)
    sim_med_pct = median([float(x) for x in pct_of_notional_sim]) if pct_of_notional_sim else None
    ali_med_pct = median([float(x) for x in pct_of_notional_ali]) if pct_of_notional_ali else None

    sim_dir = round(sum(1 for m in simulated_dir_matches if m) / len(simulated_dir_matches), 6) if simulated_dir_matches else None
    ali_dir = round(sum(1 for m in aligned_dir_matches if m) / len(aligned_dir_matches), 6) if aligned_dir_matches else None
    dir_delta = (ali_dir - sim_dir) if (ali_dir is not None and sim_dir is not None) else None

    res_red_abs = abs(sim_signed) - abs(ali_signed)
    res_red_pct = (float(res_red_abs) / float(abs(sim_signed))) if abs(sim_signed) > 0 else None

    # by-sym output
    by_sym_out = {}
    for k in set(list(by_sym_sim.keys()) + list(by_sym_ali.keys())):
        vs = by_sym_sim.get(k, {"analyzed":0, "signed_gross_res":Decimal("0"), "dir_match":0, "abs_res":[]})
        va = by_sym_ali.get(k, {"analyzed":0, "signed_gross_res":Decimal("0"), "dir_match":0, "abs_res":[]})
        dsim = round(vs["dir_match"] / vs["analyzed"], 6) if vs["analyzed"] > 0 else None
        dali = round(va["dir_match"] / va["analyzed"], 6) if va["analyzed"] > 0 else None
        by_sym_out[k] = {
            "analyzed": vs["analyzed"],
            "simulated_direction_match": dsim,
            "aligned_direction_match": dali,
            "simulated_signed_gross_residual": _fmt_money(vs["signed_gross_res"]),
            "aligned_signed_gross_residual": _fmt_money(va["signed_gross_res"]),
            "simulated_median_abs": _fmt_money(Decimal(str(median([float(x) for x in vs["abs_res"]]) if vs["abs_res"] else 0))),
            "aligned_median_abs": _fmt_money(Decimal(str(median([float(x) for x in va["abs_res"]]) if va["abs_res"] else 0))),
        }

    # by-exit
    by_exit_out = {}
    for k in set(list(by_exit_sim.keys()) + list(by_exit_ali.keys())):
        vs = by_exit_sim.get(k, {"analyzed":0,"signed_gross_res":Decimal("0"),"dir_match":0})
        va = by_exit_ali.get(k, {"analyzed":0,"signed_gross_res":Decimal("0"),"dir_match":0})
        dsim = round(vs["dir_match"] / vs["analyzed"], 6) if vs["analyzed"] > 0 else None
        dali = round(va["dir_match"] / va["analyzed"], 6) if va["analyzed"] > 0 else None
        by_exit_out[k] = {
            "analyzed": vs["analyzed"],
            "simulated_direction_match": dsim,
            "aligned_direction_match": dali,
            "simulated_signed_gross_residual": _fmt_money(vs["signed_gross_res"]),
            "aligned_signed_gross_residual": _fmt_money(va["signed_gross_res"]),
        }

    # timeout
    timeout_sim_dir_match = round(timeout_sim_dir / timeout_count, 6) if timeout_count > 0 else None
    timeout_ali_dir_match = round(timeout_ali_dir / timeout_count, 6) if timeout_count > 0 else None

    # Trust gates (conservative, same as P2-025M)
    def _eval_trustworthy(dir_m, signed_net_res, med_abs_pct, analyzed_n):
        trustworthy = True
        failed = []
        if dir_m is None or dir_m < 0.85:
            trustworthy = False
            failed.append(f"direction_match < 0.85 (got {dir_m})")
        if abs(signed_net_res) > Decimal("0.10"):
            trustworthy = False
            failed.append(f"abs(signed total net residual using journal fees) > 0.10 (got {_fmt_money(signed_net_res)})")
        if med_abs_pct is not None:
            if med_abs_pct > 0.10:
                trustworthy = False
                failed.append(f"median abs residual > 10% of notional (got {round(med_abs_pct,6)})")
        else:
            # not calculable -> conservative
            if analyzed_n > 0:
                # if we cannot compute med % , still allow if other gates pass; but doc as unavailable
                pass
        return trustworthy, failed

    sim_dir_for_gate = sim_dir
    ali_dir_for_gate = ali_dir

    sim_trust, sim_failed = _eval_trustworthy(sim_dir_for_gate, sim_net_signed, sim_med_pct, analyzed)
    ali_trust, ali_failed = _eval_trustworthy(ali_dir_for_gate, ali_net_signed, ali_med_pct, analyzed)

    # improvement
    exit_policy_fixes = (abs(ali_signed) < abs(sim_signed) * Decimal("0.1")) or (ali_dir_for_gate is not None and ali_dir_for_gate >= 0.85 and abs(ali_signed) <= Decimal("0.10"))

    payload = {
        "schema_version": SCHEMA_VERSION,
        "report_class": "live_exit_policy_fidelity",
        "journal_path": str(jpath),
        "ohlcv_fixture": str(ohlcv_fixture) if ohlcv_fixture else None,
        "cycles_seen": total_seen,
        "cycles_analyzed": analyzed,
        "cycles_skipped": without_c,
        "coverage_rate": cov_rate,
        "skip_reason_breakdown": skip_break,
        "skipped_cycle_details": skipped_details,
        "trade_permission": "none",
        "risk_increase": "not_approved",
        "scaling_allowed": False,
        "notes": [
            "Offline live-exit-policy fidelity. Compares simulated replay (current TP/SL/timeout simulation) vs journal-exit-aligned mode.",
            "Aligned mode uses journal exit_price + exit_reason for max-hold/timeout (and other) cycles when present; nearest candle close fallback otherwise.",
            "Existing replay behavior is never modified; aligned is computed from journal data + simple P/L math.",
            "When journal exit price is used, aligned gross == journal gross (residual 0) by construction.",
        ],
        "per_cycle": per_cycle,
        "simulated": {
            "direction_match": sim_dir,
            "signed_gross_residual": _fmt_money(sim_signed),
            "median_abs_gross_residual": _fmt_money(Decimal(str(sim_med_abs))),
            "p90_abs_gross_residual": _fmt_money(Decimal(str(sim_p90))),
            "median_abs_residual_pct_of_notional": str(sim_med_pct) if sim_med_pct is not None else None,
            "large_flags": simulated_large,
            "replay_trustworthy": sim_trust,
            "failed_trust_gates": sim_failed,
        },
        "aligned": {
            "direction_match": ali_dir,
            "signed_gross_residual": _fmt_money(ali_signed),
            "median_abs_gross_residual": _fmt_money(Decimal(str(ali_med_abs))),
            "p90_abs_gross_residual": _fmt_money(Decimal(str(ali_p90))),
            "median_abs_residual_pct_of_notional": str(ali_med_pct) if ali_med_pct is not None else None,
            "large_flags": aligned_large,
            "replay_trustworthy": ali_trust,
            "failed_trust_gates": ali_failed,
        },
        "improvement": {
            "direction_match_delta": dir_delta,
            "residual_reduction_abs": _fmt_money(res_red_abs),
            "residual_reduction_pct": round(res_red_pct, 6) if res_red_pct is not None else None,
            "exit_policy_alignment_fixes_residual": exit_policy_fixes,
        },
        "timeout_specific": {
            "count": timeout_count,
            "simulated_signed_gross_residual": _fmt_money(timeout_sim_res),
            "aligned_signed_gross_residual": _fmt_money(timeout_ali_res),
            "simulated_direction_match": timeout_sim_dir_match,
            "aligned_direction_match": timeout_ali_dir_match,
        },
        "by_symbol": by_sym_out,
        "by_exit_reason": by_exit_out,
        "remaining_blockers": [
            "Gaps (ADA/ETH) still present for full coverage.",
            "Even with alignment, direction under fees and real notional variation may still show issues if not all cycles use journal exit price.",
            "Live exit policy (heavy timeout) itself may be the root economic driver even if replay now matches realized prices.",
        ],
    }

    payload["trade_permission"] = "none"
    payload["risk_increase"] = "not_approved"
    payload["scaling_allowed"] = False

    return payload


def _human_summary(payload: Dict[str, Any], top_n: int = 10) -> str:
    lines = []
    lines.append("=== LIVE EXIT-POLICY FIDELITY (P2-025O) ===")
    lines.append(f"Journal: {payload.get('journal_path')}")
    lines.append(f"Coverage: seen={payload['cycles_seen']} analyzed={payload['cycles_analyzed']} skipped={payload['cycles_skipped']} rate={payload['coverage_rate']}")
    lines.append("")
    sim = payload.get("simulated", {})
    ali = payload.get("aligned", {})
    imp = payload.get("improvement", {})
    lines.append("Simulated (current TP/SL/timeout-close replay):")
    lines.append(f"  direction_match={sim.get('direction_match')} signed_gross_res={sim.get('signed_gross_residual')} med_abs={sim.get('median_abs_gross_residual')} p90={sim.get('p90_abs_gross_residual')}")
    lines.append(f"  replay_trustworthy={sim.get('replay_trustworthy')} failed={sim.get('failed_trust_gates')}")
    lines.append("")
    lines.append("Aligned (journal-exit-price for timeout + candle fallback):")
    lines.append(f"  direction_match={ali.get('direction_match')} signed_gross_res={ali.get('signed_gross_residual')} med_abs={ali.get('median_abs_gross_residual')} p90={ali.get('p90_abs_gross_residual')}")
    lines.append(f"  replay_trustworthy={ali.get('replay_trustworthy')} failed={ali.get('failed_trust_gates')}")
    lines.append("")
    lines.append(f"Improvement: dir_delta={imp.get('direction_match_delta')} res_red_abs={imp.get('residual_reduction_abs')} res_red_pct={imp.get('residual_reduction_pct')}")
    lines.append(f"exit_policy_alignment_fixes_residual: {imp.get('exit_policy_alignment_fixes_residual')}")
    lines.append("")
    to = payload.get("timeout_specific", {})
    lines.append(f"Timeout-specific: count={to.get('count')} sim_res={to.get('simulated_signed_gross_residual')} ali_res={to.get('aligned_signed_gross_residual')} sim_dir={to.get('simulated_direction_match')} ali_dir={to.get('aligned_direction_match')}")
    lines.append("")
    lines.append("By symbol (sim/ali dir_match, signed_gross):")
    for k, v in payload.get("by_symbol", {}).items():
        lines.append(f"  {k}: sim_dir={v.get('simulated_direction_match')} ali_dir={v.get('aligned_direction_match')} sim_res={v.get('simulated_signed_gross_residual')} ali_res={v.get('aligned_signed_gross_residual')}")
    lines.append("")
    lines.append("Safety: trade_permission=none, risk_increase=not_approved, scaling_allowed=false")
    lines.append("Offline diagnostic only. Existing replay behavior unmodified.")
    lines.append("=== END REPORT ===")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Live exit-policy fidelity / journal-exit-aligned replay (P2-025O, offline only)")
    ap.add_argument("--json", action="store_true", help="Emit JSON")
    ap.add_argument("--journal", type=Path, default=None)
    ap.add_argument("--ohlcv-fixture", type=Path, default=None)
    ap.add_argument("--max-cycles", type=int, default=None)
    ap.add_argument("--top-n", type=int, default=10, help="Limit for top lists")
    ap.add_argument("--output", type=Path, default=None, help="Optional write path for JSON (no write by default)")
    args = ap.parse_args(argv)

    payload = build_live_exit_policy_fidelity_report(
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
