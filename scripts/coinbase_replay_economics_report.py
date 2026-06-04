#!/usr/bin/env python3
"""
scripts/coinbase_replay_economics_report.py — Offline replay economics and fee scenario report (P2-025L).

Uses the 48 replayable journal windows (from P2-025K coverage) to compare journal-recorded
outcomes against replay-derived gross P/L under multiple fee assumptions.

Purpose: expose whether losses are driven by direction, exits, spreads/fees, or sizing economics.
NOT for strategy tuning yet; evidence gate only.

Pure offline. No broker, no orders, no mutation, no .env, no secrets, no live.
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
    DEFAULT_ENTRY_FEE_RATE,
    DEFAULT_EXIT_FEE_RATE,
    _normalize_symbol,
    load_bars_from_fixture,
    parse_journal_cycles,
    run_journal_window_replay,
)

SCHEMA_VERSION = "p2-025l.coinbase_replay_economics_report.v1"
DEFAULT_JOURNAL = ROOT / "journal_coinbase_crypto.csv"
DATA_DIR = ROOT / "data" / "offline_ohlcv" / "coinbase"


# Fee scenario definitions (rates are round-turn conservative assumptions; not live config)
TAKER_ENTRY = Decimal("0.012")
TAKER_EXIT = Decimal("0.012")
MAKER_ENTRY = Decimal("0.004")
MAKER_EXIT = Decimal("0.004")
MIXED_ENTRY = Decimal("0.004")  # maker on entry (post)
MIXED_EXIT = Decimal("0.012")


def _to_float(d: Any) -> float:
    if d is None:
        return 0.0
    try:
        return float(d)
    except Exception:
        return 0.0


def _to_decimal(v: Any, default: Decimal = Decimal("0")) -> Decimal:
    if v is None:
        return default
    try:
        d = Decimal(str(v))
        if d.is_nan():
            return default
        return d
    except Exception:
        return default


def _fmt_money(d: Decimal) -> str:
    return str(d.quantize(Decimal("0.00000001")))


def _fmt_rate(d: Decimal) -> str:
    return str(d.quantize(Decimal("0.000001")))


def _compute_coverage_and_covered(
    cycles: List[Dict[str, Any]], bars: List[Any]
) -> tuple[List[Dict[str, Any]], int, int, float, Dict[str, int]]:
    """Return (covered_cycles, with_count, without_count, coverage_rate, skip_breakdown).
    Mirrors logic from journal_window_replay_report but only for reuse of parse/load.
    """
    total = len(cycles)
    if total == 0:
        return [], 0, 0, 0.0, {}
    covered: List[Dict[str, Any]] = []
    without = 0
    skip: Dict[str, int] = defaultdict(int)
    per_sym: Dict[str, Dict] = defaultdict(lambda: {"seen": 0, "with": 0})
    for c in cycles:
        sym = _normalize_symbol(c.get("symbol", ""))
        et = c.get("entry_time")
        xt = c.get("exit_time")
        per_sym[sym]["seen"] += 1
        has = False
        if bars and et and xt:
            for b in bars:
                bsym = _normalize_symbol(getattr(b, "symbol", "") or "")
                if (not sym or bsym == sym) and et <= b.t <= xt:
                    has = True
                    break
        if has:
            covered.append(c)
            per_sym[sym]["with"] += 1
        else:
            without += 1
            skip["no_ohlcv_in_window"] += 1
    with_c = total - without
    rate = round(with_c / total, 6) if total > 0 else 0.0
    return covered, with_c, without, rate, dict(skip)


def _load_bars_for_journal(
    cycles: List[Dict[str, Any]], ohlcv_fixture: Optional[Path] = None
) -> List[Any]:
    """Auto load from data/offline_ohlcv/coinbase/ or fixture. Reuses load_bars_from_fixture."""
    needed = set()
    earliest = None
    latest = None
    for c in cycles:
        sym = _normalize_symbol(c.get("symbol", ""))
        if sym:
            needed.add(sym)
        et = c.get("entry_time")
        xt = c.get("exit_time")
        if et and (earliest is None or et < earliest):
            earliest = et
        if xt and (latest is None or xt > latest):
            latest = xt

    bars: List[Any] = []
    if ohlcv_fixture:
        try:
            bars = load_bars_from_fixture(ohlcv_fixture, start=earliest, end=latest)
        except Exception:
            bars = []
    elif DATA_DIR.exists():
        try:
            for f in sorted(DATA_DIR.glob("*.csv")) + sorted(DATA_DIR.glob("*.json")):
                fname = f.name.upper()
                for ns in needed:
                    n = ns.replace("/", "-").replace("/", "_").upper()
                    if n in fname or ns.replace("/", "").upper() in fname:
                        b = load_bars_from_fixture(f, symbol=ns, start=earliest, end=latest)
                        bars.extend(b)
            if bars:
                bars.sort(key=lambda b: b.t)
        except Exception:
            pass
    return bars


def _compute_fees_and_net(gross: Decimal, notional: Decimal, entry_rate: Decimal, exit_rate: Decimal) -> Decimal:
    exit_notional = notional + gross
    fees = (notional * entry_rate) + (exit_notional * exit_rate)
    return gross - fees


def _compute_break_even_rate(per_trade: List[Dict[str, Any]]) -> Optional[str]:
    """Return fee rate (entry=exit) at which sum(gross) == sum(fees) for replay gross."""
    g_sum = Decimal("0")
    denom = Decimal("0")
    for t in per_trade:
        g = t["replay_gross"]
        n = t["notional"]
        g_sum += g
        denom += (n + (n + g))
    if denom <= 0 or g_sum <= 0:
        return None
    r = g_sum / denom
    return _fmt_rate(r)


def _scale_for_notional(net_at_orig: Decimal, orig_not: Decimal, target_not: Decimal) -> Decimal:
    if orig_not == 0:
        return Decimal("0")
    return net_at_orig * (target_not / orig_not)


def build_replay_economics_report(
    *,
    journal_path: Optional[Path] = None,
    ohlcv_fixture: Optional[Path] = None,
    max_cycles: Optional[int] = None,
) -> Dict[str, Any]:
    jpath = Path(journal_path) if journal_path else DEFAULT_JOURNAL
    all_cycles = parse_journal_cycles(jpath)

    if max_cycles:
        all_cycles = all_cycles[:max_cycles]

    # recorded aggregates over ALL seen (for skip accounting)
    rec_wins = rec_losses = rec_breakeven = 0
    rec_gross = rec_fees = rec_net = Decimal("0")
    rec_reasons: Dict[str, int] = defaultdict(int)
    rec_by_strat: Dict[str, Dict] = defaultdict(lambda: {"net": Decimal("0"), "count": 0, "gross": Decimal("0"), "fees": Decimal("0")})
    rec_by_sym: Dict[str, Dict] = defaultdict(lambda: {"net": Decimal("0"), "count": 0, "gross": Decimal("0"), "fees": Decimal("0")})
    for c in all_cycles:
        n = c.get("net_pnl_recorded", Decimal("0"))
        g = c.get("gross_pnl_recorded", Decimal("0"))
        f = c.get("fees_recorded", Decimal("0"))
        rec_gross += g
        rec_fees += f
        rec_net += n
        r = c.get("exit_reason", "unknown")
        rec_reasons[r] += 1
        strat = c.get("strategy", "unknown")
        sym = c.get("symbol", "UNKNOWN")
        rec_by_strat[strat]["net"] += n
        rec_by_strat[strat]["gross"] += g
        rec_by_strat[strat]["fees"] += f
        rec_by_strat[strat]["count"] += 1
        rec_by_sym[sym]["net"] += n
        rec_by_sym[sym]["gross"] += g
        rec_by_sym[sym]["fees"] += f
        rec_by_sym[sym]["count"] += 1
        if n > 0:
            rec_wins += 1
        elif n < 0:
            rec_losses += 1
        else:
            rec_breakeven += 1
    rec_total = len(all_cycles)
    rec_win_rate = round(rec_wins / rec_total, 6) if rec_total > 0 else 0.0

    # load bars + identify only covered cycles (preserve skip accounting)
    bars = _load_bars_for_journal(all_cycles, ohlcv_fixture=ohlcv_fixture)
    covered_cycles, with_c, without_c, cov_rate, skip_break = _compute_coverage_and_covered(all_cycles, bars)

    # Run zero-fee on covered only to get pure replay gross (exit logic/path P/L independent of fees)
    zero_run = run_journal_window_replay(
        bars, covered_cycles, entry_fee_rate=Decimal("0"), exit_fee_rate=Decimal("0"), fee_scenario="zero_fee"
    )

    # Also run taker for direction match + baseline aggregates under default
    taker_run = run_journal_window_replay(
        bars, covered_cycles, entry_fee_rate=TAKER_ENTRY, exit_fee_rate=TAKER_EXIT, fee_scenario="taker/taker"
    )

    # Build per_trade with replay_gross (from zero) + notional + recorded for analyzed cycles
    per_trade: List[Dict[str, Any]] = []
    for i, c in enumerate(covered_cycles):
        pc = zero_run.get("per_cycle", [{}])[i] if i < len(zero_run.get("per_cycle", [])) else {}
        g = _to_decimal(pc.get("replayed_gross", "0"))
        n = c.get("notional", Decimal("5.0"))
        rec_n = c.get("net_pnl_recorded", Decimal("0"))
        rec_g = c.get("gross_pnl_recorded", Decimal("0"))
        rec_f = c.get("fees_recorded", Decimal("0"))
        er = c.get("exit_reason", "unknown")
        sym = c.get("symbol", "UNKNOWN")
        strat = c.get("strategy", "unknown")
        per_trade.append({
            "symbol": sym,
            "strategy": strat,
            "notional": n,
            "replay_gross": g,
            "recorded_net": rec_n,
            "recorded_gross": rec_g,
            "recorded_fees": rec_f,
            "exit_reason": er,
        })

    analyzed = len(per_trade)
    skipped = without_c  # from coverage (the 1 without)

    # Fee scenarios (journal_recorded_fees uses replay gross + journal's recorded fees for that cycle)
    fee_scenarios: Dict[str, Any] = {}
    scenario_defs = {
        "journal_recorded_fees": {"entry": None, "exit": None, "label": "journal_recorded_fees (replay_gross - recorded_fees)"},
        "taker/taker": {"entry": TAKER_ENTRY, "exit": TAKER_EXIT, "label": "taker/taker (default conservative)"},
        "maker/maker": {"entry": MAKER_ENTRY, "exit": MAKER_EXIT, "label": "maker/maker (optimistic lower)"},
        "zero_fee": {"entry": Decimal("0"), "exit": Decimal("0"), "label": "zero_fee (theoretical edge only)"},
        "mixed_maker_taker": {"entry": MIXED_ENTRY, "exit": MIXED_EXIT, "label": "mixed_maker_taker (maker entry / taker exit)"},
    }

    for sname, sdef in scenario_defs.items():
        nets: List[Decimal] = []
        by_sym: Dict[str, Dict] = defaultdict(lambda: {"count": 0, "net_sum": Decimal("0"), "gross_sum": Decimal("0"), "fees_sum": Decimal("0"), "wins": 0, "losses": 0})
        by_exit: Dict[str, Dict] = defaultdict(lambda: {"count": 0, "net_sum": Decimal("0"), "wins": 0, "losses": 0})
        by_strat: Dict[str, Dict] = defaultdict(lambda: {"count": 0, "net_sum": Decimal("0"), "wins": 0, "losses": 0})
        g_sum = Decimal("0")
        f_sum = Decimal("0")
        for t in per_trade:
            g = t["replay_gross"]
            n = t["notional"]
            g_sum += g
            if sname == "journal_recorded_fees":
                fees = t["recorded_fees"]
                net = g - fees
            else:
                re = sdef["entry"] or Decimal("0")
                rx = sdef["exit"] or Decimal("0")
                net = _compute_fees_and_net(g, n, re, rx)
                fees = g - net
            f_sum += fees
            nets.append(net)

            sym = t["symbol"]
            er = t["exit_reason"]
            st = t["strategy"]
            by_sym[sym]["count"] += 1
            by_sym[sym]["net_sum"] += net
            by_sym[sym]["gross_sum"] += g
            by_sym[sym]["fees_sum"] += fees
            if net > 0:
                by_sym[sym]["wins"] += 1
            elif net < 0:
                by_sym[sym]["losses"] += 1

            by_exit[er]["count"] += 1
            by_exit[er]["net_sum"] += net
            if net > 0:
                by_exit[er]["wins"] += 1
            elif net < 0:
                by_exit[er]["losses"] += 1

            by_strat[st]["count"] += 1
            by_strat[st]["net_sum"] += net
            if net > 0:
                by_strat[st]["wins"] += 1
            elif net < 0:
                by_strat[st]["losses"] += 1

        wins = sum(1 for nn in nets if nn > 0)
        losses = sum(1 for nn in nets if nn < 0)
        breakeven = len(nets) - wins - losses
        wr = round(wins / len(nets), 6) if nets else 0.0
        nsum = sum(nets)
        avg_n = (nsum / len(nets)) if nets else Decimal("0")
        med_n = median([float(x) for x in nets]) if nets else 0.0
        best_n = max(nets) if nets else Decimal("0")
        worst_n = min(nets) if nets else Decimal("0")

        fee_scenarios[sname] = {
            "label": sdef["label"],
            "gross_pnl_sum": _fmt_money(g_sum),
            "fee_sum": _fmt_money(f_sum),
            "net_pnl_sum": _fmt_money(nsum),
            "wins": wins,
            "losses": losses,
            "breakeven": breakeven,
            "win_rate": wr,
            "avg_net_pnl": _fmt_money(avg_n),
            "median_net_pnl": _fmt_money(Decimal(str(med_n))),
            "best_net_pnl": _fmt_money(best_n),
            "worst_net_pnl": _fmt_money(worst_n),
            "per_symbol": {
                k: {
                    "count": v["count"],
                    "net_pnl_sum": _fmt_money(v["net_sum"]),
                    "gross_pnl_sum": _fmt_money(v["gross_sum"]),
                    "fee_sum": _fmt_money(v["fees_sum"]),
                    "wins": v["wins"],
                    "losses": v["losses"],
                }
                for k, v in sorted(by_sym.items())
            },
            "per_exit_reason": {
                k: {"count": v["count"], "net_pnl_sum": _fmt_money(v["net_sum"]), "wins": v["wins"], "losses": v["losses"]}
                for k, v in sorted(by_exit.items())
            },
            "per_strategy": {
                k: {"count": v["count"], "net_pnl_sum": _fmt_money(v["net_sum"]), "wins": v["wins"], "losses": v["losses"]}
                for k, v in sorted(by_strat.items())
            },
        }

    # Timeout (max hold) share from journal exit reasons on analyzed
    timeout_count = sum(1 for t in per_trade if "max hold" in t["exit_reason"].lower() or "max_hold_time_exceeded" in t["exit_reason"].lower())
    timeout_share = round(timeout_count / analyzed, 6) if analyzed > 0 else 0.0

    # Break-even (replay gross -> zero net under symmetric r)
    be_rate = _compute_break_even_rate(per_trade)

    # Notional sensitivity (scale under taker/taker as baseline; offline math only)
    notional_targets = [Decimal("0.5"), Decimal("1"), Decimal("5"), Decimal("10")]
    notional_sens: Dict[str, Any] = {}
    taker_nets = [ _compute_fees_and_net(t["replay_gross"], t["notional"], TAKER_ENTRY, TAKER_EXIT) for t in per_trade ]
    for nt in notional_targets:
        scaled = []
        for idx, t in enumerate(per_trade):
            orig_net = taker_nets[idx]
            scaled.append( _scale_for_notional(orig_net, t["notional"], nt) )
        ssum = sum(scaled)
        notional_sens[str(nt)] = {
            "net_pnl_sum": _fmt_money(ssum),
            "avg_net_pnl": _fmt_money( (ssum / len(scaled)) if scaled else Decimal("0") ),
        }

    # Direction match (use the taker run's value; it compares replay_net sign vs recorded_net sign under taker fees)
    direction_match = taker_run.get("replay_vs_journal_direction_match")

    # Verdict (plain-English, evidence only)
    replay_gross_sum = _to_decimal( zero_run.get("gross_pnl_sum", "0") )
    zero_net_sum = _to_decimal( fee_scenarios["zero_fee"]["net_pnl_sum"] )
    taker_net_sum = _to_decimal( fee_scenarios["taker/taker"]["net_pnl_sum"] )
    journal_net_analyzed = sum( (t["recorded_net"] for t in per_trade), Decimal("0") )

    if replay_gross_sum > Decimal("0.05") and zero_net_sum > Decimal("0"):
        verdict = "fee_drag_dominant"
    elif replay_gross_sum < Decimal("-0.05"):
        verdict = "directionally_negative"
    elif timeout_share >= 0.8 and taker_net_sum < Decimal("0"):
        verdict = "exit_logic_negative"
    else:
        verdict = "inconclusive"

    # Build payload (always safe defaults)
    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "report_class": "replay_economics_fee_scenarios",
        "journal_path": str(jpath),
        "ohlcv_fixture": str(ohlcv_fixture) if ohlcv_fixture else None,
        "cycles_seen": rec_total,
        "cycles_analyzed": analyzed,
        "cycles_skipped": skipped,
        "coverage_rate": cov_rate,
        "skip_reason_breakdown": skip_break,
        "required_symbols": sorted(list(set(_normalize_symbol(c.get("symbol", "")) for c in all_cycles if c.get("symbol")))),
        "trade_permission": "none",
        "risk_increase": "not_approved",
        "scaling_allowed": False,
        "notes": [
            "Offline-only replay economics on journal windows with OHLCV coverage.",
            "Gross from replay harness on actual price path in each window; fees applied under scenarios (no live config).",
            "Journal-recorded values are broker-backed from journal; replay gross is simulated (bar granularity + slippage model).",
            "Notional sensitivity is pure offline math (linear scale of gross/fees); does not change live caps or notional.",
            "Verdict and break-even are evidence summaries only. This does not authorize scaling, tuning, or live trading.",
        ],
        "journal_recorded": {
            "wins": rec_wins,
            "losses": rec_losses,
            "breakeven": rec_breakeven,
            "win_rate": rec_win_rate,
            "gross_pnl_sum": _fmt_money(rec_gross),
            "fees_sum": _fmt_money(rec_fees),
            "net_pnl_sum": _fmt_money(rec_net),
            "dominant_exit_reason": max(rec_reasons.items(), key=lambda x: x[1])[0] if rec_reasons else None,
            "exit_reason_breakdown": dict(rec_reasons),
            "per_strategy": {k: {"count": v["count"], "net_pnl_sum": _fmt_money(v["net"]), "gross_pnl_sum": _fmt_money(v["gross"]), "fee_sum": _fmt_money(v["fees"])} for k, v in sorted(rec_by_strat.items())},
            "per_symbol": {k: {"count": v["count"], "net_pnl_sum": _fmt_money(v["net"]), "gross_pnl_sum": _fmt_money(v["gross"]), "fee_sum": _fmt_money(v["fees"])} for k, v in sorted(rec_by_sym.items())},
        },
        "journal_recorded_for_analyzed_cycles": {
            "net_pnl_sum": _fmt_money(journal_net_analyzed),
            "count": analyzed,
        },
        "fee_scenarios": fee_scenarios,
        "replay_gross_pnl_sum": _fmt_money(replay_gross_sum),
        "direction_match_replay_vs_journal": direction_match,
        "timeout_exit_count": timeout_count,
        "timeout_exit_share": timeout_share,
        "break_even_fee_rate": be_rate,
        "break_even_note": "Symmetric entry=exit rate at which replay gross sums to zero net. Not calculable if gross <=0 or denom=0." if be_rate is None else "Computed from replay gross and notionals on analyzed cycles.",
        "notional_sensitivity": notional_sens,
        "notional_sensitivity_note": "Offline linear scaling only. Uses per-cycle notional from journal and replay gross under taker baseline. Does not alter live risk/notional config.",
        "verdict": verdict,
        "verdict_evidence": {
            "replay_gross_sum": _fmt_money(replay_gross_sum),
            "zero_fee_net_sum": _fmt_money(zero_net_sum),
            "taker_net_sum": _fmt_money(taker_net_sum),
            "journal_net_analyzed": _fmt_money(journal_net_analyzed),
            "timeout_share": timeout_share,
        },
    }

    # top level safety
    payload["trade_permission"] = "none"
    payload["risk_increase"] = "not_approved"
    payload["scaling_allowed"] = False

    return payload


def _human_summary(payload: Dict[str, Any]) -> str:
    lines = []
    lines.append("=== REPLAY ECONOMICS FEE SCENARIO REPORT (P2-025L) ===")
    lines.append(f"Journal: {payload.get('journal_path')}")
    lines.append(f"Coverage: seen={payload['cycles_seen']} analyzed={payload['cycles_analyzed']} skipped={payload['cycles_skipped']} rate={payload['coverage_rate']}")
    lines.append(f"Skip breakdown: {payload.get('skip_reason_breakdown')}")
    lines.append("")
    jr = payload.get("journal_recorded", {})
    lines.append("Journal recorded (full seen):")
    lines.append(f"  net={jr.get('net_pnl_sum')} gross={jr.get('gross_pnl_sum')} fees={jr.get('fees_sum')} win_rate={jr.get('win_rate')}")
    lines.append(f"  dominant_exit={jr.get('dominant_exit_reason')} timeout_share_in_analyzed={payload.get('timeout_exit_share')}")
    lines.append("")
    lines.append(f"Replay gross (analyzed): {payload.get('replay_gross_pnl_sum')}")
    lines.append(f"Direction match (replay net sign vs journal recorded): {payload.get('direction_match_replay_vs_journal')}")
    lines.append("")
    lines.append("Fee scenarios (on analyzed cycles only):")
    for sname, s in payload.get("fee_scenarios", {}).items():
        lines.append(f"  {sname}: gross={s['gross_pnl_sum']} fees={s['fee_sum']} net={s['net_pnl_sum']} wr={s['win_rate']} avg={s['avg_net_pnl']} med={s['median_net_pnl']} best={s['best_net_pnl']} worst={s['worst_net_pnl']}")
    lines.append("")
    lines.append(f"Break-even fee rate (replay gross -> zero net): {payload.get('break_even_fee_rate')} ({payload.get('break_even_note')})")
    lines.append("")
    lines.append("Notional sensitivity (scaled under taker/taker baseline, offline math):")
    for nt, vals in payload.get("notional_sensitivity", {}).items():
        lines.append(f"  ${nt}: net_sum={vals['net_pnl_sum']} avg={vals['avg_net_pnl']}")
    lines.append("")
    lines.append(f"VERDICT: {payload.get('verdict')}")
    lines.append(f"  evidence: {payload.get('verdict_evidence')}")
    lines.append("")
    lines.append("Safety: trade_permission=none, risk_increase=not_approved, scaling_allowed=false")
    lines.append("This is offline evidence only. Does not authorize live trading, sizing changes, or strategy deployment.")
    lines.append("=== END REPORT ===")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Replay economics and fee scenario report (offline only, P2-025L)")
    ap.add_argument("--json", action="store_true", help="Emit JSON payload")
    ap.add_argument("--journal", type=Path, default=None, help="Path to journal csv")
    ap.add_argument("--ohlcv-fixture", type=Path, default=None, help="Optional OHLCV fixture (for tests)")
    ap.add_argument("--max-cycles", type=int, default=None, help="Limit for smoke/debug")
    ap.add_argument("--output", type=Path, default=None, help="Optional path to write JSON payload (reports/replay_economics/...)")
    args = ap.parse_args(argv)

    payload = build_replay_economics_report(
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
