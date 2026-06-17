#!/usr/bin/env python3
"""
planner_service.py — P2-046D: the service the backend/app/executor all call.

Ties the decision engine (P2-046B) to current prices + saved state + config, and returns
ONE JSON-serializable "PeriodPlan": portfolio snapshot, current-vs-target weights with
drift, the proposed BUY/SELL orders, and a plain-language summary. The FastAPI backend
returns this; the desktop UI renders it; the paper executor (later) acts on it ONLY after
human approval. Prices are INJECTED (no network here) so the logic is fully testable offline.

GOVERNANCE: produces a PROPOSAL only. authorizes_live is always False. No broker, no orders.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import allocator_engine as eng
import capital_allocation as cap
from allocator_engine import Portfolio
from app_config import AppConfig


def latest_prices_from_csvs(csv_by_symbol: Dict[str, str]) -> Dict[str, float]:
    """Read the last close from each daily-OHLCV CSV. Offline convenience for a demo plan;
    the live app would pull read-only quotes from Alpaca instead."""
    prices: Dict[str, float] = {}
    for sym, path in csv_by_symbol.items():
        last = None
        for row in csv.DictReader(Path(path).read_text().splitlines()):
            last = row
        if last:
            prices[sym] = float(last["close"])
    return prices


def build_plan(
    portfolio: Portfolio,
    prices: Dict[str, float],
    config: AppConfig,
    *,
    contribution: Optional[float] = None,
) -> Dict[str, Any]:
    """Produce the period plan. Pure: no I/O, no network, no side effects."""
    config.validate()
    contrib = config.contribution if contribution is None else contribution
    total = portfolio.value(prices)

    # Capital-adaptive: the target weights shift with total capital (a deliberate glide path).
    tier = None
    if getattr(config, "adaptive_allocation", False):
        tier = cap.tier_info(total)
        base_weights = tier["weights"]
    else:
        base_weights = config.weights

    # only act on symbols that have both a target weight and a price
    weights = {s: w for s, w in base_weights.items() if s in prices and prices[s] > 0}
    if not weights:
        raise ValueError("no priced symbols overlap the target weights")

    orders = eng.plan_period(
        portfolio, prices, weights, contrib,
        band=config.rebalance_band, allow_sell=config.allow_sell,
    )

    cur = eng.current_weights(portfolio, prices)
    tgt = eng.normalize_weights(weights)
    drift = {s: round(cur.get(s, 0.0) - tgt[s], 4) for s in tgt}

    return {
        "schema": "p2_046d_period_plan/v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "profile": config.profile,
        "portfolio_value": round(total, 4),
        "cash": round(portfolio.cash, 4),
        "holdings_units": {s: round(u, 8) for s, u in portfolio.holdings.items()},
        "current_weights": {s: round(cur.get(s, 0.0), 4) for s in tgt},
        "target_weights": {s: round(tgt[s], 4) for s in tgt},
        "drift": drift,
        "contribution": round(contrib, 4),
        "orders": [
            {"symbol": o.symbol, "side": o.side, "dollars": o.dollars,
             "est_units": o.est_units, "reason": o.reason}
            for o in orders
        ],
        "summary": eng.summarize_plan(orders),
        "overlay_enabled": config.overlay_enabled,
        "adaptive": tier is not None,
        "tier": ({"label": tier["label"], "note": tier["note"],
                  "upgrade_at": tier["upgrade_at"], "next_label": tier["next_label"]}
                 if tier else None),
        "authorizes_live": False,
        "note": "Proposal only. Human approval + paper before any live; STOP_TRADING gates execution.",
    }


def render_plan_text(plan: Dict[str, Any]) -> str:
    lines = [
        f"Accumulator plan ({plan['profile']}) · {plan['generated_utc']}",
        f"Portfolio value: ${plan['portfolio_value']:.2f}  (cash ${plan['cash']:.2f})  "
        f"contribution ${plan['contribution']:.2f}",
        "",
        f"{'sym':<5}{'target':>8}{'current':>9}{'drift':>8}",
    ]
    for s in plan["target_weights"]:
        lines.append(f"{s:<5}{plan['target_weights'][s]*100:>7.1f}%"
                     f"{plan['current_weights'][s]*100:>8.1f}%{plan['drift'][s]*100:>+7.1f}%")
    lines += ["", "Proposed orders:"]
    if plan["orders"]:
        for o in plan["orders"]:
            lines.append(f"  {o['side']:<4} {o['symbol']:<5} ${o['dollars']:>8.2f}  ({o['reason']})")
    else:
        lines.append("  (none)")
    lines += ["", f"> {plan['note']}"]
    return "\n".join(lines)
