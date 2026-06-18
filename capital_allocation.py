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
# BND (bonds), GLD (gold), BTC (crypto sleeve). Each PRESET is a capital-adaptive glide; the operator
# picks one (config.preset). Dividends + interest auto-reinvest (config.reinvest_dividends).
PRESETS: Dict[str, Dict[str, Any]] = {
    "preservation": {
        "label": "Preservation", "description": "Lowest risk. Mostly cash + bonds; tiny equity.",
        "tiers": [
            {"max_value": 1_000.0, "label": "Seed", "note": "capital first",
             "weights": {"SGOV": 0.80, "SCHD": 0.10, "GLD": 0.10}},
            {"max_value": 5_000.0, "label": "Build", "note": "add bonds",
             "weights": {"SGOV": 0.65, "SCHD": 0.15, "BND": 0.15, "GLD": 0.05}},
            {"max_value": float("inf"), "label": "Grow", "note": "a little index",
             "weights": {"SGOV": 0.55, "SCHD": 0.20, "VTI": 0.05, "BND": 0.15, "GLD": 0.05}},
        ],
    },
    "income": {
        "label": "Income", "description": "Preservation + dividend income. Balanced, modest growth.",
        "tiers": [
            {"max_value": 1_000.0, "label": "Seed", "note": "preservation + income",
             "weights": {"SGOV": 0.60, "SCHD": 0.25, "GLD": 0.15}},
            {"max_value": 5_000.0, "label": "Build", "note": "add index, bonds, small crypto",
             "weights": {"SGOV": 0.45, "SCHD": 0.25, "VTI": 0.10, "BND": 0.10, "GLD": 0.07, "BTC": 0.03}},
            {"max_value": float("inf"), "label": "Grow", "note": "more index, keep income core",
             "weights": {"SGOV": 0.30, "SCHD": 0.25, "VTI": 0.20, "BND": 0.10, "GLD": 0.10, "BTC": 0.05}},
        ],
    },
    "growth": {
        "label": "Growth", "description": "Higher risk/return. Equity-heavy with a crypto sleeve.",
        "tiers": [
            {"max_value": 1_000.0, "label": "Seed", "note": "equity + income core",
             "weights": {"SGOV": 0.40, "SCHD": 0.25, "VTI": 0.25, "GLD": 0.10}},
            {"max_value": 5_000.0, "label": "Build", "note": "index-led growth",
             "weights": {"SGOV": 0.20, "SCHD": 0.20, "VTI": 0.40, "GLD": 0.10, "BTC": 0.10}},
            {"max_value": float("inf"), "label": "Grow", "note": "max index growth",
             "weights": {"SGOV": 0.10, "SCHD": 0.15, "VTI": 0.55, "GLD": 0.10, "BTC": 0.10}},
        ],
    },
}

DEFAULT_PRESET = "income"
# Back-compat: TIERS is the default preset's glide.
TIERS: List[Dict[str, Any]] = PRESETS[DEFAULT_PRESET]["tiers"]


def tiers_for_preset(preset: str = DEFAULT_PRESET) -> List[Dict[str, Any]]:
    return PRESETS.get(preset, PRESETS[DEFAULT_PRESET])["tiers"]


def validate_tiers(tiers: List[Dict[str, Any]] = TIERS) -> None:
    last = 0.0
    for t in tiers:
        s = sum(t["weights"].values())
        if abs(s - 1.0) > 1e-9:
            raise ValueError(f"tier {t['label']} weights sum to {s}, not 1.0")
        if t["max_value"] <= last:
            raise ValueError("tier max_value thresholds must strictly increase")
        last = t["max_value"]


def tier_for_capital(value: float, preset: str = DEFAULT_PRESET) -> Dict[str, Any]:
    """Return the tier whose band contains `value` (first tier with value < max_value)."""
    tiers = tiers_for_preset(preset)
    for t in tiers:
        if value < t["max_value"]:
            return t
    return tiers[-1]


def weights_for_capital(value: float, preset: str = DEFAULT_PRESET) -> Dict[str, float]:
    return dict(tier_for_capital(value, preset)["weights"])


def tier_info(value: float, preset: str = DEFAULT_PRESET) -> Dict[str, Any]:
    tiers = tiers_for_preset(preset)
    t = tier_for_capital(value, preset)
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


def list_presets() -> List[Dict[str, str]]:
    """Names + labels + descriptions for the UI preset picker."""
    return [{"key": k, "label": v["label"], "description": v["description"]}
            for k, v in PRESETS.items()]


for _name, _p in PRESETS.items():       # fail fast at import if any preset is misconfigured
    validate_tiers(_p["tiers"])
