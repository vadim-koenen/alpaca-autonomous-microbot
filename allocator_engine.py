#!/usr/bin/env python3
"""
allocator_engine.py — P2-046B: the accumulator/allocator decision engine.

This is the broker-agnostic "brain" of the pivot (see FRAMEWORK_EDGE_DISCOVERY_2026-06-16.md
and P2-046A): given current holdings, live prices, target weights, and the cash to deploy this
period, it returns the exact BUY/SELL orders to move the portfolio toward target. No prediction,
no signals — just disciplined accumulation + drift control.

DESIGN CHOICES (deliberate, honest):
- **Contribution-funded rebalancing.** New DCA money is steered to the most *underweight* assets
  first, so the portfolio rebalances WITHOUT selling winners (no fees, no taxable events). Selling
  is opt-in (`allow_sell`) and only trims assets that breach the drift band.
- **Plain DCA is the default engine.** P2-046A showed the "buy-at-lows" valuation overlay does NOT
  beat plain DCA on the real basket, so it is OFF by default (kept as an optional, capped tilt).
- **Pure & deterministic.** Every function is side-effect-free and unit-tested. The live executor
  (later, behind STOP_TRADING) maps Orders → Alpaca calls; the desktop app renders the same Orders.

GOVERNANCE: offline logic only. No broker, no network, no runtime mutation. Nothing here places an
order or authorizes live trading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

BUY = "BUY"
SELL = "SELL"


@dataclass(frozen=True)
class Order:
    symbol: str
    side: str          # BUY | SELL
    dollars: float     # notional to transact (always positive)
    est_units: float   # estimated units at the supplied price (pre-cost)
    reason: str = ""   # "dca" | "rebalance_buy" | "rebalance_sell" | "tilt"


@dataclass
class Portfolio:
    holdings: Dict[str, float] = field(default_factory=dict)  # symbol -> units
    cash: float = 0.0

    def value(self, prices: Dict[str, float]) -> float:
        return self.cash + sum(self.holdings.get(s, 0.0) * prices[s] for s in prices)

    def holdings_value(self, prices: Dict[str, float]) -> Dict[str, float]:
        return {s: self.holdings.get(s, 0.0) * prices[s] for s in prices}


# --- helpers ------------------------------------------------------------------

def normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("target weights must sum to a positive number")
    return {s: w / total for s, w in weights.items()}


def current_weights(portfolio: Portfolio, prices: Dict[str, float]) -> Dict[str, float]:
    hv = portfolio.holdings_value(prices)
    total = sum(hv.values())
    if total <= 0:
        return {s: 0.0 for s in prices}
    return {s: hv[s] / total for s in prices}


# --- the core decision --------------------------------------------------------

def plan_period(
    portfolio: Portfolio,
    prices: Dict[str, float],
    target_weights: Dict[str, float],
    contribution: float,
    *,
    band: float = 0.0,
    allow_sell: bool = False,
    valuation_tilt: Optional[Dict[str, float]] = None,
) -> List[Order]:
    """Plan one accumulation period.

    1. Compute the post-contribution target value per asset.
    2. Route `contribution` to the most-underweight assets first (gap-fill) — this is the
       fee-free, contribution-funded rebalance. Leftover (if every asset is at/above target)
       is spread by target weight.
    3. Optionally `allow_sell`: trim any asset still over its target by more than `band`.
    4. Optional `valuation_tilt` (per-symbol multiplier, default OFF) nudges buy sizes; it is
       renormalized so total deployed == contribution (capital-neutral).

    Returns a list of Orders (dollars > 0). Deterministic; no side effects.
    """
    w = normalize_weights(target_weights)
    syms = list(w.keys())
    for s in syms:
        if s not in prices or prices[s] <= 0:
            raise ValueError(f"missing/invalid price for {s}")

    hv = {s: portfolio.holdings.get(s, 0.0) * prices[s] for s in syms}
    cur_total = sum(hv.values())
    total_after = cur_total + max(0.0, contribution)
    target_val = {s: total_after * w[s] for s in syms}
    gap = {s: target_val[s] - hv[s] for s in syms}  # +ve = underweight (wants buying)

    orders: List[Order] = []
    budget = max(0.0, contribution)

    # --- 2. allocate contribution to underweight assets ---
    shortfalls = {s: g for s, g in gap.items() if g > 0}
    short_total = sum(shortfalls.values())
    alloc: Dict[str, float] = {s: 0.0 for s in syms}

    if budget > 0 and short_total > 0:
        if short_total >= budget:
            # not enough new money to fully rebalance: fill underweights pro-rata
            for s, g in shortfalls.items():
                alloc[s] = budget * (g / short_total)
        else:
            # fill every underweight, then spread the remainder by target weight
            for s, g in shortfalls.items():
                alloc[s] = g
            remainder = budget - short_total
            for s in syms:
                alloc[s] += remainder * w[s]
    elif budget > 0:
        # already balanced/overweight everywhere: pure DCA by target weight
        for s in syms:
            alloc[s] = budget * w[s]

    # --- 4. optional valuation tilt (capital-neutral renormalization) ---
    if valuation_tilt and budget > 0:
        tilted = {s: alloc[s] * valuation_tilt.get(s, 1.0) for s in syms}
        tsum = sum(tilted.values())
        if tsum > 0:
            alloc = {s: budget * tilted[s] / tsum for s in syms}

    for s in syms:
        if alloc[s] > 1e-9:
            orders.append(Order(s, BUY, round(alloc[s], 6), round(alloc[s] / prices[s], 8),
                                reason="rebalance_buy" if gap[s] > 0 else "dca"))

    # --- 3. optional sells to trim assets above band (post-contribution) ---
    if allow_sell and total_after > 0:
        for s in syms:
            over = (hv[s] - target_val[s]) / total_after  # fraction overweight
            if over > band:
                trim = hv[s] - target_val[s]
                if trim > 1e-9:
                    orders.append(Order(s, SELL, round(trim, 6), round(trim / prices[s], 8),
                                        reason="rebalance_sell"))

    return orders


def plan_rebalance_only(
    portfolio: Portfolio,
    prices: Dict[str, float],
    target_weights: Dict[str, float],
    *,
    band: float = 0.0,
    allow_sell: bool = True,
) -> List[Order]:
    """A standalone drift-band rebalance with no new contribution (sells overweights,
    buys underweights from the proceeds + existing cash)."""
    return plan_period(portfolio, prices, target_weights, portfolio.cash,
                       band=band, allow_sell=allow_sell)


def apply_orders(
    portfolio: Portfolio,
    orders: List[Order],
    prices: Dict[str, float],
    *,
    cost_bps: float = 10.0,
) -> Portfolio:
    """Apply orders to a COPY of the portfolio (for sim/paper). Costs haircut both sides.
    Never lets units or cash go negative beyond rounding."""
    cf = 1.0 - cost_bps / 1e4
    holdings = dict(portfolio.holdings)
    cash = portfolio.cash
    for o in orders:
        p = prices[o.symbol]
        if o.side == BUY:
            spend = min(o.dollars, cash) if cash < o.dollars else o.dollars
            holdings[o.symbol] = holdings.get(o.symbol, 0.0) + spend * cf / p
            cash -= spend
        elif o.side == SELL:
            units = holdings.get(o.symbol, 0.0)
            sell_units = min(units, o.dollars / p)
            holdings[o.symbol] = units - sell_units
            cash += sell_units * p * cf
    return Portfolio(holdings=holdings, cash=round(cash, 10))


def summarize_plan(orders: List[Order]) -> Dict[str, float]:
    """Compact totals for a UI/dashboard."""
    return {
        "n_orders": len(orders),
        "buy_dollars": round(sum(o.dollars for o in orders if o.side == BUY), 4),
        "sell_dollars": round(sum(o.dollars for o in orders if o.side == SELL), 4),
    }
