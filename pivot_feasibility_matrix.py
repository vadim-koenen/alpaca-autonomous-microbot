#!/usr/bin/env python3
"""
pivot_feasibility_matrix.py — P2-044A offline pivot feasibility matrix.

PURPOSE
-------
The short-horizon Coinbase BTC/ETH retail-fee thesis is FALSIFIED (P2-043D:
`any_scenario_passed=false`, THESIS_STATUS=PIVOT_OR_STOP). Before writing any
new strategy code, this module screens candidate pivot "lanes" on a single,
honest cost-vs-expected-move basis and reports which (if any) is worth carrying
into a real-cost walk-forward backtest gate.

WHAT THIS IS
------------
A FEASIBILITY SCREEN, not a profit claim. It answers one question per lane:
"Can the expected gross move at this horizon plausibly clear the round-trip
cost, and is the lane testable/compliant given a ~$10 account?"

WHAT THIS IS NOT
----------------
- It does NOT prove edge. A lane scored FEASIBLE_TO_TEST only earns the right to
  an offline backtest; it is not authorized for live trading.
- It does NOT use real-time prices, broker APIs, or any network. Every number is
  a documented ASSUMPTION (see ASSUMPTIONS_SOURCE on each lane). Assumptions must
  be confirmed against real fee schedules and real OHLCV before any decision.
- It performs NO runtime mutation. Offline only. Writes to an output dir
  (default /tmp). Does not touch runtime/STOP_TRADING, journals, or broker state.

AUTHORIZATION TO GO LIVE still requires a P2-043D-style real-cost walk-forward:
net-of-all-cost EV/trade > 0 AND >= 2x round-trip cost; profit factor >= 1.3;
beats BOTH no-trade and buy-and-hold; stable across folds; >= 100-200 trades.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# --- account / governance constants (mirror project risk rules for the $10 account) ---
ACCOUNT_EQUITY_USD: float = 10.0
MAX_LIVE_TRADE_NOTIONAL_USD: float = 3.0  # per project risk rules
PDT_MIN_EQUITY_USD: float = 25_000.0      # US pattern-day-trader threshold for frequent intraday equities

# Anchor for horizon scaling: ACTIVE_HANDOFF verified ~0.8% (80 bps) expected
# absolute BTC/ETH move over a 90-minute window. Longer horizons scale ~sqrt(time)
# (random-walk diffusion); this is an approximation, deliberately conservative.
ANCHOR_MOVE_BPS: float = 80.0
ANCHOR_HORIZON_MIN: float = 90.0

# Verdict thresholds on the hurdle ratio (expected_move / round_trip_cost).
HURDLE_INFEASIBLE_BELOW: float = 1.0   # move smaller than cost => structurally unwinnable
HURDLE_FEASIBLE_AT_OR_ABOVE: float = 2.0  # need a >=2x margin to have any chance net of noise


@dataclass(frozen=True)
class LaneAssumptions:
    """All inputs for one pivot lane. Every field is an ASSUMPTION to be confirmed."""
    key: str
    label: str
    venue: str
    instrument: str
    horizon_label: str
    horizon_minutes: float
    # Per-side costs in basis points (1 bp = 0.01%). Round trip = 2x each, see below.
    fee_bps_per_side: float
    spread_bps_per_side: float
    slippage_bps_per_side: float
    # Expected ABSOLUTE move over the horizon, in bps. If None, derived from the
    # sqrt-time anchor; if given, it's an explicit override (e.g. equities vol).
    expected_move_bps_override: Optional[float]
    min_trade_notional_usd: float
    market_hours_only: bool
    pdt_constrained: bool  # True if the lane needs frequent intraday equity round-trips on a sub-$25k account
    # Prior probability of a DURABLE net-of-fee edge, from the P2-043D 2026-06-15 verdict ranges.
    prior_p_durable_edge: float
    assumptions_source: str
    is_no_trade_baseline: bool = False


@dataclass
class LaneResult:
    key: str
    label: str
    venue: str
    instrument: str
    horizon_label: str
    round_trip_cost_bps: float
    expected_move_bps: float
    hurdle_ratio: float                # expected_move / round_trip_cost
    breakeven_win_rate: float          # symmetric-move breakeven p* (1.0 == impossible)
    required_net_capture_bps: float    # must capture at least this, net, to break even
    live_capital_compliant: bool       # can a >= min-notional, <= max-notional live order be placed?
    offline_testable: bool
    prior_p_durable_edge: float
    constraints: List[str] = field(default_factory=list)
    verdict: str = ""                  # INFEASIBLE | MARGINAL | FEASIBLE_TO_TEST | BASELINE
    composite_score: float = 0.0
    notes: str = ""


def round_trip_cost_bps(a: LaneAssumptions) -> float:
    """Total round-trip frictional cost in bps: fees + spread + slippage, both sides."""
    return 2.0 * (a.fee_bps_per_side + a.spread_bps_per_side + a.slippage_bps_per_side)


def expected_move_bps(a: LaneAssumptions) -> float:
    """Expected absolute move over the horizon. Override if provided, else sqrt-time scaled."""
    if a.expected_move_bps_override is not None:
        return float(a.expected_move_bps_override)
    scale = math.sqrt(max(a.horizon_minutes, 1e-9) / ANCHOR_HORIZON_MIN)
    return ANCHOR_MOVE_BPS * scale


def breakeven_win_rate(expected_move: float, cost: float) -> float:
    """
    Symmetric +/- move model. Win pays +move, loss pays -move, every round trip pays cost.
    EV(p) = p*move - (1-p)*move - cost = move*(2p-1) - cost.
    Breakeven p* = 0.5 + cost / (2*move). If cost >= move, p* >= 1.0 => impossible.
    Returns a value clamped to [0, 1]; 1.0 signals structural infeasibility.
    """
    if expected_move <= 0:
        return 1.0
    p_star = 0.5 + cost / (2.0 * expected_move)
    return min(1.0, max(0.0, p_star))


def live_capital_compliant(a: LaneAssumptions) -> bool:
    """
    A lane is live-compliant for THIS account only if a >= min-notional, <= live-cap
    order can be placed AND the lane is not blocked by the PDT rule on a sub-$25k
    account. (Offline testability is separate and always True.)
    """
    if a.is_no_trade_baseline:
        return True
    if a.pdt_constrained and ACCOUNT_EQUITY_USD < PDT_MIN_EQUITY_USD:
        return False
    return (a.min_trade_notional_usd <= MAX_LIVE_TRADE_NOTIONAL_USD
            and a.min_trade_notional_usd <= ACCOUNT_EQUITY_USD)


def evaluate_lane(a: LaneAssumptions) -> LaneResult:
    cost = round_trip_cost_bps(a)
    move = expected_move_bps(a)
    hurdle = (move / cost) if cost > 0 else math.inf
    p_star = breakeven_win_rate(move, cost)
    compliant = live_capital_compliant(a)

    constraints: List[str] = []
    if a.market_hours_only:
        constraints.append("market_hours_only")
    if a.pdt_constrained:
        constraints.append(f"pdt_constrained(<${PDT_MIN_EQUITY_USD:,.0f})")
    if not compliant:
        constraints.append(
            f"min_notional_${a.min_trade_notional_usd:.2f}>live_cap_${MAX_LIVE_TRADE_NOTIONAL_USD:.2f}"
        )

    res = LaneResult(
        key=a.key,
        label=a.label,
        venue=a.venue,
        instrument=a.instrument,
        horizon_label=a.horizon_label,
        round_trip_cost_bps=round(cost, 2),
        expected_move_bps=round(move, 2),
        hurdle_ratio=round(hurdle, 3) if math.isfinite(hurdle) else hurdle,
        breakeven_win_rate=round(p_star, 4),
        required_net_capture_bps=round(cost, 2),
        live_capital_compliant=compliant,
        offline_testable=True,  # everything here can be backtested offline
        prior_p_durable_edge=a.prior_p_durable_edge,
        constraints=constraints,
        notes=a.assumptions_source,
    )

    # --- verdict ---
    if a.is_no_trade_baseline:
        res.verdict = "BASELINE"
    elif hurdle < HURDLE_INFEASIBLE_BELOW or p_star >= 0.95:
        res.verdict = "INFEASIBLE"
    elif hurdle >= HURDLE_FEASIBLE_AT_OR_ABOVE:
        res.verdict = "FEASIBLE_TO_TEST"
    else:
        res.verdict = "MARGINAL"

    # --- composite score (ranking only; NOT a probability of profit) ---
    # Reward cost headroom (hurdle), prior edge odds, and capital compliance;
    # penalize operational constraints. Baseline/infeasible get 0.
    if res.verdict in ("INFEASIBLE", "BASELINE"):
        res.composite_score = 0.0
    else:
        hurdle_term = min(hurdle, 5.0) / 5.0           # 0..1, saturates at 5x
        edge_term = min(a.prior_p_durable_edge, 0.30) / 0.30
        capital_term = 1.0 if compliant else 0.5
        constraint_penalty = 1.0 - 0.15 * len(constraints)
        constraint_penalty = max(0.4, constraint_penalty)
        res.composite_score = round(
            100.0 * (0.45 * hurdle_term + 0.40 * edge_term + 0.15 * capital_term) * constraint_penalty,
            2,
        )
    return res


def default_lanes() -> List[LaneAssumptions]:
    """
    Candidate pivot lanes mapped to the P2-044 decision memo paths.
    NOTE: fee/spread numbers are APPROXIMATE and MUST be confirmed against live
    fee schedules before any decision. Coinbase taker per-side is modeled at the
    Intro-1 1.20% worst case (round trip 240 bps); ACTIVE_HANDOFF also cites a
    blended ~1.2% round-trip figure — both are bracketed by the maker lane below.
    """
    return [
        LaneAssumptions(
            key="coinbase_taker_short",
            label="Coinbase taker, 90-min BTC/ETH (FALSIFIED baseline)",
            venue="Coinbase", instrument="BTC/USD,ETH/USD",
            horizon_label="90 min", horizon_minutes=90.0,
            fee_bps_per_side=120.0, spread_bps_per_side=3.0, slippage_bps_per_side=5.0,
            expected_move_bps_override=None,
            min_trade_notional_usd=1.0, market_hours_only=False, pdt_constrained=False,
            prior_p_durable_edge=0.035,
            assumptions_source="P2-043D verdict; ACTIVE_HANDOFF 2026-06-14 (1.20% taker/side).",
        ),
        LaneAssumptions(
            key="coinbase_maker_short",
            label="Coinbase maker/post-only, 90-min BTC/ETH",
            venue="Coinbase", instrument="BTC/USD,ETH/USD",
            horizon_label="90 min", horizon_minutes=90.0,
            fee_bps_per_side=60.0, spread_bps_per_side=3.0, slippage_bps_per_side=2.0,
            expected_move_bps_override=None,
            min_trade_notional_usd=1.0, market_hours_only=False, pdt_constrained=False,
            prior_p_durable_edge=0.085,
            assumptions_source="P2-043D verdict (maker 5-12%); Intro-1 0.60% maker/side. Assumes post-only fills.",
        ),
        LaneAssumptions(
            key="coinbase_longer_horizon",
            label="Coinbase longer-horizon (4-24h) BTC/ETH",
            venue="Coinbase", instrument="BTC/USD,ETH/USD",
            horizon_label="~8 h", horizon_minutes=480.0,
            fee_bps_per_side=120.0, spread_bps_per_side=3.0, slippage_bps_per_side=5.0,
            expected_move_bps_override=None,
            min_trade_notional_usd=1.0, market_hours_only=False, pdt_constrained=False,
            prior_p_durable_edge=0.15,
            assumptions_source="P2-043D verdict (longer-horizon 10-20%). Taker cost held; turnover falls.",
        ),
        LaneAssumptions(
            key="cheaper_venue_crypto",
            label="Cheaper-venue crypto (e.g. Alpaca crypto), 4-8h BTC/ETH",
            venue="Alpaca (crypto)", instrument="BTC/USD,ETH/USD",
            horizon_label="~4 h", horizon_minutes=240.0,
            fee_bps_per_side=25.0, spread_bps_per_side=4.0, slippage_bps_per_side=4.0,
            expected_move_bps_override=None,
            min_trade_notional_usd=1.0, market_hours_only=False, pdt_constrained=False,
            prior_p_durable_edge=0.13,
            assumptions_source="P2-043D verdict (cheaper-venue 8-18%). Alpaca crypto ~0.15/0.25% maker/taker (CONFIRM).",
        ),
        LaneAssumptions(
            key="alpaca_equities_etf_swing",
            label="Commission-free Alpaca equities/ETF, multi-day swing (PDT-safe)",
            venue="Alpaca (equities)", instrument="liquid ETF e.g. SPY/QQQ",
            horizon_label="~3 trading days", horizon_minutes=3.0 * 6.5 * 60.0,
            fee_bps_per_side=0.0, spread_bps_per_side=1.0, slippage_bps_per_side=2.0,
            expected_move_bps_override=150.0,  # ~1.5% over ~3 days for a liquid ETF (assumption)
            min_trade_notional_usd=1.0, market_hours_only=True, pdt_constrained=False,
            prior_p_durable_edge=0.175,
            assumptions_source="P2-043D verdict (pivot off short-horizon crypto 10-25%). Commission-free; swing avoids PDT.",
        ),
        LaneAssumptions(
            key="alpaca_equities_etf_intraday",
            label="Alpaca equities/ETF, intraday day-trade (PDT-BLOCKED at $10)",
            venue="Alpaca (equities)", instrument="liquid ETF e.g. SPY/QQQ",
            horizon_label="intraday", horizon_minutes=90.0,
            fee_bps_per_side=0.0, spread_bps_per_side=1.0, slippage_bps_per_side=2.0,
            expected_move_bps_override=40.0,  # ~0.4% over 90 min for a liquid ETF (assumption)
            min_trade_notional_usd=1.0, market_hours_only=True, pdt_constrained=True,
            prior_p_durable_edge=0.06,
            assumptions_source="Low cost but PDT rule blocks frequent intraday round-trips on a sub-$25k account.",
        ),
        LaneAssumptions(
            key="no_trade_park",
            label="No-trade / park system (baseline)",
            venue="n/a", instrument="n/a",
            horizon_label="n/a", horizon_minutes=1.0,
            fee_bps_per_side=0.0, spread_bps_per_side=0.0, slippage_bps_per_side=0.0,
            expected_move_bps_override=0.0,
            min_trade_notional_usd=0.0, market_hours_only=False, pdt_constrained=False,
            prior_p_durable_edge=0.0,
            assumptions_source="No-trade optimum: net EV exactly 0; cannot lose to fees. Mandatory baseline.",
            is_no_trade_baseline=True,
        ),
    ]


def build_matrix(lanes: Optional[List[LaneAssumptions]] = None) -> Dict[str, Any]:
    lanes = lanes if lanes is not None else default_lanes()
    results = [evaluate_lane(a) for a in lanes]

    tradable = [r for r in results if r.verdict in ("FEASIBLE_TO_TEST", "MARGINAL")]
    tradable_sorted = sorted(tradable, key=lambda r: r.composite_score, reverse=True)
    recommended = tradable_sorted[0] if tradable_sorted else None

    recommended_key = recommended.key if recommended else "no_trade_park"
    recommended_reason = (
        f"Highest composite score ({recommended.composite_score}) among testable lanes: "
        f"hurdle {recommended.hurdle_ratio}x, breakeven win-rate {recommended.breakeven_win_rate}, "
        f"prior P(durable edge) {recommended.prior_p_durable_edge}."
        if recommended else
        "No lane cleared the cost hurdle; no-trade is the optimum until a positive-EV setup exists."
    )

    return {
        "schema": "p2_044a_pivot_feasibility_matrix/v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "disclaimer": (
            "FEASIBILITY SCREEN ONLY — not a profit claim, not live authorization. "
            "All fee/move figures are assumptions to confirm. Live requires a P2-043D-style "
            "real-cost walk-forward (net EV>0 AND >=2x cost; PF>=1.3; beats no-trade AND "
            "buy-and-hold; stable across folds; >=100-200 trades)."
        ),
        "account": {
            "equity_usd": ACCOUNT_EQUITY_USD,
            "max_live_trade_notional_usd": MAX_LIVE_TRADE_NOTIONAL_USD,
            "pdt_min_equity_usd": PDT_MIN_EQUITY_USD,
        },
        "anchor": {"move_bps": ANCHOR_MOVE_BPS, "horizon_minutes": ANCHOR_HORIZON_MIN,
                   "scaling": "sqrt-time"},
        "thresholds": {
            "hurdle_infeasible_below": HURDLE_INFEASIBLE_BELOW,
            "hurdle_feasible_at_or_above": HURDLE_FEASIBLE_AT_OR_ABOVE,
        },
        "lanes": [asdict(r) for r in results],
        "recommended_lane_key": recommended_key,
        "recommended_reason": recommended_reason,
        "next_evidence_required": (
            "Run a real-cost walk-forward backtest on REAL OHLCV for the recommended lane "
            "(>=100-200 trades, fees+spread+slippage+fill-prob) and confirm the lane's fee "
            "schedule before proposing any live restart. Live stays NO-GO until gates pass."
        ),
    }


def render_markdown(matrix: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# P2-044A — Pivot Feasibility Matrix (offline screen)")
    lines.append("")
    lines.append(f"Generated: {matrix['generated_utc']}")
    lines.append("")
    lines.append(f"> {matrix['disclaimer']}")
    lines.append("")
    acct = matrix["account"]
    lines.append(
        f"Account: ${acct['equity_usd']:.2f} equity · max live notional "
        f"${acct['max_live_trade_notional_usd']:.2f} · PDT threshold ${acct['pdt_min_equity_usd']:,.0f}"
    )
    lines.append("")
    lines.append("| Lane | Cost (bps RT) | Exp move (bps) | Hurdle | Breakeven win% | Live OK | Prior edge | Verdict | Score |")
    lines.append("|---|---:|---:|---:|---:|:--:|---:|:--:|---:|")
    for r in matrix["lanes"]:
        hurdle = r["hurdle_ratio"]
        hurdle_s = "inf" if hurdle in (float("inf"),) else f"{hurdle:.2f}x"
        live_ok = "yes" if r["live_capital_compliant"] else "NO"
        lines.append(
            f"| {r['label']} | {r['round_trip_cost_bps']:.0f} | {r['expected_move_bps']:.0f} | "
            f"{hurdle_s} | {r['breakeven_win_rate']*100:.1f}% | {live_ok} | "
            f"{r['prior_p_durable_edge']*100:.1f}% | {r['verdict']} | {r['composite_score']:.0f} |"
        )
    lines.append("")
    lines.append(f"**Recommended lane to test next:** `{matrix['recommended_lane_key']}`")
    lines.append("")
    lines.append(matrix["recommended_reason"])
    lines.append("")
    lines.append(f"**Next evidence required:** {matrix['next_evidence_required']}")
    lines.append("")
    lines.append("## Per-lane constraints & assumptions")
    for r in matrix["lanes"]:
        cons = ", ".join(r["constraints"]) if r["constraints"] else "none"
        lines.append(f"- **{r['label']}** ({r['venue']}, {r['horizon_label']}): "
                     f"constraints: {cons}. {r['notes']}")
    lines.append("")
    return "\n".join(lines)


def write_outputs(matrix: Dict[str, Any], out_dir: Path) -> Dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "p2_044a_pivot_feasibility_matrix.json"
    md_path = out_dir / "p2_044a_pivot_feasibility_matrix.md"
    json_path.write_text(json.dumps(matrix, indent=2))
    md_path.write_text(render_markdown(matrix))
    return {"json": str(json_path), "md": str(md_path)}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="P2-044A offline pivot feasibility matrix")
    parser.add_argument("--out-dir", default="/tmp", help="Output directory (default: /tmp). Offline only.")
    parser.add_argument("--print", action="store_true", help="Print the markdown report to stdout.")
    args = parser.parse_args(argv)

    matrix = build_matrix()
    paths = write_outputs(matrix, Path(args.out_dir))
    if args.print:
        print(render_markdown(matrix))
    print(f"[p2-044a] wrote {paths['json']}")
    print(f"[p2-044a] wrote {paths['md']}")
    print(f"[p2-044a] recommended_lane_key={matrix['recommended_lane_key']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
