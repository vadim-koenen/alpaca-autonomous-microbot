#!/usr/bin/env python3
"""
scripts/coinbase_replay_fidelity_reconciliation.py — P2-025M Replay Fidelity Reconciliation.

Offline-only reconciliation of replay-derived gross and (journal-fees) net vs journal-recorded
values per cycle. Produces per-cycle residual details, distributions, by-sym/strat/exit,
timeout-specific, and a conservative replay_trustworthy true/false verdict.

Purpose: determine whether the replay harness is faithful enough to the realized journal
outcomes before any maker/post-only, exit tuning, or scaling decisions. Senior consultant
review of P2-025L identified that direction_match=0.5 and net residual ~$1.34 mean the
replay may be manufacturing the apparent gross edge; this report quantifies it.

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

SCHEMA_VERSION = "p2-025m.coinbase_replay_fidelity_reconciliation.v1"
DEFAULT_JOURNAL = ROOT / "journal_coinbase_crypto.csv"
DATA_DIR = ROOT / "data" / "offline_ohlcv" / "coinbase"


def _compute_replay_exit_price(journal_entry_p: Decimal, replay_gross: Decimal, notional: Decimal) -> Optional[Decimal]:
    if notional <= 0 or journal_entry_p <= 0:
        return None
    qty = notional / journal_entry_p
    if qty <= 0:
        return None
    return journal_entry_p + (replay_gross / qty)


def _infer_replay_exit_basis(replayed_exit_reason: str) -> str:
    r = (replayed_exit_reason or "").lower()
    if "max_hold" in r or "max hold" in r or "timeout" in r:
        return "candle close + adverse slippage (max_hold)"
    if "stop_loss" in r or "sl" in r:
        return "bar low + adverse slippage (stop_loss)"
    if "take_profit" in r or "tp" in r:
        return "bar high + adverse slippage (take_profit)"
    if "end_of_data" in r:
        return "last candle close + adverse slippage (end_of_data)"
    return "inferred from simulate (high/low/close + slippage)"


def build_replay_fidelity_report(
    *,
    journal_path: Optional[Path] = None,
    ohlcv_fixture: Optional[Path] = None,
    max_cycles: Optional[int] = None,
) -> Dict[str, Any]:
    jpath = Path(journal_path) if journal_path else DEFAULT_JOURNAL
    all_cycles = parse_journal_cycles(jpath)
    if max_cycles:
        all_cycles = all_cycles[:max_cycles]

    total_seen = len(all_cycles)
    bars = _load_bars_for_journal(all_cycles, ohlcv_fixture=ohlcv_fixture)
    covered_cycles, with_c, without_c, cov_rate, skip_break = _compute_coverage_and_covered(all_cycles, bars)

    # Run zero-fee replay on covered only to get pure replay gross + per_cycle details
    zero_run = run_journal_window_replay(
        bars, covered_cycles, entry_fee_rate=Decimal("0"), exit_fee_rate=Decimal("0"), fee_scenario="zero_fee"
    )

    per_cycle_fidelity: List[Dict[str, Any]] = []
    skipped_details: List[Dict[str, Any]] = []

    # Skipped from the run's per_cycle (the no_ohlcv ones appended) + any other
    # But to be complete, use original all_cycles that are not in covered
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
            "gap_fixable_by_re_fetch": True,  # always possible in principle with public fetcher
            "recorded_net": str(c.get("net_pnl_recorded", "0")),
        })

    # Build fidelity rows for analyzed (covered that replayed)
    gross_residuals: List[Decimal] = []
    net_residuals_journal_fees: List[Decimal] = []
    abs_gross_res: List[Decimal] = []
    pct_of_notional: List[Decimal] = []
    direction_matches: List[bool] = []
    timeout_dir_matches: List[bool] = []

    by_sym: Dict[str, Dict] = defaultdict(lambda: {"analyzed": 0, "skipped": 0, "dir_match": 0, "signed_gross_res": Decimal("0"), "abs_gross_res": [], "net_res_journal_fees": Decimal("0")})
    by_strat: Dict[str, Dict] = defaultdict(lambda: {"analyzed": 0, "dir_match": 0, "signed_gross_res": Decimal("0")})
    by_exit: Dict[str, Dict] = defaultdict(lambda: {"analyzed": 0, "dir_match": 0, "signed_gross_res": Decimal("0")})

    replayed_count = 0
    for i, c in enumerate(covered_cycles):
        pc = zero_run.get("per_cycle", [{}])[i] if i < len(zero_run.get("per_cycle", [])) else {}
        if pc.get("replayed") is False:
            # should not happen for covered, but record
            continue

        replayed_count += 1
        sym = c.get("symbol", "UNKNOWN")
        strat = c.get("strategy", "unknown")
        rec_exit = c.get("exit_reason", "unknown")
        is_timeout = "max hold" in rec_exit.lower() or "max_hold_time_exceeded" in rec_exit.lower()

        j_g = _to_decimal(c.get("gross_pnl_recorded", "0"))
        j_f = _to_decimal(c.get("fees_recorded", "0"))
        j_n = _to_decimal(c.get("net_pnl_recorded", "0"))
        j_entry_p = _to_decimal(c.get("entry_price", "0"))
        j_exit_p = _to_decimal(c.get("exit_price", "0"))
        ntnl = _to_decimal(c.get("notional", "5"))

        r_g = _to_decimal(pc.get("replayed_gross", "0"))
        r_f_zero = _to_decimal(pc.get("replayed_fees", "0"))  # should be ~0
        r_n_zero = _to_decimal(pc.get("replayed_net", "0"))
        r_reason = pc.get("replayed_exit_reason", "unknown")
        dir_m = pc.get("direction_match")  # this is for net under the run fees (zero here) vs rec net

        # Compute replay exit price from gross (entry is journal exact)
        r_entry_p = j_entry_p
        r_exit_p = _compute_replay_exit_price(j_entry_p, r_g, ntnl)

        gross_res = r_g - j_g
        net_with_j_fees = r_g - j_f   # replay gross, journal fees
        net_res = net_with_j_fees - j_n

        sign_match = None
        if j_g != 0 or r_g != 0:
            sign_match = (r_g > 0) == (j_g > 0)

        pct = None
        if ntnl > 0:
            pct = abs(gross_res) / ntnl
            pct_of_notional.append(pct)

        gross_residuals.append(gross_res)
        net_residuals_journal_fees.append(net_res)
        abs_gross_res.append(abs(gross_res))
        if dir_m is not None:
            direction_matches.append(bool(dir_m))
            if is_timeout:
                timeout_dir_matches.append(bool(dir_m))

        entry_basis = "journal exact (fill_price from journal)"
        exit_basis = _infer_replay_exit_basis(r_reason)

        row = {
            "symbol": sym,
            "strategy": strat,
            "exit_reason_journal": rec_exit,
            "entry_time": str(c.get("entry_time")) if c.get("entry_time") else None,
            "exit_time": str(c.get("exit_time")) if c.get("exit_time") else None,
            "journal_entry_price": str(j_entry_p) if j_entry_p else None,
            "journal_exit_price": str(j_exit_p) if j_exit_p else None,
            "replay_entry_price": str(r_entry_p) if r_entry_p else None,
            "replay_exit_price": str(r_exit_p) if r_exit_p else None,
            "journal_gross": str(j_g),
            "replay_gross": str(r_g),
            "gross_residual": str(gross_res),
            "journal_fees": str(j_f),
            "replay_fee_assumption": "zero_fee (for gross); journal-recorded fees applied for net residual",
            "journal_net": str(j_n),
            "replay_net_with_journal_fees": str(net_with_j_fees),
            "net_residual_using_journal_fees": str(net_res),
            "sign_match": sign_match,
            "residual_pct_of_notional": str(pct) if pct is not None else None,
            "replay_entry_basis": entry_basis,
            "replay_exit_basis": exit_basis,
            "is_timeout_exit": is_timeout,
            "direction_match_from_replay_run": dir_m,
        }
        per_cycle_fidelity.append(row)

        by_sym[sym]["analyzed"] += 1
        by_sym[sym]["signed_gross_res"] += gross_res
        by_sym[sym]["abs_gross_res"].append(abs(gross_res))
        by_sym[sym]["net_res_journal_fees"] += net_res
        if dir_m:
            by_sym[sym]["dir_match"] += 1

        by_strat[strat]["analyzed"] += 1
        by_strat[strat]["signed_gross_res"] += gross_res
        if dir_m:
            by_strat[strat]["dir_match"] += 1

        by_exit[rec_exit]["analyzed"] += 1
        by_exit[rec_exit]["signed_gross_res"] += gross_res
        if dir_m:
            by_exit[rec_exit]["dir_match"] += 1

    analyzed = len(per_cycle_fidelity)

    # Aggregates
    signed_gross_total = sum(gross_residuals) if gross_residuals else Decimal("0")
    abs_gross_total = sum(abs_gross_res) if abs_gross_res else Decimal("0")
    mean_gross_res = (signed_gross_total / analyzed) if analyzed > 0 else Decimal("0")
    med_abs_gross = median([float(x) for x in abs_gross_res]) if abs_gross_res else 0.0
    p75_abs = None
    p90_abs = None
    if abs_gross_res:
        s = sorted(float(x) for x in abs_gross_res)
        p75_abs = s[int(0.75 * (len(s)-1))] if len(s) > 1 else s[0]
        p90_abs = s[int(0.90 * (len(s)-1))] if len(s) > 1 else s[0]
    max_abs = max(abs_gross_res) if abs_gross_res else Decimal("0")

    signed_net_jf_total = sum(net_residuals_journal_fees) if net_residuals_journal_fees else Decimal("0")

    dir_match = round(sum(1 for m in direction_matches if m) / len(direction_matches), 6) if direction_matches else None
    mismatch_count = sum(1 for m in direction_matches if not m) if direction_matches else 0

    timeout_dir_match = round(sum(1 for m in timeout_dir_matches if m) / len(timeout_dir_matches), 6) if timeout_dir_matches else None

    # By-sym summaries (fill dir_match rate and med abs)
    by_sym_out = {}
    for k, v in sorted(by_sym.items()):
        dmatch = round(v["dir_match"] / v["analyzed"], 6) if v["analyzed"] > 0 else None
        med_abs = median([float(x) for x in v["abs_gross_res"]]) if v["abs_gross_res"] else 0.0
        by_sym_out[k] = {
            "analyzed": v["analyzed"],
            "skipped": v.get("skipped", 0),
            "direction_match": dmatch,
            "signed_gross_residual": _fmt_money(v["signed_gross_res"]),
            "median_abs_gross_residual": _fmt_money(Decimal(str(med_abs))),
            "net_residual_journal_fees": _fmt_money(v["net_res_journal_fees"]),
        }

    by_strat_out = {}
    for k, v in sorted(by_strat.items()):
        dmatch = round(v["dir_match"] / v["analyzed"], 6) if v["analyzed"] > 0 else None
        by_strat_out[k] = {
            "analyzed": v["analyzed"],
            "direction_match": dmatch,
            "signed_gross_residual": _fmt_money(v["signed_gross_res"]),
        }

    by_exit_out = {}
    for k, v in sorted(by_exit.items()):
        dmatch = round(v["dir_match"] / v["analyzed"], 6) if v["analyzed"] > 0 else None
        by_exit_out[k] = {
            "analyzed": v["analyzed"],
            "direction_match": dmatch,
            "signed_gross_residual": _fmt_money(v["signed_gross_res"]),
        }

    # Trust gates (conservative)
    replay_trustworthy = True
    failed_gates: List[str] = []
    notes: List[str] = []

    dir_threshold = Decimal("0.85")
    if dir_match is None or dir_match < 0.85:
        replay_trustworthy = False
        failed_gates.append(f"direction_match < 0.85 (got {dir_match})")

    # median abs residual <= 10% of notional: use median of the % list
    med_pct = median([float(x) for x in pct_of_notional]) if pct_of_notional else 1.0
    if med_pct > 0.10:
        replay_trustworthy = False
        failed_gates.append(f"median abs residual pct of notional > 0.10 (got {round(med_pct,6)})")

    if abs(signed_net_jf_total) > Decimal("0.10"):
        replay_trustworthy = False
        failed_gates.append(f"abs(signed total net residual using journal fees) > 0.10 (got { _fmt_money(signed_net_jf_total) })")

    if not pct_of_notional:
        replay_trustworthy = False
        failed_gates.append("cannot compute residual % of notional (missing notionals)")

    # Suspected drivers
    suspected: List[str] = []
    if dir_match is not None and dir_match < 0.7:
        suspected.append("low direction_match suggests systematic bias in exit price or entry timing vs journal fills")
    if med_pct > 0.05:
        suspected.append("median residual >5% of notional points to bar-granularity / slippage / fill-price mismatch")
    if "max hold" in str(by_exit_out):
        suspected.append("dominance of timeout exits amplifies any close-vs-fill discrepancy")
    if not suspected:
        suspected.append("residuals small and direction high; replay appears faithful on covered cycles")

    # Build payload
    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "report_class": "replay_fidelity_reconciliation",
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
            "Offline replay fidelity reconciliation. Compares per-cycle replay gross (zero-fee run) and replay gross + journal fees net against journal-recorded values.",
            "Entry price in replay is taken exactly from journal (by design of journal-window replay). Exit price derived from replay gross + notional.",
            "Direction match and residuals use the actual journal entry/exit prices and fees where recorded.",
            "replay_trustworthy verdict uses conservative gates. Failure means P2-025L fee scenarios are not actionable.",
            "Skipped cycles (ADA/ETH gaps) are detailed but the verdict is computed only on cycles with OHLCV coverage.",
        ],
        "per_cycle": per_cycle_fidelity,
        "residual_distribution": {
            "count": analyzed,
            "signed_total_gross_residual": _fmt_money(signed_gross_total),
            "absolute_total_gross_residual": _fmt_money(abs_gross_total),
            "mean_gross_residual": _fmt_money(mean_gross_res),
            "median_abs_gross_residual": _fmt_money(Decimal(str(med_abs_gross))),
            "p75_abs_gross_residual": _fmt_money(Decimal(str(p75_abs))) if p75_abs is not None else None,
            "p90_abs_gross_residual": _fmt_money(Decimal(str(p90_abs))) if p90_abs is not None else None,
            "max_abs_gross_residual": _fmt_money(max_abs),
            "median_residual_pct_of_notional": round(med_pct, 6) if pct_of_notional else None,
        },
        "direction_fidelity": {
            "direction_match": dir_match,
            "mismatch_count": mismatch_count,
            "timeout_direction_match": timeout_dir_match,
            "mismatched_cycles": [r for r in per_cycle_fidelity if r.get("sign_match") is False][:20],  # limit
        },
        "by_symbol": by_sym_out,
        "by_strategy": by_strat_out,
        "by_exit_reason": by_exit_out,
        "timeout_specific": {
            "count": sum(1 for r in per_cycle_fidelity if r.get("is_timeout_exit")),
            "direction_match": timeout_dir_match,
        },
        "replay_trustworthy": replay_trustworthy,
        "failed_trust_gates": failed_gates,
        "suspected_residual_drivers": suspected,
        "senior_consultant_note": "P2-025L fee scenario results (including break-even, notional sensitivity, and 'fee_drag_dominant' verdict) are not actionable until replay fidelity passes the conservative gates above.",
    }

    payload["trade_permission"] = "none"
    payload["risk_increase"] = "not_approved"
    payload["scaling_allowed"] = False

    # Convenience top-level aggregates for smokes/transcripts (match economics style where possible)
    payload["replay_gross_pnl_sum"] = payload["residual_distribution"].get("count", 0) and _fmt_money(Decimal("0"))  # gross is per-cycle; use signed for convenience
    # Actually compute from per_cycle
    rg_sum = sum(Decimal(r["replay_gross"]) for r in per_cycle_fidelity) if per_cycle_fidelity else Decimal("0")
    payload["replay_gross_pnl_sum"] = _fmt_money(rg_sum)
    jg_sum = sum(Decimal(r["journal_gross"]) for r in per_cycle_fidelity) if per_cycle_fidelity else Decimal("0")
    payload["journal_analyzed_gross"] = _fmt_money(jg_sum)

    return payload


def _human_summary(payload: Dict[str, Any]) -> str:
    lines = []
    lines.append("=== REPLAY FIDELITY RECONCILIATION (P2-025M) ===")
    lines.append(f"Journal: {payload.get('journal_path')}")
    lines.append(f"Coverage: seen={payload['cycles_seen']} analyzed={payload['cycles_analyzed']} skipped={payload['cycles_skipped']} rate={payload['coverage_rate']}")
    lines.append(f"Skip breakdown: {payload.get('skip_reason_breakdown')}")
    lines.append("")
    lines.append("Skipped cycle details (gaps do not block verdict on covered cycles):")
    for s in payload.get("skipped_cycle_details", [])[:5]:
        lines.append(f"  {s['symbol']} entry={s['entry_time']} exit={s['exit_time']} reason={s['missing_ohlcv_window_reason']}")
    if len(payload.get("skipped_cycle_details", [])) > 5:
        lines.append("  ...")
    lines.append("")
    rd = payload.get("residual_distribution", {})
    lines.append("Residual distribution (gross replay vs journal):")
    lines.append(f"  signed_total={rd.get('signed_total_gross_residual')} abs_total={rd.get('absolute_total_gross_residual')}")
    lines.append(f"  mean={rd.get('mean_gross_residual')} med_abs={rd.get('median_abs_gross_residual')} p75={rd.get('p75_abs_gross_residual')} p90={rd.get('p90_abs_gross_residual')} max_abs={rd.get('max_abs_gross_residual')}")
    lines.append(f"  med_pct_of_notional={rd.get('median_residual_pct_of_notional')}")
    lines.append("")
    df = payload.get("direction_fidelity", {})
    lines.append(f"Direction fidelity: match={df.get('direction_match')} mismatches={df.get('mismatch_count')} timeout_match={df.get('timeout_direction_match')}")
    lines.append("")
    lines.append("By symbol (analyzed/skipped, dir_match, signed_gross_res, med_abs):")
    for k, v in payload.get("by_symbol", {}).items():
        lines.append(f"  {k}: analyzed={v['analyzed']} skipped={v.get('skipped',0)} match={v['direction_match']} signed_res={v['signed_gross_residual']} med_abs={v['median_abs_gross_residual']}")
    lines.append("")
    lines.append(f"replay_trustworthy: {payload.get('replay_trustworthy')}")
    if payload.get("failed_trust_gates"):
        lines.append(f"  failed_gates: {payload.get('failed_trust_gates')}")
    lines.append(f"  suspected_drivers: {payload.get('suspected_residual_drivers')}")
    lines.append("")
    lines.append("Safety: trade_permission=none, risk_increase=not_approved, scaling_allowed=false")
    lines.append("This is offline diagnostic only. Does not authorize live trading, sizing, maker studies, or exit changes.")
    lines.append("=== END REPORT ===")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Replay fidelity reconciliation (P2-025M, offline only)")
    ap.add_argument("--json", action="store_true", help="Emit JSON")
    ap.add_argument("--journal", type=Path, default=None)
    ap.add_argument("--ohlcv-fixture", type=Path, default=None)
    ap.add_argument("--max-cycles", type=int, default=None)
    ap.add_argument("--output", type=Path, default=None, help="Optional write path for JSON")
    args = ap.parse_args(argv)

    payload = build_replay_fidelity_report(
        journal_path=args.journal,
        ohlcv_fixture=args.ohlcv_fixture,
        max_cycles=args.max_cycles,
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
