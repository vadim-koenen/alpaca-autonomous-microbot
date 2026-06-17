#!/usr/bin/env python3
"""
app_config.py — P2-046D: accumulator/allocator configuration.

Holds the operator's chosen basket, target weights (CONSERVATIVE profile, chosen
2026-06-16), contribution cadence, and execution assumptions. Loaded by the planner
service / FastAPI backend / desktop app. Plain JSON so it is human-editable and the
Settings screen can write it back.

GOVERNANCE: config only. No broker, no orders, no live authorization.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict

# Operator-selected CONSERVATIVE allocation (2026-06-16): lower drawdown, metals ballast,
# small crypto sleeve. Weights sum to 1.0.
CONSERVATIVE_WEIGHTS: Dict[str, float] = {
    "SPY": 0.35,
    "GLD": 0.25,
    "SLV": 0.15,
    "QQQ": 0.15,
    "BTC": 0.10,
}


@dataclass
class AppConfig:
    weights: Dict[str, float] = field(default_factory=lambda: dict(CONSERVATIVE_WEIGHTS))
    contribution: float = 100.0      # cash deployed per cadence period
    cadence_days: int = 7            # weekly
    rebalance_band: float = 0.25     # trim only when an asset drifts > 25% of target
    allow_sell: bool = False         # accumulator default: steer new money, don't sell
    cost_bps: float = 10.0           # spread+slippage assumption per side
    overlay_enabled: bool = False    # P2-046A: dip-overlay does NOT beat plain DCA -> OFF
    live_paper: bool = False         # M4 gate: must be explicitly enabled to submit Alpaca PAPER orders
    live_trading_enabled: bool = False   # M5 gate: REAL money. Off until the operator deliberately enables.
    live_max_contribution: float = 100.0  # fat-finger cap on a single live contribution ($)
    profile: str = "conservative"
    # Offline price source for the app/planner: symbol -> daily-OHLCV CSV (last close used).
    # The live app can swap this for read-only Alpaca quotes; CSVs keep it runnable offline.
    price_csvs: Dict[str, str] = field(default_factory=lambda: {
        "SPY": "SPY_clean.csv", "GLD": "GLD_clean.csv", "SLV": "SLV_clean.csv",
        "QQQ": "QQQ_daily.csv", "BTC": "BTC_daily.csv",
    })

    def validate(self) -> None:
        if not self.weights:
            raise ValueError("weights must be non-empty")
        total = sum(self.weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"weights must sum to 1.0 (got {total})")
        if any(w < 0 for w in self.weights.values()):
            raise ValueError("weights must be non-negative")
        if self.contribution < 0 or self.cadence_days <= 0:
            raise ValueError("contribution >= 0 and cadence_days > 0 required")


def default_config() -> AppConfig:
    c = AppConfig()
    c.validate()
    return c


def load_config(path: Path) -> AppConfig:
    if not Path(path).exists():
        return default_config()
    data = json.loads(Path(path).read_text())
    c = AppConfig(**data)
    c.validate()
    return c


def save_config(config: AppConfig, path: Path) -> None:
    config.validate()
    Path(path).write_text(json.dumps(asdict(config), indent=2))
