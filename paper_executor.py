#!/usr/bin/env python3
"""
paper_executor.py — P2-046D: execute an APPROVED plan as paper fills.

Turns a human-approved PeriodPlan into portfolio changes. Two modes:
- **simulate** (default, used now): models fills locally via `apply_orders` and persists state.
  Touches NO broker — it just updates a local JSON portfolio, so it is not "trading".
- **broker** (NOT enabled): would place Alpaca *paper* orders. HARD-GATED: refuses while
  `runtime/STOP_TRADING` exists or without explicit authorization. Left stubbed by design;
  enabling it is a separate, approved step (M4) after the offline gates pass.

GOVERNANCE: nothing here authorizes LIVE trading. Requires explicit `approved=True`.
`authorizes_live` is always False. STOP_TRADING always wins.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

import allocator_engine as eng
from allocator_engine import Order, Portfolio, BUY, SELL
from app_config import AppConfig

STOP_TRADING_PATH = Path("runtime/STOP_TRADING")


class ExecutionBlocked(Exception):
    """Raised when execution is refused by governance/safety."""


def _orders_from_plan(plan: Dict[str, Any]) -> list:
    return [Order(o["symbol"], o["side"], float(o["dollars"]), float(o["est_units"]),
                  o.get("reason", "")) for o in plan.get("orders", [])]


def execute_plan(
    portfolio: Portfolio,
    plan: Dict[str, Any],
    prices: Dict[str, float],
    config: AppConfig,
    *,
    approved: bool = False,
    mode: str = "simulate",
    stop_trading_path: Path = STOP_TRADING_PATH,
) -> Tuple[Dict[str, Any], Portfolio]:
    """Apply an approved plan. Returns a result dict incl. the new portfolio.

    - `approved` must be True (the human clicked Approve).
    - mode='simulate' updates local state only (no broker).
    - mode='broker' is refused here (STOP_TRADING present / not authorized) — by design.
    """
    if not approved:
        raise ExecutionBlocked("plan not approved by operator")

    if mode == "broker":
        # Defense-in-depth: never reachable without removing STOP_TRADING AND wiring a
        # real client AND explicit live-research approval — none of which exist now.
        if stop_trading_path.exists():
            raise ExecutionBlocked("STOP_TRADING present — broker execution refused")
        raise ExecutionBlocked("broker mode not authorized (paper/live gated until M4)")

    if mode != "simulate":
        raise ExecutionBlocked(f"unknown execution mode '{mode}'")

    orders = _orders_from_plan(plan)
    # Fund the period's contribution as new cash BEFORE deploying it (the operator is
    # depositing this money this period). Leftover stays as cash in the portfolio.
    contribution = float(plan.get("contribution", 0.0))
    funded = Portfolio(holdings=dict(portfolio.holdings), cash=portfolio.cash + contribution)
    new_pf = eng.apply_orders(funded, orders, prices, cost_bps=config.cost_bps)
    fills = [{"symbol": o.symbol, "side": o.side, "dollars": o.dollars,
              "est_units": o.est_units, "reason": o.reason} for o in orders]
    return {
        "mode": "simulate",
        "executed_utc": datetime.now(timezone.utc).isoformat(),
        "fills": fills,
        "n_fills": len(fills),
        "portfolio": {"holdings": new_pf.holdings, "cash": new_pf.cash},
        "portfolio_value": round(new_pf.value(prices), 4),
        "authorizes_live": False,
        "note": "Simulated fills to local state only. No broker contacted.",
    }, new_pf
