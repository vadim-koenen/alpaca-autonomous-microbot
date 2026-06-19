#!/usr/bin/env python3
"""
suggestion_engine.py — P2-046V: proactive "today's suggested action" with context + guidance.

Surfaces the single most useful thing to do now, in plain English, WITH historical context (what
you've put in / what it's worth) and forward guidance (a simple, clearly-labeled projection). So the
operator is informed and nudged instead of guessing.

HONESTY GUARDRAILS:
- Suggestions are DISCIPLINE + HOUSEKEEPING only (contribute, reinvest, rebalance, pause on risk).
  Never "buy/sell asset X by a signal" — that's the falsified alpha game.
- The forward number is a compound-interest PROJECTION of contributions at an assumed return — an
  estimate, explicitly NOT a market prediction or guarantee.

GOVERNANCE: pure logic. No broker, no orders, no network.
"""

from __future__ import annotations

from typing import Any, Dict, List


def _m(x: float) -> str:
    return f"${float(x):,.0f}"


def projected_value(state: Dict[str, Any]) -> float:
    """Rough 12-month projection: (current value + a year of contributions) grown at the assumed
    return for the chosen risk preset. An ESTIMATE, not a prediction."""
    tv = float(state.get("total_value", 0.0))
    c = float(state.get("contribution", 0.0))
    ppy = float(state.get("periods_per_year", 52))
    r = float(state.get("assumed_return", 0.06))
    return (tv + c * ppy) * (1 + r)


def _context(state: Dict[str, Any]) -> str:
    inv = float(state.get("invested", 0.0))
    tv = float(state.get("total_value", 0.0))
    plp = state.get("total_pl_pct")
    if inv <= 0:
        return ""
    chg = f" ({plp:+.1f}%)" if plp is not None else ""
    return f"You've put in {_m(inv)}; it's worth {_m(tv)}{chg}. "


def _guidance(state: Dict[str, Any]) -> str:
    c = float(state.get("contribution", 0.0))
    return (f"Keep adding {_m(c)}/contribution → on track for ~{_m(projected_value(state))} in a year "
            "(estimate, not a guarantee).")


def suggest(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Prioritized suggestions (1 = most urgent). state keys: mode, total_value, invested,
    total_pl_pct, contribution, cadence_days, periods_per_year, assumed_return,
    days_since_contribution (int|None), reinvest_amount, max_drift, rebalance_band,
    risk_alerts (int), tier (dict|None), funded (bool|None)."""
    c = float(state.get("contribution", 0.0))
    ctx = _context(state)
    fwd = _guidance(state)
    out: List[Dict[str, Any]] = []

    if int(state.get("risk_alerts", 0)) > 0:
        n = int(state["risk_alerts"])
        out.append({"type": "risk", "priority": 1, "title": "Hold off — risk event",
                    "message": f"{n} risk alert(s) on assets you hold. {ctx}Consider skipping this "
                               "week's contribution until it clears, then resume."})

    if state.get("funded") is False:
        out.append({"type": "fund", "priority": 2, "title": "Add funds to keep investing",
                    "message": f"Your account is out of cash to deploy {_m(c)}. {ctx}Add a deposit in "
                               "Alpaca (or set a recurring one) and it invests automatically."})

    amt = float(state.get("reinvest_amount", 0.0))
    if amt > 0:
        amt_s = f"${amt:.2f}"  # cents — dividends are small
        out.append({"type": "reinvest", "priority": 3, "title": f"{amt_s} of income ready",
                    "message": f"You earned {amt_s} in dividends/interest. {ctx}It auto-reinvests "
                               f"on your next contribution — compounding works for you. {fwd}"})

    days = state.get("days_since_contribution")
    cadence = int(state.get("cadence_days", 7))
    if days is None:
        out.append({"type": "contribute", "priority": 4, "title": "Make your first contribution",
                    "message": f"Your account is idle. Add {_m(c)} to start — small and consistent is "
                               f"the whole strategy. {fwd}"})
    elif days >= cadence:
        out.append({"type": "contribute", "priority": 4, "title": f"Time to add {_m(c)}",
                    "message": f"It's been {days} days. {ctx}Add {_m(c)} to stay on pace. {fwd}"})

    if float(state.get("max_drift", 0.0)) > float(state.get("rebalance_band", 1.0)):
        out.append({"type": "rebalance", "priority": 5, "title": "Your mix drifted",
                    "message": f"{ctx}One holding has drifted from target — your next contribution "
                               "steers it back automatically. Nothing to do manually."})

    tier = state.get("tier")
    if tier and tier.get("upgrade_at"):
        gap = float(tier["upgrade_at"]) - float(state.get("total_value", 0.0))
        if 0 < gap <= float(tier["upgrade_at"]) * 0.25:
            out.append({"type": "tier", "priority": 6, "title": f"{_m(gap)} from a new tier",
                        "message": f"At {_m(tier['upgrade_at'])} you reach the {tier.get('next_label')} "
                                   f"tier, which shifts your mix toward more growth. {ctx}"})

    if not out:
        nd = max(0, cadence - int(days or 0))
        when = "today" if nd == 0 else f"in {nd} day(s)"
        out.append({"type": "on_track", "priority": 9, "title": "You're on track",
                    "message": f"{ctx}Nothing needs doing — next contribution due {when}. {fwd}"})

    out.sort(key=lambda s: s["priority"])
    return out


def top_suggestion(state: Dict[str, Any]) -> Dict[str, Any]:
    return suggest(state)[0]
