#!/usr/bin/env python3
"""
app_analytics.py — P2-046G: performance tracking for the accumulator (equity curve).

Reconstructs the portfolio value vs invested-capital time series from the append-only
history of approved (simulated) fills, so the operator can SEE the tool working over time.
This is how "B is proven": watch the accumulator accumulate and track value vs contributions.

GOVERNANCE: read-only analytics over local history. No broker, no orders, authorizes_live=False.
"""

from __future__ import annotations

from typing import Any, Dict, List


def equity_curve(history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """From paper_fill history records, build points of {t, value, invested}. Pure."""
    points: List[Dict[str, Any]] = []
    invested = 0.0
    for rec in history:
        if rec.get("event") != "paper_fill":
            continue
        plan = rec.get("plan", {}) or {}
        result = rec.get("result", {}) or {}
        invested += float(plan.get("contribution", 0.0))
        value = float(result.get("portfolio_value", 0.0))
        t = rec.get("logged_utc") or result.get("executed_utc", "")
        points.append({"t": t, "value": round(value, 2), "invested": round(invested, 2)})

    current = points[-1]["value"] if points else 0.0
    total_invested = round(invested, 2)
    gain = current - total_invested
    ret_pct = round((gain / total_invested * 100), 2) if total_invested > 0 else 0.0
    return {
        "schema": "p2_046g_equity_curve/v1",
        "points": points,
        "n_periods": len(points),
        "current_value": round(current, 2),
        "total_invested": total_invested,
        "total_gain": round(gain, 2),
        "total_return_pct": ret_pct,
        "authorizes_live": False,
    }
