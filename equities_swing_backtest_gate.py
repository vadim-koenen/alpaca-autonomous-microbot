#!/usr/bin/env python3
"""
equities_swing_backtest_gate.py — P2-044B offline real-cost walk-forward gate
for the recommended pivot lane: commission-free Alpaca equities/ETF, multi-day
SWING (PDT-safe). This is the make-or-break gate that must PASS before any live
restart of the pivoted strategy.

DESIGN PRINCIPLES (governance-aligned)
--------------------------------------
- OFFLINE ONLY. No broker, no network, no runtime mutation. Writes to /tmp.
- DATA-AGNOSTIC. Reads daily OHLCV from a CSV you supply on the Mac
  (columns: date,open,high,low,close,volume). The bot must NOT invent real-time
  prices: if no CSV is given, a clearly-labeled SYNTHETIC random-walk fixture is
  generated for a *mechanics smoke test only* and the verdict is stamped
  `decision_grade=false`. Synthetic results NEVER authorize anything.
- LONG ONLY. The account cannot short; no short logic here.
- PDT-SAFE by construction: daily bars => earliest exit is the next bar (>= 1 day
  hold), so trades are swings, not day-trades.
- REAL-COST. Commission-free, but spread + slippage are charged on both fills.
- HONEST GATE. PASS requires net-of-cost edge that beats BOTH no-trade and
  buy-and-hold, with a cost-multiple margin, profit factor, fold stability, and a
  minimum trade count. A FAIL is a valid and expected outcome.

PASS CRITERIA (all must hold; mirrors the P2-043D gate shape):
  1. n_trades >= MIN_TRADES
  2. net EV / trade (bps) > 0
  3. net EV / trade (bps) >= COST_MULTIPLE * round_trip_cost_bps
  4. profit factor >= MIN_PROFIT_FACTOR
  5. total net (bps) > buy-and-hold net (bps)        [beats buy-and-hold]
  6. total net (bps) > 0                              [beats no-trade]
  7. fold stability: fraction of folds with positive net EV >= MIN_FOLD_STABILITY
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------- gate thresholds
MIN_TRADES: int = 100
COST_MULTIPLE: float = 2.0
MIN_PROFIT_FACTOR: float = 1.3
MIN_FOLD_STABILITY: float = 0.6
DEFAULT_N_FOLDS: int = 5
BPS: float = 1e4


# ---------------------------------------------------------------- data model
@dataclass(frozen=True)
class Bar:
    date: str
    o: float
    h: float
    l: float
    c: float
    v: float = 0.0


@dataclass(frozen=True)
class SwingParams:
    breakout_lookback: int = 20      # Donchian: enter on close above N-day high
    atr_period: int = 14
    stop_atr_mult: float = 2.0
    target_atr_mult: float = 3.0
    max_hold_days: int = 10
    min_hold_days: int = 1           # PDT-safe; daily bars already guarantee >=1


@dataclass(frozen=True)
class CostModel:
    commission_bps_per_side: float = 0.0   # commission-free equities/ETF
    spread_bps: float = 1.0                # full bid/ask spread (bps); half charged per side
    slippage_bps_per_side: float = 2.0

    @property
    def round_trip_cost_bps(self) -> float:
        return 2.0 * self.commission_bps_per_side + self.spread_bps + 2.0 * self.slippage_bps_per_side

    def entry_fill(self, price: float) -> float:
        return price * (1.0 + (self.spread_bps / 2.0 + self.slippage_bps_per_side) / BPS)

    def exit_fill(self, price: float) -> float:
        return price * (1.0 - (self.spread_bps / 2.0 + self.slippage_bps_per_side) / BPS)


@dataclass
class Trade:
    entry_date: str
    exit_date: str
    entry_signal_price: float
    exit_signal_price: float
    entry_fill: float
    exit_fill: float
    hold_days: int
    exit_reason: str           # target | stop | max_hold | end_of_data
    gross_return_bps: float
    net_return_bps: float


# ---------------------------------------------------------------- indicators
def true_ranges(bars: List[Bar]) -> List[float]:
    out: List[float] = []
    for i, b in enumerate(bars):
        if i == 0:
            out.append(b.h - b.l)
        else:
            pc = bars[i - 1].c
            out.append(max(b.h - b.l, abs(b.h - pc), abs(b.l - pc)))
    return out


def atr_series(bars: List[Bar], period: int) -> List[Optional[float]]:
    tr = true_ranges(bars)
    out: List[Optional[float]] = [None] * len(bars)
    if len(bars) < period:
        return out
    # simple moving average of true range
    running = sum(tr[:period])
    out[period - 1] = running / period
    for i in range(period, len(bars)):
        running += tr[i] - tr[i - period]
        out[i] = running / period
    return out


def donchian_high(bars: List[Bar], i: int, lookback: int) -> Optional[float]:
    if i < lookback:
        return None
    return max(b.h for b in bars[i - lookback:i])


# ---------------------------------------------------------------- simulation
def simulate(bars: List[Bar], params: SwingParams, costs: CostModel) -> List[Trade]:
    """Long-only Donchian breakout swing. Enter at close of breakout bar; exit on
    stop / target / max-hold / end. Conservative: if both stop and target are
    inside a bar's range, assume the stop fills first."""
    trades: List[Trade] = []
    atr = atr_series(bars, params.atr_period)
    n = len(bars)
    i = max(params.breakout_lookback, params.atr_period)
    while i < n:
        dh = donchian_high(bars, i, params.breakout_lookback)
        a = atr[i]
        if dh is None or a is None or a <= 0:
            i += 1
            continue
        if bars[i].c > dh:  # breakout entry signal at close of bar i
            entry_signal = bars[i].c
            entry_fill = costs.entry_fill(entry_signal)
            stop = entry_signal - params.stop_atr_mult * a
            target = entry_signal + params.target_atr_mult * a
            exit_idx = None
            exit_signal = None
            reason = "end_of_data"
            j = i + 1
            last = min(n - 1, i + params.max_hold_days)
            while j <= last:
                bar = bars[j]
                hit_stop = bar.l <= stop
                hit_target = bar.h >= target
                if hit_stop:  # conservative ordering
                    exit_idx, exit_signal, reason = j, stop, "stop"
                    break
                if hit_target:
                    exit_idx, exit_signal, reason = j, target, "target"
                    break
                j += 1
            if exit_idx is None:
                exit_idx = last
                exit_signal = bars[last].c
                reason = "max_hold" if last == i + params.max_hold_days else "end_of_data"
            exit_fill = costs.exit_fill(exit_signal)
            gross_bps = (exit_signal / entry_signal - 1.0) * BPS
            # fills capture spread + slippage; subtract the round-trip COMMISSION
            # explicitly (charged on notional each side, not via the fill price).
            net_bps = (exit_fill / entry_fill - 1.0) * BPS - 2.0 * costs.commission_bps_per_side
            trades.append(Trade(
                entry_date=bars[i].date, exit_date=bars[exit_idx].date,
                entry_signal_price=entry_signal, exit_signal_price=exit_signal,
                entry_fill=entry_fill, exit_fill=exit_fill,
                hold_days=exit_idx - i, exit_reason=reason,
                gross_return_bps=round(gross_bps, 3), net_return_bps=round(net_bps, 3),
            ))
            i = exit_idx + 1  # no overlapping positions
        else:
            i += 1
    return trades


# ---------------------------------------------------------------- metrics
def buy_and_hold_net_bps(bars: List[Bar], costs: CostModel) -> float:
    if len(bars) < 2:
        return 0.0
    entry = costs.entry_fill(bars[0].c)
    exit_ = costs.exit_fill(bars[-1].c)
    return (exit_ / entry - 1.0) * BPS


def profit_factor(net_returns: List[float]) -> float:
    gains = sum(r for r in net_returns if r > 0)
    losses = -sum(r for r in net_returns if r < 0)
    if losses == 0:
        return math.inf if gains > 0 else 0.0
    return gains / losses


def trade_metrics(trades: List[Trade]) -> Dict[str, Any]:
    nets = [t.net_return_bps for t in trades]
    grosses = [t.gross_return_bps for t in trades]
    n = len(trades)
    wins = sum(1 for r in nets if r > 0)
    return {
        "n_trades": n,
        "win_rate": round(wins / n, 4) if n else 0.0,
        "net_ev_per_trade_bps": round(statistics.fmean(nets), 3) if n else 0.0,
        "gross_ev_per_trade_bps": round(statistics.fmean(grosses), 3) if n else 0.0,
        "total_net_bps": round(sum(nets), 3),
        "profit_factor": round(profit_factor(nets), 3) if n else 0.0,
        "exit_reason_counts": {
            r: sum(1 for t in trades if t.exit_reason == r)
            for r in ("target", "stop", "max_hold", "end_of_data")
        },
    }


def split_folds(bars: List[Bar], n_folds: int) -> List[List[Bar]]:
    if n_folds <= 1 or len(bars) < n_folds:
        return [bars]
    size = len(bars) // n_folds
    return [bars[k * size: (k + 1) * size if k < n_folds - 1 else len(bars)]
            for k in range(n_folds)]


def evaluate(
    bars: List[Bar],
    params: SwingParams,
    costs: CostModel,
    n_folds: int = DEFAULT_N_FOLDS,
    min_trades: int = MIN_TRADES,
    decision_grade: bool = True,
) -> Dict[str, Any]:
    all_trades = simulate(bars, params, costs)
    overall = trade_metrics(all_trades)
    bh = buy_and_hold_net_bps(bars, costs)
    rt_cost = costs.round_trip_cost_bps

    fold_evs: List[float] = []
    for fb in split_folds(bars, n_folds):
        ft = simulate(fb, params, costs)
        fold_evs.append(trade_metrics(ft)["net_ev_per_trade_bps"] if ft else 0.0)
    positive_folds = sum(1 for e in fold_evs if e > 0)
    fold_stability = round(positive_folds / len(fold_evs), 3) if fold_evs else 0.0

    checks = {
        "min_trades": overall["n_trades"] >= min_trades,
        "net_ev_positive": overall["net_ev_per_trade_bps"] > 0,
        "net_ev_ge_cost_multiple": overall["net_ev_per_trade_bps"] >= COST_MULTIPLE * rt_cost,
        "profit_factor_ok": overall["profit_factor"] >= MIN_PROFIT_FACTOR,
        "beats_buy_and_hold": overall["total_net_bps"] > bh,
        "beats_no_trade": overall["total_net_bps"] > 0,
        "fold_stable": fold_stability >= MIN_FOLD_STABILITY,
    }
    passed = all(checks.values())
    fail_reasons = [k for k, v in checks.items() if not v]

    return {
        "schema": "p2_044b_equities_swing_backtest_gate/v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "decision_grade": decision_grade,
        "disclaimer": (
            "Offline real-cost walk-forward gate. PASS authorizes only the NEXT step "
            "(paper reproduction), never a direct live restart. decision_grade=false "
            "means inputs were synthetic and the verdict is a mechanics smoke test only."
        ),
        "lane": "alpaca_equities_etf_swing (commission-free, multi-day swing, PDT-safe)",
        "n_bars": len(bars),
        "params": asdict(params),
        "costs": {**asdict(costs), "round_trip_cost_bps": round(rt_cost, 3)},
        "baselines": {"no_trade_bps": 0.0, "buy_and_hold_bps": round(bh, 3)},
        "metrics": overall,
        "fold_evs_bps": [round(e, 3) for e in fold_evs],
        "fold_stability": fold_stability,
        "thresholds": {
            "MIN_TRADES": min_trades, "COST_MULTIPLE": COST_MULTIPLE,
            "MIN_PROFIT_FACTOR": MIN_PROFIT_FACTOR, "MIN_FOLD_STABILITY": MIN_FOLD_STABILITY,
        },
        "checks": checks,
        "fail_reasons": fail_reasons,
        "verdict": "PASS" if passed else "FAIL",
        "authorizes_live": False,  # never directly; PASS -> paper repro -> bounded live A/B
    }


# ---------------------------------------------------------------- io
def load_bars_csv(path: Path) -> List[Bar]:
    bars: List[Bar] = []
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        lower = {(k or "").strip().lower(): k for k in (reader.fieldnames or [])}

        def col(*names: str) -> str:
            for nm in names:
                if nm in lower:
                    return lower[nm]
            raise KeyError(f"CSV missing one of columns: {names}")

        dcol = col("date", "timestamp", "time")
        ocol, hcol, lcol, ccol = col("open", "o"), col("high", "h"), col("low", "l"), col("close", "c")
        try:
            vcol = col("volume", "v")
        except KeyError:
            vcol = None
        for row in reader:
            bars.append(Bar(
                date=str(row[dcol]),
                o=float(row[ocol]), h=float(row[hcol]),
                l=float(row[lcol]), c=float(row[ccol]),
                v=float(row[vcol]) if vcol else 0.0,
            ))
    return bars


def synthetic_bars(n: int = 600, seed: int = 7, start_price: float = 100.0,
                   daily_vol: float = 0.012, drift: float = 0.0) -> List[Bar]:
    """SYNTHETIC random-walk daily bars — mechanics smoke test ONLY. Not market data."""
    rng = random.Random(seed)
    bars: List[Bar] = []
    price = start_price
    day = datetime(2024, 1, 1)
    for _ in range(n):
        ret = rng.gauss(drift, daily_vol)
        o = price
        c = max(0.01, price * (1.0 + ret))
        hi = max(o, c) * (1.0 + abs(rng.gauss(0, daily_vol / 2)))
        lo = min(o, c) * (1.0 - abs(rng.gauss(0, daily_vol / 2)))
        bars.append(Bar(date=day.strftime("%Y-%m-%d"), o=o, h=hi, l=lo, c=c, v=1e6))
        price = c
        day += timedelta(days=1)
    return bars


def render_markdown(v: Dict[str, Any]) -> str:
    m = v["metrics"]
    lines = [
        "# P2-044B — Equities/ETF Swing Backtest Gate",
        "",
        f"Generated: {v['generated_utc']}",
        f"Lane: {v['lane']}",
        f"**Verdict: {v['verdict']}**  ·  decision_grade={v['decision_grade']}  ·  authorizes_live={v['authorizes_live']}",
        "",
        f"> {v['disclaimer']}",
        "",
        f"Bars: {v['n_bars']} · round-trip cost: {v['costs']['round_trip_cost_bps']} bps · "
        f"buy&hold: {v['baselines']['buy_and_hold_bps']} bps",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Trades | {m['n_trades']} |",
        f"| Win rate | {m['win_rate']*100:.1f}% |",
        f"| Net EV / trade (bps) | {m['net_ev_per_trade_bps']} |",
        f"| Gross EV / trade (bps) | {m['gross_ev_per_trade_bps']} |",
        f"| Total net (bps) | {m['total_net_bps']} |",
        f"| Profit factor | {m['profit_factor']} |",
        f"| Fold stability | {v['fold_stability']} |",
        "",
        "## Gate checks",
    ]
    for k, ok in v["checks"].items():
        lines.append(f"- {'PASS' if ok else 'FAIL'} — {k}")
    if v["fail_reasons"]:
        lines += ["", f"Fail reasons: {', '.join(v['fail_reasons'])}"]
    lines += ["", f"Exit reasons: {m['exit_reason_counts']}", ""]
    return "\n".join(lines)


def write_outputs(v: Dict[str, Any], out_dir: Path) -> Dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    jp = out_dir / "p2_044b_equities_swing_gate_verdict.json"
    mp = out_dir / "p2_044b_equities_swing_gate_verdict.md"
    jp.write_text(json.dumps(v, indent=2))
    mp.write_text(render_markdown(v))
    return {"json": str(jp), "md": str(mp)}


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="P2-044B offline equities/ETF swing backtest gate")
    p.add_argument("--csv", help="Daily OHLCV CSV (date,open,high,low,close,volume). REAL data => decision-grade.")
    p.add_argument("--out-dir", default="/tmp")
    p.add_argument("--folds", type=int, default=DEFAULT_N_FOLDS)
    p.add_argument("--min-trades", type=int, default=MIN_TRADES)
    p.add_argument("--print", action="store_true")
    args = p.parse_args(argv)

    if args.csv:
        bars = load_bars_csv(Path(args.csv))
        decision_grade = True
        min_trades = args.min_trades
    else:
        print("[p2-044b] WARNING: no --csv given. Using SYNTHETIC random-walk bars "
              "for a mechanics smoke test only. Verdict is NOT decision-grade.")
        bars = synthetic_bars()
        decision_grade = False
        min_trades = 20  # relaxed for the smoke run; flagged non-decision-grade

    v = evaluate(bars, SwingParams(), CostModel(), n_folds=args.folds,
                 min_trades=min_trades, decision_grade=decision_grade)
    paths = write_outputs(v, Path(args.out_dir))
    if args.print:
        print(render_markdown(v))
    print(f"[p2-044b] verdict={v['verdict']} decision_grade={v['decision_grade']} "
          f"trades={v['metrics']['n_trades']}")
    print(f"[p2-044b] wrote {paths['json']}")
    print(f"[p2-044b] wrote {paths['md']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
