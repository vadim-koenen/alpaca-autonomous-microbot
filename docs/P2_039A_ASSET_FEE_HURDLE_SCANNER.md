# P2-039A Asset Universe / Fee Hurdle / Liquidity Feasibility Scanner

## Purpose
The purpose of the P2-039A scanner is to act as a rigorous readiness gate that evaluates a candidate asset universe to see if those assets are theoretically viable to trade given the microbot's explicit fee, spread, slippage, and notional constraints. It prevents the expansion of live trading to assets that guarantee a mathematical loss due to high hurdles relative to their volatility.

## Why P2-039A Exists
P2-038B and P2-038C demonstrated that our current binding constraint is not a lack of assets, but rather a lack of profitability resulting from fee drag and insufficient holding periods (timeouts). The current historical trades show a massive fee drag turning a small gross loss (-$0.14) into a larger net loss (-$1.58), with only 2 out of 80 trades producing net positive returns. P2-039A builds the mathematical foundation to filter out structurally impossible assets before they are ever permitted near the live environment.

## Why Live Asset Expansion is Not Approved Yet
Until the strategy fundamentally alters its exit timing or execution cost model to clear the fee hurdle, expanding to more assets will merely increase the frequency of fee drag. Assets will only be cleared for live expansion once they mathematically cross the profit-first decision rule and pass rigorous replay evidence testing.

## Fee Hurdle Concept
The **all-in fee hurdle** is defined as the sum of round-trip execution fees (either taker or maker tier estimates) plus a realistic spread/slippage proxy (e.g. 0.05%). To break even, the underlying asset must move in our favor by *at least* the all-in hurdle percentage.

## Notional Sensitivity
Because percentage fees scale linearly with notional value, the absolute dollar value of the hurdle increases as position sizing increases. However, some minimum nominal constraints and minimum tick constraints may mean that very small sizes ($1-$5) cannot effectively overcome standard spreads. P2-039A models sizes from $1 to $100 to estimate minimum viable notional sizing.

## Volatility / Opportunity Feasibility
An asset may pass the mathematical fee hurdle but fail the volatility feasibility check if it simply does not move frequently enough to overcome the hurdle within the maximum allowed timeout window (e.g., 90 minutes). A failure here denotes "dead" or overly stable pairs.

## Feeding P2-039B and P2-040
The outputs from this scanner (assets marked `viable_for_research=true`) inform the target universe for **P2-039B Prediction Dataset** ingestion and eventually gate the final **P2-040 Proposed Live Universe** configuration.

## Profit-First Decision Rule
A trade is not eligible for live execution unless its conservative expected net edge clears:
`E[net] = p_tp * TP - p_sl * SL - p_timeout * E[timeout PnL] - fees_roundtrip - spread - slippage`
Minimum threshold for future live consideration:
- point estimate `E[net] >= +0.5%` of notional
- walk-forward lower 95% confidence interval of mean net return > 0

## Explicit Warning
**This does not change live trading.**
This scanner and its tests are purely advisory and read-only. It makes no mutations to live behavior, strategies, broker orders, risk, sizing, or capital allocations. `viable_for_live` is hardcoded to `false` in this patch.
