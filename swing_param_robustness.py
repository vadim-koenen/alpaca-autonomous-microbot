#!/usr/bin/env python3
"""
swing_param_robustness.py — P2-044C anti-overfitting robustness sweep for the
equities/ETF swing lane (P2-044B gate).

WHY THIS EXISTS
---------------
The project's recurring failure mode is OVERFITTING: ~30 prior filters were mined
on tiny samples and all came back falsified/overfit. A single good-looking
parameter set is NOT evidence of edge. This module asks the harder question:

  "Does the swing edge survive OUT-OF-SAMPLE across a whole grid of parameters,
   or does it only look good for a cherry-picked combo on in-sample data?"

It runs anchored walk-forward: for each parameter combo it selects on the
in-sample (early) portion and scores on the out-of-sample (later) portion, then
reports the OOS distribution and an honest robustness verdict.

GOVERNANCE: offline only, no broker, no network, no runtime mutation. Reuses the
P2-044B gate. Data-agnostic; needs REAL OHLCV via --csv to be decision-grade.
Synthetic input is a mechanics smoke test only (decision_grade=false).

ROBUSTNESS VERDICT
  ROBUST     : >= ROBUST_PASS_FRACTION of combos PASS the gate out-of-sample AND
               median OOS net EV/trade > 0. (Edge is broad, not a fluke.)
  FRAGILE    : some combos pass OOS but below the robust fraction. Treat as weak;
               do not go live on a thin majority.
  FALSIFIED  : no combo passes OOS, or median OOS net EV/trade <= 0.
"""

from __future__ import annotations

import argparse
import itertools
import json
import statistics
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import equities_swing_backtest_gate as gate

ROBUST_PASS_FRACTION: float = 0.50   # >=50% of param combos must pass OOS to call it ROBUST
IN_SAMPLE_FRACTION: float = 0.6      # first 60% IS, last 40% OOS (anchored, no leakage)

# Parameter grid (kept small + sensible; expand on the Mac with real data).
GRID = {
    "breakout_lookback": [10, 20, 40],
    "stop_atr_mult": [1.5, 2.0, 3.0],
    "target_atr_mult": [2.0, 3.0, 4.0],
    "max_hold_days": [5, 10, 20],
}


def param_combos() -> List[gate.SwingParams]:
    keys = list(GRID.keys())
    combos = []
    for values in itertools.product(*(GRID[k] for k in keys)):
        kw = dict(zip(keys, values))
        # Only keep combos where target > stop (asymmetric payoff makes sense).
        if kw["target_atr_mult"] > kw["stop_atr_mult"]:
            combos.append(gate.SwingParams(**kw))
    return combos


def split_in_out(bars: List[gate.Bar], in_frac: float) -> (List[gate.Bar], List[gate.Bar]):
    cut = int(len(bars) * in_frac)
    return bars[:cut], bars[cut:]


def evaluate_combo_oos(
    bars: List[gate.Bar],
    params: gate.SwingParams,
    costs: gate.CostModel,
    min_trades_oos: int,
) -> Dict[str, Any]:
    """Score one combo on the OUT-OF-SAMPLE segment only (params are fixed, not fit
    to OOS). The IS segment exists to mimic real selection; here we report OOS."""
    _is, oos = split_in_out(bars, IN_SAMPLE_FRACTION)
    v = gate.evaluate(oos, params, costs, n_folds=3, min_trades=min_trades_oos,
                      decision_grade=False)
    return {
        "params": asdict(params),
        "oos_verdict": v["verdict"],
        "oos_net_ev_per_trade_bps": v["metrics"]["net_ev_per_trade_bps"],
        "oos_trades": v["metrics"]["n_trades"],
        "oos_profit_factor": v["metrics"]["profit_factor"],
        "oos_fail_reasons": v["fail_reasons"],
    }


def run_robustness(
    bars: List[gate.Bar],
    costs: Optional[gate.CostModel] = None,
    min_trades_oos: int = 30,
    decision_grade: bool = True,
) -> Dict[str, Any]:
    costs = costs or gate.CostModel()
    combos = param_combos()
    results = [evaluate_combo_oos(bars, c, costs, min_trades_oos) for c in combos]

    passes = [r for r in results if r["oos_verdict"] == "PASS"]
    pass_fraction = round(len(passes) / len(results), 3) if results else 0.0
    oos_evs = [r["oos_net_ev_per_trade_bps"] for r in results]
    median_oos_ev = round(statistics.median(oos_evs), 3) if oos_evs else 0.0

    if not passes or median_oos_ev <= 0:
        verdict = "FALSIFIED"
    elif pass_fraction >= ROBUST_PASS_FRACTION and median_oos_ev > 0:
        verdict = "ROBUST"
    else:
        verdict = "FRAGILE"

    best = max(results, key=lambda r: r["oos_net_ev_per_trade_bps"]) if results else None

    return {
        "schema": "p2_044c_swing_param_robustness/v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "decision_grade": decision_grade,
        "disclaimer": (
            "Anti-overfitting sweep. ROBUST means the edge survives out-of-sample across "
            "many parameter combos, not one. Even ROBUST does not authorize live — it gates "
            "the P2-044B decision-grade run + paper reproduction. decision_grade=false => "
            "synthetic mechanics smoke test only."
        ),
        "lane": "alpaca_equities_etf_swing",
        "n_bars": len(bars),
        "in_sample_fraction": IN_SAMPLE_FRACTION,
        "n_param_combos": len(results),
        "oos_pass_count": len(passes),
        "oos_pass_fraction": pass_fraction,
        "median_oos_net_ev_per_trade_bps": median_oos_ev,
        "robust_pass_fraction_threshold": ROBUST_PASS_FRACTION,
        "best_oos_combo": best,
        "verdict": verdict,
        "authorizes_live": False,
        "results": results,
    }


def render_markdown(v: Dict[str, Any]) -> str:
    lines = [
        "# P2-044C — Swing Parameter Robustness Sweep",
        "",
        f"Generated: {v['generated_utc']}",
        f"Lane: {v['lane']} · bars: {v['n_bars']} · combos: {v['n_param_combos']}",
        f"**Robustness verdict: {v['verdict']}**  ·  decision_grade={v['decision_grade']}  ·  "
        f"authorizes_live={v['authorizes_live']}",
        "",
        f"> {v['disclaimer']}",
        "",
        f"OOS pass fraction: {v['oos_pass_fraction']} (threshold {v['robust_pass_fraction_threshold']}) · "
        f"median OOS net EV/trade: {v['median_oos_net_ev_per_trade_bps']} bps",
        "",
    ]
    if v["best_oos_combo"]:
        b = v["best_oos_combo"]
        lines += [
            "Best OOS combo:",
            f"- params: {b['params']}",
            f"- OOS verdict {b['oos_verdict']}, net EV/trade {b['oos_net_ev_per_trade_bps']} bps, "
            f"trades {b['oos_trades']}, PF {b['oos_profit_factor']}",
            "",
        ]
    return "\n".join(lines)


def write_outputs(v: Dict[str, Any], out_dir: Path) -> Dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    jp = out_dir / "p2_044c_swing_param_robustness.json"
    mp = out_dir / "p2_044c_swing_param_robustness.md"
    jp.write_text(json.dumps(v, indent=2))
    mp.write_text(render_markdown(v))
    return {"json": str(jp), "md": str(mp)}


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="P2-044C swing parameter robustness sweep")
    p.add_argument("--csv", help="Daily OHLCV CSV. REAL data => decision-grade.")
    p.add_argument("--out-dir", default="/tmp")
    p.add_argument("--min-trades-oos", type=int, default=30)
    p.add_argument("--print", action="store_true")
    args = p.parse_args(argv)

    if args.csv:
        bars = gate.load_bars_csv(Path(args.csv))
        decision_grade = True
        min_trades_oos = args.min_trades_oos
    else:
        print("[p2-044c] WARNING: no --csv. SYNTHETIC bars, mechanics smoke test only.")
        bars = gate.synthetic_bars(n=900, seed=5)
        decision_grade = False
        min_trades_oos = 5

    v = run_robustness(bars, gate.CostModel(), min_trades_oos=min_trades_oos,
                       decision_grade=decision_grade)
    paths = write_outputs(v, Path(args.out_dir))
    if args.print:
        print(render_markdown(v))
    print(f"[p2-044c] verdict={v['verdict']} decision_grade={v['decision_grade']} "
          f"oos_pass_fraction={v['oos_pass_fraction']}")
    print(f"[p2-044c] wrote {paths['json']}")
    print(f"[p2-044c] wrote {paths['md']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
