#!/usr/bin/env python3
"""
analyze_live_journal.py — P2-044H real-evidence diagnosis: fees vs no-edge.

Reads the bot's ACTUAL live trade journal (journal_coinbase_crypto.csv), computes
each trade's GROSS return (before fees) from the realized fill/exit prices, and
then re-prices the whole record under several venue fee models. This answers the
only question that matters for "can this ever be profitable":

  - If GROSS return per trade is ~0 or negative, the entries have NO EDGE, and
    NO venue/fee change and NO patch can fix it. The honest move is a new signal
    thesis or stop.
  - If GROSS is meaningfully positive but fees eat it, then a cheaper venue
    genuinely helps and there is a real path.

GOVERNANCE: offline only, read-only on the journal, no broker, no network, no
runtime mutation. Writes a report to /tmp.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BPS = 1e4

# Venue round-trip cost as a FRACTION of notional (fees only; confirm live schedules).
VENUE_ROUND_TRIP = {
    "coinbase_taker": 0.0240,   # ~1.20%/side
    "coinbase_maker": 0.0120,   # ~0.60%/side
    "alpaca_crypto":  0.0050,   # ~0.25%/side
    "alpaca_equities": 0.0000,  # commission-free (spread/slippage only, ~0)
}


@dataclass
class TradeRow:
    symbol: str
    strategy: str
    qty: float
    fill_price: float
    exit_price: float
    gross_pnl: float
    fees_paid: float
    position_value: float
    gross_return: float  # gross_pnl / position_value


def _f(x: Optional[str]) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def load_exits(csv_path: Path) -> List[TradeRow]:
    rows: List[TradeRow] = []
    with csv_path.open(newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("action") or "").strip().upper() != "EXIT":
                continue
            qty = _f(r.get("qty"))
            fill = _f(r.get("fill_price"))
            exitp = _f(r.get("exit_price"))
            gross = _f(r.get("gross_pnl"))
            fees = _f(r.get("fees_paid"))
            pos_val = qty * fill if (qty > 0 and fill > 0) else _f(r.get("notional"))
            if pos_val <= 0:
                continue
            rows.append(TradeRow(
                symbol=(r.get("symbol") or "").strip(),
                strategy=(r.get("strategy") or "").strip(),
                qty=qty, fill_price=fill, exit_price=exitp,
                gross_pnl=gross, fees_paid=fees, position_value=pos_val,
                gross_return=gross / pos_val,
            ))
    return rows


def _t_stat(values: List[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    sd = statistics.pstdev(values)
    if sd == 0:
        return 0.0
    return statistics.fmean(values) / (sd / math.sqrt(n))


def analyze(rows: List[TradeRow]) -> Dict[str, Any]:
    n = len(rows)
    gross_returns = [r.gross_return for r in rows]
    total_pos = sum(r.position_value for r in rows)
    total_gross = sum(r.gross_pnl for r in rows)
    total_fees_actual = sum(r.fees_paid for r in rows)

    mean_gross = statistics.fmean(gross_returns) if n else 0.0
    median_gross = statistics.median(gross_returns) if n else 0.0
    std_gross = statistics.pstdev(gross_returns) if n > 1 else 0.0
    t_stat = _t_stat(gross_returns)
    gross_wins = sum(1 for g in gross_returns if g > 0)

    # Re-price under each venue: net = total_gross - round_trip_rate * total_position_value.
    venue_net = {}
    for venue, rt in VENUE_ROUND_TRIP.items():
        venue_net[venue] = {
            "round_trip_rate": rt,
            "modeled_fees": round(rt * total_pos, 4),
            "net_usd": round(total_gross - rt * total_pos, 4),
            "net_per_trade_usd": round((total_gross - rt * total_pos) / n, 5) if n else 0.0,
        }

    # Verdict: is the binding constraint EDGE or FEES?
    # mean gross return per trade vs the CHEAPEST venue's per-trade cost.
    cheapest_rt = min(VENUE_ROUND_TRIP.values())
    if mean_gross <= 0:
        diagnosis = "NO_EDGE"
        explanation = (
            "Mean GROSS return per trade is <= 0 BEFORE any fees. The entries have no "
            "directional edge. No venue, fee tier, or parameter patch can make a "
            "zero/negative-edge signal profitable. A different signal thesis (or stop) is required."
        )
    elif mean_gross <= cheapest_rt:
        diagnosis = "EDGE_TOO_SMALL_FOR_ANY_VENUE"
        explanation = (
            f"Mean gross edge ({mean_gross*100:.3f}%/trade) is positive but does not even "
            f"clear the cheapest venue's round-trip cost ({cheapest_rt*100:.3f}%). Not profitable "
            "anywhere without a larger edge or far lower turnover."
        )
    else:
        diagnosis = "EDGE_EXISTS_FEES_BINDING"
        explanation = (
            f"Mean gross edge ({mean_gross*100:.3f}%/trade) exceeds the cheapest venue cost "
            f"({cheapest_rt*100:.3f}%). A cheaper venue is a REAL path; re-test with the gate."
        )

    return {
        "schema": "p2_044h_live_journal_diagnosis/v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "disclaimer": "Real-evidence diagnosis from the actual live journal. Read-only. Not live authorization.",
        "n_trades": n,
        "total_position_value_usd": round(total_pos, 4),
        "total_gross_pnl_usd": round(total_gross, 4),
        "total_fees_actual_usd": round(total_fees_actual, 4),
        "actual_net_usd": round(total_gross - total_fees_actual, 4),
        "gross_return_per_trade": {
            "mean_pct": round(mean_gross * 100, 4),
            "median_pct": round(median_gross * 100, 4),
            "stdev_pct": round(std_gross * 100, 4),
            "t_stat_vs_zero": round(t_stat, 3),
            "gross_win_rate": round(gross_wins / n, 4) if n else 0.0,
        },
        "venue_repricing": venue_net,
        "diagnosis": diagnosis,
        "explanation": explanation,
    }


def render_markdown(a: Dict[str, Any]) -> str:
    g = a["gross_return_per_trade"]
    lines = [
        "# P2-044H — Live Journal Diagnosis (real data): fees vs no-edge",
        "",
        f"Generated: {a['generated_utc']}",
        f"> {a['disclaimer']}",
        "",
        f"Trades analyzed: **{a['n_trades']}** · total position value ${a['total_position_value_usd']:.2f}",
        f"Total GROSS P&L (before fees): **${a['total_gross_pnl_usd']:.4f}**",
        f"Total fees actually paid: ${a['total_fees_actual_usd']:.4f}",
        f"Actual net: **${a['actual_net_usd']:.4f}**",
        "",
        "## Gross edge per trade (BEFORE fees) — the real question",
        f"- mean: **{g['mean_pct']}%**  · median: {g['median_pct']}%  · stdev: {g['stdev_pct']}%",
        f"- t-stat vs 0: **{g['t_stat_vs_zero']}**  · gross win rate: {g['gross_win_rate']*100:.1f}%",
        "",
        "## What each venue's fees would have produced (on the SAME real trades)",
        "| Venue | Round-trip | Modeled fees | Net USD | Net/trade |",
        "|---|---:|---:|---:|---:|",
    ]
    for v, d in a["venue_repricing"].items():
        lines.append(
            f"| {v} | {d['round_trip_rate']*100:.2f}% | ${d['modeled_fees']:.4f} | "
            f"${d['net_usd']:.4f} | ${d['net_per_trade_usd']:.5f} |"
        )
    lines += [
        "",
        f"## Diagnosis: **{a['diagnosis']}**",
        "",
        a["explanation"],
        "",
    ]
    return "\n".join(lines)


def write_outputs(a: Dict[str, Any], out_dir: Path) -> Dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    jp = out_dir / "p2_044h_live_journal_diagnosis.json"
    mp = out_dir / "p2_044h_live_journal_diagnosis.md"
    jp.write_text(json.dumps(a, indent=2))
    mp.write_text(render_markdown(a))
    return {"json": str(jp), "md": str(mp)}


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="P2-044H live journal fees-vs-edge diagnosis")
    p.add_argument("--journal", default="journal_coinbase_crypto.csv")
    p.add_argument("--out-dir", default="/tmp")
    p.add_argument("--print", action="store_true")
    args = p.parse_args(argv)

    rows = load_exits(Path(args.journal))
    if not rows:
        print(f"[p2-044h] no EXIT trades found in {args.journal}")
        return 1
    a = analyze(rows)
    paths = write_outputs(a, Path(args.out_dir))
    if args.print:
        print(render_markdown(a))
    print(f"[p2-044h] diagnosis={a['diagnosis']} trades={a['n_trades']}")
    print(f"[p2-044h] wrote {paths['json']}")
    print(f"[p2-044h] wrote {paths['md']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
