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
    broker: Any = None,
    confirm_live: bool = False,
    accumulator_stop_path: Path = Path("runtime/ACCUMULATOR_STOP"),
) -> Tuple[Dict[str, Any], Portfolio]:
    """Apply an approved plan. Returns a result dict incl. the new portfolio.

    - `approved` must be True (the human clicked Approve).
    - mode='simulate' updates local state only (no broker).
    - mode='paper' submits to a paper-only broker (fake money); gated by config.live_paper + broker.
    - mode='live' (real money) is always refused in this build.
    """
    if not approved:
        raise ExecutionBlocked("plan not approved by operator")

    orders = _orders_from_plan(plan)

    if mode == "live":
        # REAL MONEY. Multi-gate, all required:
        #  - config.live_trading_enabled explicitly True
        #  - confirm_live token passed by the caller (deliberate operator confirmation)
        #  - a live broker supplied
        #  - per-contribution dollar cap not exceeded (fat-finger guard)
        #  - dedicated kill-switch runtime/ACCUMULATOR_STOP absent
        if not getattr(config, "live_trading_enabled", False):
            raise ExecutionBlocked("config.live_trading_enabled is False — real-money live disabled")
        if not confirm_live:
            raise ExecutionBlocked("live execution requires explicit confirm_live=True")
        if broker is None:
            raise ExecutionBlocked("no live broker supplied")
        if accumulator_stop_path.exists():
            raise ExecutionBlocked("ACCUMULATOR_STOP present — live execution halted")
        cap = float(getattr(config, "live_max_contribution", 100.0))
        contribution = float(plan.get("contribution", 0.0))
        if contribution > cap:
            raise ExecutionBlocked(f"contribution ${contribution} exceeds live cap ${cap}")
        fills = broker.submit_orders(orders)
        return {
            "mode": "broker_live",
            "executed_utc": datetime.now(timezone.utc).isoformat(),
            "fills": fills,
            "n_fills": len(fills),
            "real_money": True,
            "authorizes_live": False,  # an execution result never re-authorizes anything
            "note": "Submitted to Alpaca LIVE account (REAL money). Reconcile state from broker.",
        }, portfolio

    if mode == "paper":
        # PAPER = fake money via a paper-only broker (paper endpoint + dedicated paper keys), so it
        # is INDEPENDENT of the global STOP_TRADING switch (that guards real money / the old bot).
        # Gates: config.live_paper enabled AND a (paper-only) broker supplied AND operator approval.
        if not getattr(config, "live_paper", False):
            raise ExecutionBlocked("config.live_paper is False — paper execution not enabled")
        if broker is None:
            raise ExecutionBlocked("no broker supplied for paper mode")
        fills = broker.submit_orders(orders)
        return {
            "mode": "broker_paper",
            "executed_utc": datetime.now(timezone.utc).isoformat(),
            "fills": fills,
            "n_fills": len(fills),
            "authorizes_live": False,
            "note": "Submitted to Alpaca PAPER account (fake money). Reconcile state from broker.",
        }, portfolio

    if mode != "simulate":
        raise ExecutionBlocked(f"unknown execution mode '{mode}'")

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
