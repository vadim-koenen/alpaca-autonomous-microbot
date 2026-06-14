# P2-043A Profit Thesis / EV Contract

## Overview

The Profit Thesis Expected Value (EV) Contract provides a pure, deterministic mathematical layer that evaluates the prospective profitability of a candidate trade before it can enter any execution or live-research pipeline. 

Until now, the microbot's guardrails strictly checked for safety: maximum notional size, allowed symbols, timeouts, and budget limits. However, **safety is not profitability**. Executing a safe, low-risk trade with negative expected value continuously will only safely bleed the portfolio through exchange fees, spreads, and slippage.

This contract shifts the focus from "Is this safe?" to "Does this mathematically justify its costs?"

## Economic Contract Model

Every trade proposal is now required to fulfill the following EV contract:

### 1. Narrative Justification
A candidate cannot just be a pure mechanical signal output without a reason. It must provide context:
- `why_this_symbol`: The fundamental/technical reason for selecting this asset.
- `why_now`: The exact catalyst triggering the timing.

### 2. Rigorous Cost Accounting
Retail trading implies significant costs. The candidate must model:
- `expected_fee_bps`: Exchange commissions.
- `expected_spread_bps`: Bid/Ask width at the time of proposal.
- `expected_slippage_bps`: Expected market impact.

The **Round Trip Cost** is calculated deterministically:
```python
round_trip_cost_bps = expected_fee_bps + expected_spread_bps + expected_slippage_bps
```

### 3. Expected Value Mathematics
The candidate provides a gross expected edge. The contract deducts all friction to calculate the true net edge:
```python
net_expected_edge_bps = gross_expected_edge_bps - expected_fee_bps - expected_spread_bps - expected_slippage_bps
```

### 4. Required Gating
A trade is completely rejected if it violates any of these deterministic barriers:

- `NEGATIVE_NET_EDGE`: The `net_expected_edge_bps` is zero or less.
- `INSUFFICIENT_NET_EDGE`: The net edge is less than the strict cushion (`2.0 * round_trip_cost_bps`).
- `MOVE_BELOW_COST`: The absolute expected move is smaller than or equal to the total round trip cost.
- `MISSING_NARRATIVE`: Fails to explain `why_this_symbol` or `why_now`.
- `MISSING_HOLD_MINUTES`: Lacks a valid expected hold duration.
- `MISSING_INVALIDATION` / `MISSING_TARGET`: Fails to provide explicit technical exit bounds.
- `MISSING_EVIDENCE_REQUIREMENTS`: Missing post-trade research tracking goals.
- `LIVE_TRADING_FOR_PROFIT_NOT_ALLOWED`: Safety constraint enforcing that live-profit trading remains disabled.

## Current Implications

With the `minimum_required_edge_bps` dynamically set to `2.0 * round_trip_cost_bps`, any candidate paying Coinbase retail rates (~10-12 bps) + crossing spread (~2 bps) + slippage (~2-5 bps) will encounter a baseline round-trip cost of ~16-20 bps. 

To pass the EV contract, a trade must demonstrate a gross edge that clears the cost *plus* an additional 32-40 bps of safety cushion. Most current low-edge, time-based exit strategies will correctly and mathematically fail this contract, preventing further fee bleed.
