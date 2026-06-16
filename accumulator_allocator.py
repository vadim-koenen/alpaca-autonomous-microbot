#!/usr/bin/env python3
"""
accumulator_allocator.py — P2-046A: offline accumulation/allocation backtest.

PIVOT CONTEXT. Three signal lanes were falsified on real data (price-technical
P2-044H, news P2-045, equities-swing P2-044D): retail directional prediction on
liquid public markets has no edge. The bot's JOB therefore changes from *trader*
to *accumulator/allocator* — DCA into a diversified basket, hold, rebalance, and
buy bigger tranches when an asset is cheap relative to its own long-run trend.
That last bit ("buy at the lows") is MECHANICAL, not predictive: it just buys more
cheap units with reserved dry powder, so it needs no edge.

This harness tests, OFFLINE and capital-neutral, whether the valuation overlay
actually beats plain DCA across a basket — BEFORE we build it live. It is the
laboratory check that keeps us out of the patch-loop.

WHAT IT DOES (all causal — only past bars inform any decision):
- Loads N asset daily-OHLCV CSVs (date,open,high,low,close,volume).
- Runs identical periodic contributions through three strategies:
    * lump_sum     — deploy everything on day one (reference).
    * plain_dca    — deploy each contribution immediately at target weights.
    * overlay_dca  — deploy a valuation-scaled amount vs the asset's long-run MA,
                     banking the remainder as dry powder, drawing it down on dips.
  Same total contributions for plain vs overlay => a FAIR, budget-neutral test.
- Optional drift-band rebalance (off by default so the overlay effect is isolated).
- Reports per-strategy: final value, return multiple, avg cost basis, max drawdown.
- Pre-registered verdict: VALUATION_OVERLAY_HELPS / NO_BENEFIT / INSUFFICIENT_DATA.

GOVERNANCE: offline only. No broker, no orders, no runtime mutation, no network.
A positive result authorizes only further offline design + paper repro, never live.
/tmp output. Pure stdlib; the maths are unit-tested with synthetic series.
"""

from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import equities_swing_backtest_gate as gate  # reuse Bar, load_bars_csv, synthetic_bars

# --- Pre-registered constants (set BEFORE seeing any real result) -------------
MA_WINDOW = 200             # long-run trend window (trading days)
PERIOD_DAYS = 7             # contribute/act weekly
CONTRIB_PER_PERIOD = 1.0    # unit contribution; absolute value is irrelevant
BUY_COST_BPS = 10.0         # spread+slippage on each deployment (per side)
MIN_PERIODS = 26            # need >= ~half a year of weekly actions to judge
OVERLAY_HELP_MARGIN = 0.02  # overlay must beat plain by >=2% relative value-multiple
                            # AND lower avg cost on a majority of assets

# Valuation bands: ratio = price / long-run MA -> deployment multiplier.
# >trend: deploy less (bank dry powder). <trend: deploy more (spend reserve).
DEFAULT_BANDS: Tuple[Tuple[float, float], ...] = (
    (1.10, 0.5),   # >10% above trend -> half-size buys
    (0.95, 1.0),   # near trend -> normal
    (0.80, 2.0),   # 5-20% below trend -> double
    (0.0, 3.0),    # >20% below trend -> triple
)


@dataclass
class StrategyResult:
    name: str
    total_contributed: float
    deployed: float
    leftover_cash: float
    final_value: float
    value_multiple: float
    avg_cost: Dict[str, float]          # dollar-weighted cost basis per symbol
    units: Dict[str, float]
    max_drawdown: float                 # fraction (0..1) on the portfolio value path
    n_periods: int


# --- pure helpers (unit-tested) ----------------------------------------------

def moving_average_causal(closes: List[float], i: int, window: int) -> Optional[float]:
    """Mean of the `window` closes STRICTLY BEFORE index i. None until warmed up.
    Strictly-before keeps it causal: today's decision never peeks at today's close
    beyond the price we transact at."""
    if i < window:
        return None
    return statistics.fmean(closes[i - window:i])


def valuation_multiplier(ratio: float, bands: Tuple[Tuple[float, float], ...] = DEFAULT_BANDS) -> float:
    """Map price/MA ratio to a deployment multiplier via descending thresholds."""
    for threshold, mult in bands:
        if ratio >= threshold:
            return mult
    return bands[-1][1]


def common_calendar(series: Dict[str, List[gate.Bar]]) -> List[str]:
    """Sorted dates present in EVERY asset (intersection) — a shared trade calendar."""
    if not series:
        return []
    sets = [set(b.date[:10] for b in bars) for bars in series.values()]
    common = set.intersection(*sets) if sets else set()
    return sorted(common)


def _max_drawdown(path: List[float]) -> float:
    peak = float("-inf")
    mdd = 0.0
    for v in path:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return round(mdd, 4)


# --- core simulation ----------------------------------------------------------

def simulate(
    series: Dict[str, List[gate.Bar]],
    weights: Dict[str, float],
    *,
    mode: str = "plain",                 # 'plain' | 'overlay'
    period_days: int = PERIOD_DAYS,
    contrib: float = CONTRIB_PER_PERIOD,
    ma_window: int = MA_WINDOW,
    bands: Tuple[Tuple[float, float], ...] = DEFAULT_BANDS,
    buy_cost_bps: float = BUY_COST_BPS,
    rebalance_every: int = 0,            # 0 = off
    rebalance_band: float = 0.0,
) -> StrategyResult:
    """Capital-neutral accumulation sim. Every mode receives the SAME contributions;
    only deployment timing differs. Per-asset cash reserve makes the overlay
    self-financing (banks above trend, spends on dips)."""
    dates = common_calendar(series)
    closes = {s: {b.date[:10]: b.c for b in bars} for s, bars in series.items()}
    # per-symbol ordered closes for causal MA
    ordered = {s: [closes[s][d] for d in dates] for s in series}

    syms = list(weights.keys())
    wsum = sum(weights.values()) or 1.0
    w = {s: weights[s] / wsum for s in syms}

    cash = {s: 0.0 for s in syms}
    units = {s: 0.0 for s in syms}
    deployed = {s: 0.0 for s in syms}
    contributed = 0.0
    cost_factor = 1.0 - buy_cost_bps / 1e4
    value_path: List[float] = []

    action_idxs = list(range(0, len(dates), max(1, period_days)))
    n_periods = len(action_idxs)

    for step, i in enumerate(action_idxs):
        d = dates[i]
        for s in syms:
            price = ordered[s][i]
            add = contrib * w[s]
            contributed += add
            cash[s] += add
            if mode == "overlay":
                ma = moving_average_causal(ordered[s], i, ma_window)
                mult = valuation_multiplier(price / ma, bands) if ma else 1.0
                target = contrib * w[s] * mult
                spend = min(cash[s], max(0.0, target))
            else:  # plain
                spend = cash[s]
            if spend > 0 and price > 0:
                units[s] += spend * cost_factor / price
                cash[s] -= spend
                deployed[s] += spend
        # optional rebalance toward target weights
        if rebalance_every and step > 0 and step % rebalance_every == 0:
            _rebalance(units, ordered, i, w, rebalance_band, cost_factor)
        value_path.append(sum(units[s] * ordered[s][i] for s in syms) + sum(cash.values()))

    last = {s: ordered[s][-1] for s in syms}
    final_value = sum(units[s] * last[s] for s in syms) + sum(cash.values())
    total_deployed = sum(deployed.values())
    avg_cost = {s: round(deployed[s] / units[s], 6) if units[s] > 0 else 0.0 for s in syms}
    return StrategyResult(
        name=mode,
        total_contributed=round(contributed, 6),
        deployed=round(total_deployed, 6),
        leftover_cash=round(sum(cash.values()), 6),
        final_value=round(final_value, 6),
        value_multiple=round(final_value / contributed, 6) if contributed else 0.0,
        avg_cost=avg_cost,
        units={s: round(units[s], 8) for s in syms},
        max_drawdown=_max_drawdown(value_path),
        n_periods=n_periods,
    )


def _rebalance(units, ordered, i, w, band, cost_factor) -> None:
    """Drift-band rebalance: trim assets above target weight, add to those below."""
    vals = {s: units[s] * ordered[s][i] for s in units}
    total = sum(vals.values())
    if total <= 0:
        return
    for s in units:
        target = total * w[s]
        drift = (vals[s] - target) / total
        if abs(drift) <= band:
            continue
        price = ordered[s][i]
        if price <= 0:
            continue
        delta_val = target - vals[s]          # +ve buy, -ve sell
        if delta_val > 0:
            units[s] += delta_val * cost_factor / price
        else:
            units[s] += delta_val / price * (2 - cost_factor)  # sell pays cost too


# --- evaluation / verdict -----------------------------------------------------

def evaluate(
    series: Dict[str, List[gate.Bar]],
    weights: Optional[Dict[str, float]] = None,
    *,
    decision_grade: bool = True,
    rebalance_every: int = 0,
    rebalance_band: float = 0.25,
    **kw,
) -> Dict[str, Any]:
    weights = weights or {s: 1.0 for s in series}
    common = common_calendar(series)
    res_plain = simulate(series, weights, mode="plain", **kw)
    res_overlay = simulate(series, weights, mode="overlay", **kw)
    reb = None
    if rebalance_every:
        reb = simulate(series, weights, mode="overlay",
                       rebalance_every=rebalance_every, rebalance_band=rebalance_band, **kw)

    n = res_plain.n_periods
    # per-asset: did overlay lower the cost basis?
    improved = sum(1 for s in weights
                   if res_overlay.avg_cost.get(s, 0) and res_plain.avg_cost.get(s, 0)
                   and res_overlay.avg_cost[s] < res_plain.avg_cost[s])
    rel_gain = ((res_overlay.value_multiple - res_plain.value_multiple)
                / res_plain.value_multiple) if res_plain.value_multiple else 0.0

    if len(common) < MIN_PERIODS * PERIOD_DAYS or n < MIN_PERIODS:
        verdict = "INSUFFICIENT_DATA"
        why = (f"Only {n} action periods over {len(common)} common bars; "
               f"need >= {MIN_PERIODS}. Get more history / more overlapping assets.")
    elif rel_gain >= OVERLAY_HELP_MARGIN and improved >= (len(weights) + 1) // 2:
        verdict = "VALUATION_OVERLAY_HELPS"
        why = (f"Overlay return-multiple {res_overlay.value_multiple} vs plain "
               f"{res_plain.value_multiple} (+{round(rel_gain*100,1)}%); lower cost basis on "
               f"{improved}/{len(weights)} assets. Mechanical (no prediction). Build it — "
               "still offline->paper->bounded-live; never live on this alone.")
    else:
        verdict = "NO_BENEFIT"
        why = (f"Overlay {res_overlay.value_multiple} vs plain {res_plain.value_multiple} "
               f"(+{round(rel_gain*100,1)}%); cost basis improved on {improved}/{len(weights)} "
               "assets — below the pre-registered bar. Plain DCA is the honest default here.")

    def _r(r: StrategyResult) -> Dict[str, Any]:
        return {
            "strategy": r.name, "total_contributed": r.total_contributed,
            "deployed": r.deployed, "leftover_cash": r.leftover_cash,
            "final_value": r.final_value, "value_multiple": r.value_multiple,
            "avg_cost": r.avg_cost, "max_drawdown": r.max_drawdown, "n_periods": r.n_periods,
        }

    out = {
        "schema": "p2_046a_accumulator_allocator/v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "decision_grade": decision_grade,
        "disclaimer": "Offline accumulation backtest. Not live authorization. "
                      "A positive result earns offline design + paper repro only.",
        "assets": list(weights.keys()),
        "weights": {s: round(weights[s], 4) for s in weights},
        "common_bars": len(common),
        "ma_window": MA_WINDOW, "period_days": PERIOD_DAYS,
        "buy_cost_bps": BUY_COST_BPS,
        "results": {
            "plain_dca": _r(res_plain),
            "overlay_dca": _r(res_overlay),
            **({"overlay_dca_rebalanced": _r(reb)} if reb else {}),
        },
        "overlay_vs_plain_rel_gain": round(rel_gain, 4),
        "assets_with_lower_cost_basis": improved,
        "verdict": verdict,
        "explanation": why,
        "authorizes_live": False,
    }
    return out


def render_markdown(r: Dict[str, Any]) -> str:
    lines = [
        "# P2-046A — Accumulator/Allocator Backtest (DCA vs valuation overlay)",
        "",
        f"Generated: {r['generated_utc']} · decision_grade={r['decision_grade']}",
        f"> {r['disclaimer']}",
        "",
        f"Assets: {', '.join(r['assets'])} · common bars: {r['common_bars']} · "
        f"MA {r['ma_window']}d · contribute every {r['period_days']}d · buy cost {r['buy_cost_bps']} bps",
        "",
        "| Strategy | Contributed | Deployed | Final value | Multiple | Max DD |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for key in ("plain_dca", "overlay_dca", "overlay_dca_rebalanced"):
        if key in r["results"]:
            x = r["results"][key]
            lines.append(f"| {key} | {x['total_contributed']:.2f} | {x['deployed']:.2f} | "
                         f"{x['final_value']:.2f} | {x['value_multiple']:.2f}x | "
                         f"{x['max_drawdown']*100:.1f}% |")
    lines += [
        "",
        f"Overlay vs plain: **{r['overlay_vs_plain_rel_gain']*100:+.1f}%** return-multiple; "
        f"lower cost basis on **{r['assets_with_lower_cost_basis']}/{len(r['assets'])}** assets.",
        "",
        f"## Verdict: **{r['verdict']}**",
        "",
        r["explanation"],
        "",
    ]
    return "\n".join(lines)


def write_outputs(r: Dict[str, Any], out_dir: Path) -> Dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    jp = out_dir / "p2_046a_accumulator_allocator.json"
    mp = out_dir / "p2_046a_accumulator_allocator.md"
    jp.write_text(json.dumps(r, indent=2))
    mp.write_text(render_markdown(r))
    return {"json": str(jp), "md": str(mp)}


def _parse_csv_args(items: List[str]) -> Dict[str, str]:
    """--csv SYM=path ... -> {SYM: path}."""
    out: Dict[str, str] = {}
    for it in items:
        if "=" not in it:
            raise SystemExit(f"--csv expects SYMBOL=path, got '{it}'")
        sym, path = it.split("=", 1)
        out[sym.strip().upper()] = path.strip()
    return out


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="P2-046A accumulator/allocator backtest")
    p.add_argument("--csv", nargs="+", help="One or more SYMBOL=path daily-OHLCV CSVs.")
    p.add_argument("--weights", help="Comma list SYM:w,... (default equal weight).")
    p.add_argument("--rebalance-every", type=int, default=0, help="Rebalance every N periods (0=off).")
    p.add_argument("--rebalance-band", type=float, default=0.25)
    p.add_argument("--out-dir", default="/tmp")
    p.add_argument("--print", action="store_true")
    args = p.parse_args(argv)

    if args.csv:
        paths = _parse_csv_args(args.csv)
        series = {s: gate.load_bars_csv(Path(pth)) for s, pth in paths.items()}
        decision_grade = True
    else:  # synthetic smoke: V-shaped + uptrend, NOT decision grade
        series = {"DIP": gate.synthetic_bars(420, seed=7), "UP": gate.synthetic_bars(420, seed=11)}
        decision_grade = False

    weights: Optional[Dict[str, float]] = None
    if args.weights:
        weights = {}
        for kv in args.weights.split(","):
            s, w = kv.split(":")
            weights[s.strip().upper()] = float(w)

    r = evaluate(series, weights, decision_grade=decision_grade,
                 rebalance_every=args.rebalance_every, rebalance_band=args.rebalance_band)
    paths = write_outputs(r, Path(args.out_dir))
    if args.print:
        print(render_markdown(r))
    print(f"[p2-046a] verdict={r['verdict']} decision_grade={r['decision_grade']}")
    print(f"[p2-046a] wrote {paths['json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
