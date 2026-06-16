#!/usr/bin/env python3
"""
venue_compare.py — P2-044G multi-venue cost comparison for the swing lane.

Runs the SAME swing strategy through the P2-044B real-cost gate under several
venue cost models, side by side, so the fee hurdle is explicit and comparable.

VENUES (cost models; per-side bps — CONFIRM live schedules before deciding):
  coinbase_taker   : ~1.20%/side  (current live behavior; reference)
  coinbase_maker   : ~0.60%/side  (post-only; realistic Coinbase improvement)
  alpaca_crypto    : ~0.25%/side  (same coins, cheaper venue; you have keys)
  alpaca_equities  : 0% commission (ETF; lowest hurdle, not crypto)

DATA
- Crypto venues use the crypto CSV; the equities venue uses the equities CSV.
- If only --crypto-csv is given, all venues run on it in FEE-ISOLATION mode
  (holds the price path constant to isolate the fee effect) and the equities row
  is flagged data_mismatch=true (its price series isn't really an ETF).
- No CSV at all => synthetic smoke, decision_grade=false (never GO).

GOVERNANCE: offline only, no broker, no network, no runtime mutation; /tmp output.
This compares FEE FEASIBILITY; it does not authorize live. A PASS only earns the
P2-044D combined run + paper reproduction.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import equities_swing_backtest_gate as gate


# name -> (CostModel, asset_class)  asset_class in {"crypto","equities"}
VENUES: Dict[str, Dict[str, Any]] = {
    "coinbase_taker": {
        "costs": gate.CostModel(commission_bps_per_side=120.0, spread_bps=5.0, slippage_bps_per_side=5.0),
        "asset_class": "crypto",
        "note": "Current live behavior. ~1.20%/side taker (Intro-1). Reference only.",
    },
    "coinbase_maker": {
        "costs": gate.CostModel(commission_bps_per_side=60.0, spread_bps=5.0, slippage_bps_per_side=3.0),
        "asset_class": "crypto",
        "note": "Post-only maker ~0.60%/side. Realistic Coinbase improvement; assumes fills.",
    },
    "alpaca_crypto": {
        "costs": gate.CostModel(commission_bps_per_side=25.0, spread_bps=4.0, slippage_bps_per_side=4.0),
        "asset_class": "crypto",
        "note": "Same coins, ~0.25%/side taker. You already have Alpaca keys. CONFIRM schedule.",
    },
    "alpaca_equities": {
        "costs": gate.CostModel(commission_bps_per_side=0.0, spread_bps=1.0, slippage_bps_per_side=2.0),
        "asset_class": "equities",
        "note": "Commission-free ETF. Lowest hurdle; market-hours, PDT-aware, not crypto.",
    },
}


def compare(
    crypto_bars: Optional[List[gate.Bar]],
    equities_bars: Optional[List[gate.Bar]] = None,
    params: Optional[gate.SwingParams] = None,
    n_folds: int = gate.DEFAULT_N_FOLDS,
    min_trades: int = gate.MIN_TRADES,
    decision_grade: bool = True,
) -> Dict[str, Any]:
    params = params or gate.SwingParams()
    rows: List[Dict[str, Any]] = []

    for name, spec in VENUES.items():
        costs = spec["costs"]
        if spec["asset_class"] == "equities":
            bars = equities_bars if equities_bars is not None else crypto_bars
            data_mismatch = equities_bars is None
        else:
            bars = crypto_bars
            data_mismatch = False
        if bars is None:
            continue
        v = gate.evaluate(bars, params, costs, n_folds=n_folds,
                          min_trades=min_trades, decision_grade=decision_grade)
        rows.append({
            "venue": name,
            "asset_class": spec["asset_class"],
            "round_trip_cost_bps": round(costs.round_trip_cost_bps, 2),
            "n_trades": v["metrics"]["n_trades"],
            "net_ev_per_trade_bps": v["metrics"]["net_ev_per_trade_bps"],
            "gross_ev_per_trade_bps": v["metrics"]["gross_ev_per_trade_bps"],
            "total_net_bps": v["metrics"]["total_net_bps"],
            "profit_factor": v["metrics"]["profit_factor"],
            "buy_and_hold_bps": v["baselines"]["buy_and_hold_bps"],
            "verdict": v["verdict"],
            "fail_reasons": v["fail_reasons"],
            "data_mismatch": data_mismatch,
            "note": spec["note"],
        })

    passing = [r for r in rows if r["verdict"] == "PASS"]
    ranked = sorted(rows, key=lambda r: r["net_ev_per_trade_bps"], reverse=True)
    if passing:
        best = max(passing, key=lambda r: r["net_ev_per_trade_bps"])
        recommendation = (
            f"{best['venue']} is the only/best PASS (net EV/trade "
            f"{best['net_ev_per_trade_bps']} bps). Carry it to P2-044D + paper. Live stays NO-GO."
        )
    else:
        top = ranked[0] if ranked else None
        recommendation = (
            "No venue PASSES the gate on this data. Least-bad by net EV/trade: "
            f"{top['venue']} ({top['net_ev_per_trade_bps']} bps) — still NOT live-worthy. "
            "Either improve the strategy/horizon, drop to the cheapest venue, or park."
            if top else "No data."
        )

    return {
        "schema": "p2_044g_venue_compare/v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "decision_grade": decision_grade,
        "disclaimer": (
            "Compares FEE feasibility of the same swing strategy across venue cost models. "
            "Not live authorization. A PASS only earns the P2-044D combined run + paper repro."
        ),
        "params": asdict(params),
        "results": ranked,
        "n_passing": len(passing),
        "recommendation": recommendation,
        "authorizes_live": False,
    }


def render_markdown(c: Dict[str, Any]) -> str:
    lines = [
        "# P2-044G — Venue Cost Comparison (swing lane)",
        "",
        f"Generated: {c['generated_utc']} · decision_grade={c['decision_grade']}",
        "",
        f"> {c['disclaimer']}",
        "",
        "| Venue | Asset | Cost bps RT | Trades | Net EV/trade | Total net | PF | Buy&Hold | Verdict |",
        "|---|---|---:|---:|---:|---:|---:|---:|:--:|",
    ]
    for r in c["results"]:
        flag = " *" if r["data_mismatch"] else ""
        lines.append(
            f"| {r['venue']}{flag} | {r['asset_class']} | {r['round_trip_cost_bps']:.0f} | "
            f"{r['n_trades']} | {r['net_ev_per_trade_bps']} | {r['total_net_bps']} | "
            f"{r['profit_factor']} | {r['buy_and_hold_bps']} | {r['verdict']} |"
        )
    lines += [
        "",
        "`*` = data_mismatch: equities cost model run on the crypto price series "
        "(fee-isolation only; supply --equities-csv for a true ETF comparison).",
        "",
        f"**Passing venues: {c['n_passing']}**",
        "",
        f"**Recommendation:** {c['recommendation']}",
        "",
    ]
    return "\n".join(lines)


def write_outputs(c: Dict[str, Any], out_dir: Path) -> Dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    jp = out_dir / "p2_044g_venue_compare.json"
    mp = out_dir / "p2_044g_venue_compare.md"
    jp.write_text(json.dumps(c, indent=2))
    mp.write_text(render_markdown(c))
    return {"json": str(jp), "md": str(mp)}


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="P2-044G multi-venue cost comparison")
    p.add_argument("--crypto-csv", help="Daily OHLCV for crypto venues (Coinbase/Alpaca crypto).")
    p.add_argument("--equities-csv", help="Daily OHLCV for the equities venue (ETF).")
    p.add_argument("--out-dir", default="/tmp")
    p.add_argument("--print", action="store_true")
    args = p.parse_args(argv)

    if args.crypto_csv or args.equities_csv:
        crypto = gate.load_bars_csv(Path(args.crypto_csv)) if args.crypto_csv else None
        equities = gate.load_bars_csv(Path(args.equities_csv)) if args.equities_csv else None
        c = compare(crypto, equities, decision_grade=True)
    else:
        print("[p2-044g] WARNING: no CSV. SYNTHETIC bars; decision_grade=false (never live).")
        crypto = gate.synthetic_bars(n=900, seed=5)
        c = compare(crypto, None, min_trades=20, decision_grade=False)

    paths = write_outputs(c, Path(args.out_dir))
    if args.print:
        print(render_markdown(c))
    print(f"[p2-044g] passing={c['n_passing']} decision_grade={c['decision_grade']}")
    print(f"[p2-044g] wrote {paths['json']}")
    print(f"[p2-044g] wrote {paths['md']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
