#!/usr/bin/env python3
"""
suggestion_engine.py — P2-046S: proactive "today's suggested action" engine.

Looks at the account's current state and surfaces the single most useful thing to do right now,
in plain English — so the operator is nudged instead of having to remember/think. Powers daily
check-in notifications and a "Today's suggestion" dashboard card.

HONESTY GUARDRAIL: suggestions are about DISCIPLINE + HOUSEKEEPING only (contribute, deploy idle
income, rebalance drift, pause on a risk event, tier progress). They NEVER say "buy/sell asset X
because of a signal" — that's the falsified alpha game. No prediction, ever.

GOVERNANCE: pure logic. No broker, no orders, no network.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def suggest(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return suggestions sorted by priority (1 = most urgent). state keys:
    mode, total_value, contribution, cadence_days, days_since_contribution (int|None),
    reinvest_amount, max_drift, rebalance_band, risk_alerts (int), tier (dict|None),
    funded (bool|None)."""
    c = float(state.get("contribution", 0.0))
    out: List[Dict[str, Any]] = []

    if int(state.get("risk_alerts", 0)) > 0:
        n = int(state["risk_alerts"])
        out.append({"type": "risk", "priority": 1, "title": "Heads up — risk event",
                    "message": f"{n} risk alert(s) on your basket. Consider holding this week's "
                               "contribution until it clears."})

    if state.get("funded") is False:
        out.append({"type": "fund", "priority": 2, "title": "Add funds to invest",
                    "message": f"Your account needs cash to deploy ${c:.0f}. Add a deposit in Alpaca "
                               "and it'll invest automatically."})

    amt = float(state.get("reinvest_amount", 0.0))
    if amt > 0:
        out.append({"type": "reinvest", "priority": 3, "title": "Income ready to reinvest",
                    "message": f"You earned ${amt:.2f} in dividends/interest — it auto-reinvests on "
                               "your next contribution."})

    days = state.get("days_since_contribution")
    cadence = int(state.get("cadence_days", 7))
    if days is None:
        out.append({"type": "contribute", "priority": 4, "title": "Start investing",
                    "message": f"Your account is idle — add your ${c:.0f} to start building."})
    elif days >= cadence:
        out.append({"type": "contribute", "priority": 4, "title": "Time to invest",
                    "message": f"It's been {days} days since your last contribution. Add ${c:.0f} "
                               "to stay on track."})

    if float(state.get("max_drift", 0.0)) > float(state.get("rebalance_band", 1.0)):
        out.append({"type": "rebalance", "priority": 5, "title": "Allocation drifted",
                    "message": "Your mix drifted from target — your next contribution steers it back "
                               "automatically (no action needed)."})

    tier = state.get("tier")
    if tier and tier.get("upgrade_at"):
        gap = float(tier["upgrade_at"]) - float(state.get("total_value", 0.0))
        if 0 < gap <= float(tier["upgrade_at"]) * 0.25:
            out.append({"type": "tier", "priority": 6, "title": "Almost a new tier",
                        "message": f"You're ${gap:.0f} from the {tier.get('next_label')} tier — it "
                                   "adds more growth to your mix."})

    if not out:
        nd = max(0, cadence - int(days or 0))
        out.append({"type": "on_track", "priority": 9, "title": "All on track",
                    "message": f"Nothing to do — you're on target. Next contribution due in {nd} day(s)."})

    out.sort(key=lambda s: s["priority"])
    return out


def top_suggestion(state: Dict[str, Any]) -> Dict[str, Any]:
    return suggest(state)[0]
