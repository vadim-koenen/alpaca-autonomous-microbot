#!/usr/bin/env python3
"""
run_pivot_gate.py — P2-044D one-command orchestrator for the equities/ETF swing
pivot decision. Runs the anti-overfitting robustness sweep (P2-044C) AND the
real-cost walk-forward gate (P2-044B) on one OHLCV CSV and emits ONE combined
verdict: GO_TO_PAPER or NO_GO.

GOVERNANCE
- Offline only; no broker, no network, no runtime mutation. Writes to /tmp.
- The strongest possible output is GO_TO_PAPER. This NEVER authorizes live trading.
  The path is: ROBUST + gate PASS (on REAL data) -> paper reproduction (M4) ->
  bounded live A/B (M5). Live stays NO-GO here.
- Data-agnostic: needs REAL daily OHLCV via --csv to be decision-grade. Without
  --csv it runs a synthetic mechanics smoke test stamped decision_grade=false,
  which can never be GO_TO_PAPER.

COMBINED DECISION (all must hold for GO_TO_PAPER)
  1. decision_grade is True (real data supplied)
  2. robustness verdict == ROBUST  (edge survives OOS across the param grid)
  3. full-sample gate verdict == PASS  (sanity check on default params)
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import equities_swing_backtest_gate as gate
import swing_param_robustness as rob


def run_decision(
    bars: List[gate.Bar],
    costs: Optional[gate.CostModel] = None,
    decision_grade: bool = True,
    min_trades_gate: int = gate.MIN_TRADES,
    min_trades_oos: int = 30,
) -> Dict[str, Any]:
    costs = costs or gate.CostModel()

    rob_v = rob.run_robustness(bars, costs, min_trades_oos=min_trades_oos,
                               decision_grade=decision_grade)
    gate_v = gate.evaluate(bars, gate.SwingParams(), costs,
                           min_trades=min_trades_gate, decision_grade=decision_grade)

    robust_ok = rob_v["verdict"] == "ROBUST"
    gate_ok = gate_v["verdict"] == "PASS"
    go = bool(decision_grade and robust_ok and gate_ok)

    reasons: List[str] = []
    if not decision_grade:
        reasons.append("not_decision_grade(synthetic_or_no_csv)")
    if not robust_ok:
        reasons.append(f"robustness={rob_v['verdict']}(need ROBUST)")
    if not gate_ok:
        reasons.append(f"gate={gate_v['verdict']}(need PASS); fails={gate_v['fail_reasons']}")

    return {
        "schema": "p2_044d_pivot_gate_decision/v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "lane": "alpaca_equities_etf_swing",
        "decision_grade": decision_grade,
        "n_bars": len(bars),
        "robustness_verdict": rob_v["verdict"],
        "robustness_oos_pass_fraction": rob_v["oos_pass_fraction"],
        "robustness_median_oos_ev_bps": rob_v["median_oos_net_ev_per_trade_bps"],
        "gate_verdict": gate_v["verdict"],
        "gate_metrics": gate_v["metrics"],
        "gate_fail_reasons": gate_v["fail_reasons"],
        "verdict": "GO_TO_PAPER" if go else "NO_GO",
        "reasons": reasons,
        "authorizes_live": False,
        "next_step": (
            "Paper reproduction (M4): reproduce these net-of-cost results in paper over "
            ">=30-50 trades before any bounded live A/B (M5). Live stays NO-GO."
            if go else
            "Do NOT pivot live. Reconsider lane (cheaper-venue crypto MARGINAL) or park "
            "the system. No-trade is a valid optimum."
        ),
    }


def render_markdown(d: Dict[str, Any]) -> str:
    m = d["gate_metrics"]
    lines = [
        "# P2-044D — Pivot Gate Decision (combined)",
        "",
        f"Generated: {d['generated_utc']}",
        f"Lane: {d['lane']} · bars: {d['n_bars']} · decision_grade={d['decision_grade']}",
        "",
        f"**VERDICT: {d['verdict']}**  ·  authorizes_live={d['authorizes_live']}",
        "",
        f"- Robustness (P2-044C): **{d['robustness_verdict']}** "
        f"(OOS pass fraction {d['robustness_oos_pass_fraction']}, "
        f"median OOS EV {d['robustness_median_oos_ev_bps']} bps)",
        f"- Gate (P2-044B): **{d['gate_verdict']}** "
        f"(trades {m['n_trades']}, net EV/trade {m['net_ev_per_trade_bps']} bps, "
        f"PF {m['profit_factor']})",
        "",
    ]
    if d["reasons"]:
        lines += ["Why not GO_TO_PAPER:" if d["verdict"] == "NO_GO" else "Notes:"]
        lines += [f"- {r}" for r in d["reasons"]]
        lines.append("")
    lines += [f"**Next step:** {d['next_step']}", ""]
    return "\n".join(lines)


def write_outputs(d: Dict[str, Any], out_dir: Path) -> Dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    jp = out_dir / "p2_044d_pivot_gate_decision.json"
    mp = out_dir / "p2_044d_pivot_gate_decision.md"
    jp.write_text(json.dumps(d, indent=2))
    mp.write_text(render_markdown(d))
    return {"json": str(jp), "md": str(mp)}


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="P2-044D combined pivot gate decision")
    p.add_argument("--csv", help="Daily OHLCV CSV (date,open,high,low,close,volume). REAL => decision-grade.")
    p.add_argument("--out-dir", default="/tmp")
    p.add_argument("--print", action="store_true")
    args = p.parse_args(argv)

    if args.csv:
        bars = gate.load_bars_csv(Path(args.csv))
        d = run_decision(bars, gate.CostModel(), decision_grade=True)
    else:
        print("[p2-044d] WARNING: no --csv. SYNTHETIC bars; verdict can only be NO_GO.")
        bars = gate.synthetic_bars(n=900, seed=5)
        d = run_decision(bars, gate.CostModel(), decision_grade=False,
                         min_trades_gate=20, min_trades_oos=5)

    paths = write_outputs(d, Path(args.out_dir))
    if args.print:
        print(render_markdown(d))
    print(f"[p2-044d] verdict={d['verdict']} decision_grade={d['decision_grade']}")
    print(f"[p2-044d] wrote {paths['json']}")
    print(f"[p2-044d] wrote {paths['md']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
