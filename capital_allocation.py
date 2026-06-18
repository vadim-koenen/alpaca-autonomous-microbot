#!/usr/bin/env python3
"""
capital_allocation.py — P2-046M: capital-adaptive allocation (a principled glide path).

The target allocation ADAPTS to total capital: ultra-safe while the balance is small (you're
learning and can't afford a loss), shifting toward growth as the base grows enough to absorb
volatility. This is a DELIBERATE, capital-keyed glide — NOT market timing or signal-chasing.
The bot still never picks assets from research; only the *weights* shift across fixed tiers.

Tuned for the operator's stated profile (short horizon, preservation + income, untested risk):
even the top tier stays bond/T-bill anchored. Thresholds + weights are easy to edit here.

GOVERNANCE: pure allocation logic. No broker, no orders, no prediction.
"""

from __future__ import annotations

from typing import Any, Dict, List

# Each tier: applies while total capital < `max_value`. Weights must sum to 1.0.
# Symbols: SGOV (T-bills/cash), SCHD (dividend-income index), VTI (total-market index),
# BND (bonds), GLD (gold), BTC (crypto sleeve). Income-tilted for the operator's goal; dividends
# + interest auto-reinvest (config.reinvest_dividends).
TIERS: List[Dict[str, Any]] = [
    {"max_value": 1_000.0, "label": "Seed",
     "note": "tiny + learning → preservation + income (cash, dividends, gold)",
     "weights": {"SGOV": 0.60, "SCHD": 0.25, "GLD": 0.15}},
    {"max_value": 5_000.0, "label": "Build",
     "note": "base established → add a broad index, bonds + a small crypto sleeve",
     "weights": {"SGOV": 0.45, "SCHD": 0.25, "VTI": 0.10, "BND": 0.10, "GLD": 0.07, "BTC": 0.03}},
    {"max_value": float("inf"), "label": "Grow",
     "note": "base can absorb more volatility → more index growth, keep the income core",
     "weights": {"SGOV": 0.30, "SCHD": 0.25, "VTI": 0.20, "BND": 0.10, "GLD": 0.10, "BTC": 0.05}},
]


def validate_tiers(tiers: List[Dict[str, Any]] = TIERS) -> None:
    last = 0.0
    for t in tiers:
        s = sum(t["weights"].values())
        if abs(s - 1.0) > 1e-9:
            raise ValueError(f"tier {t['label']} weights sum to {s}, not 1.0")
        if t["max_value"] <= last:
            raise ValueError("tier max_value thresholds must strictly increase")
        last = t["max_value"]


def tier_for_capital(value: float, tiers: List[Dict[str, Any]] = TIERS) -> Dict[str, Any]:
    """Return the tier whose band contains `value` (first tier with value < max_value)."""
    for t in tiers:
        if value < t["max_value"]:
            return t
    return tiers[-1]


def weights_for_capital(value: float, tiers: List[Dict[str, Any]] = TIERS) -> Dict[str, float]:
    return dict(tier_for_capital(value, tiers)["weights"])


def tier_info(value: float, tiers: List[Dict[str, Any]] = TIERS) -> Dict[str, Any]:
    t = tier_for_capital(value, tiers)
    nxt = None
    for cand in tiers:
        if cand["max_value"] > t["max_value"] - 1e-9 and cand is not t and cand["max_value"] > value:
            nxt = cand
            break
    upgrade_at = t["max_value"] if t["max_value"] != float("inf") else None
    return {
        "label": t["label"],
        "note": t["note"],
        "weights": dict(t["weights"]),
        "upgrade_at": upgrade_at,
        "next_label": nxt["label"] if nxt else None,
    }


validate_tiers()  # fail fast at import if a tier is misconfigured
