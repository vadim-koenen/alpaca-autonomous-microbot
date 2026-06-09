# P2-035C Coinbase Minimum-Net-Edge Entry Gate & Account-ID Redaction

This document describes the design, implementation, fee assumptions, and verification details of the **P2-035C** update.

## Purpose

The cryptocurrency trading bot has experienced fee drag on micro-trades, leading to a net-negative return over 51 closed cycles (cumulative net ≈ -$1.44). The main loss mechanisms are exchange fees and timeout-based exits. Prior to this patch, the risk manager checks were strategy-dependent: if a strategy (such as `coinbase_probe`) did not voluntarily attach expected edge or fee metadata, it could bypass the fee-aware hurdle completely. 

This patch introduces a mandatory, config-driven pre-entry gate that rejects any crypto candidate whose expected gross move cannot clear estimated round-trip costs, spread, slippage, and a safety margin. In addition, it redacts sensitive account identifiers (Coinbase and Alpaca IDs) from live logs.

## What Changed

### 1. Mandatory Fee-Edge Gate
- **File modified**: [risk_manager.py](file:///Users/vadimkoenen/Documents/Claude/Projects/Investing/alpaca-autonomous-microbot/risk_manager.py)
- **New check**: `_check_mandatory_fee_edge_gate` is added to the risk manager check chain.
- **Scope**: Gated entries for all crypto buy/short proposals.
- **Log message**: Emits `ENTRY_SKIPPED fee_edge_gate` with detailed cost breakdown on rejection.

### 2. Account ID Masking in Live Logs
- **File modified**: [permissions.py](file:///Users/vadimkoenen/Documents/Claude/Projects/Investing/alpaca-autonomous-microbot/permissions.py)
- **Summary masking**: `AccountPermissions.summary()` now masks the account number (UUID for Coinbase or numeric for Alpaca). 
  - If the identifier is greater than 4 characters, it outputs `****XXXX` (showing only the last 4 characters).
  - If it is empty or too short, it outputs `[REDACTED]`.
- This shields sensitive account numbers from live logs while preserving essential diagnostic info.

---

## Fee & Cost Assumptions

The gate calculates the minimum required gross move as follows:

$$\text{Required Gross Move (\%)} = \text{Worst-case Round-Trip Fee} + \text{Spread} + \text{Slippage Buffer} + \text{Safety Margin}$$

- **Taker Fee**: Read from config under `fees.taker_fee_pct` (default `0.012` = 1.20% per trade / 2.40% round-trip).
- **Spread**: Derived dynamically from quote bid/ask spread. If quote is unavailable, it defaults to `0.00%` and falls back to config parameters.
- **Slippage**: Read from config under `crypto.slippage_estimate_pct` (default `0.05` = 0.05%).
- **Safety Margin**: Read from config under `crypto.fee_edge_safety_margin_pct` (default `0.005` = 0.50%).

> [!IMPORTANT]
> The default taker fee of 1.20% matches the retail tier 0 fee structure on Coinbase. If the bot successfully fetches custom fee rates from Coinbase at startup, those actual rates are dynamically utilized.

---

## Reject-Only Rationale

This gate is strictly **reject-only**:
- It **never** places, modifies, or cancels any order.
- It **never** increases trade sizes or overrides strategy sizing limits.
- It **never** loosens risk parameters or allows entries that would have been blocked by other gates.
- It only acts as a safety filter to drop candidates that are mathematically expected to lose money to fees.

---

## How Diagnostics Appear

On rejection, a `WARNING` level log is emitted to the risk manager log:
```
ENTRY_SKIPPED fee_edge_gate strategy=coinbase_probe symbol=BTC/USD expected_move=0.500% < total_cost=2.970% (rt_fee=2.400% spread=0.020% slippage=0.050% safety=0.500%)
```

A structured skip reason is returned to the entry chain:
`fee_edge_gate: expected_move <x>% < total_cost <y>% (fees=<f>% spread=<s>% slip=<sl>% margin=<m>%)`

---

## Redaction Behavior

Live logs now mask UUID and Alpaca account numbers:
```
PERMISSIONS: Account: ****059a | status=ACTIVE | margin=False | short=False | ...
```
No sensitive identifiers are written to live logs, fulfilling compliance and security requirements.

---

## Tests Run

A new test suite [test_fee_edge_gate.py](file:///Users/vadimkoenen/Documents/Claude/Projects/Investing/alpaca-autonomous-microbot/tests/test_fee_edge_gate.py) contains 10 target test cases verifying:
- **Fee-negative** rejection and cost decomposition logging.
- **Fee-positive** entry allowance.
- **Config-driven** fee rates and margin bounds.
- **Non-crypto (equity)** skip bypass.
- **Missing/invalid take-profit price** handling.
- **Sell-side** bypass.
- **Silent bypass prevention** (ensuring strategies without explicit metadata are still evaluated).

Target tests in [test_permissions.py](file:///Users/vadimkoenen/Documents/Claude/Projects/Investing/alpaca-autonomous-microbot/tests/test_permissions.py) verify:
- Account ID masking for standard UUID formats.
- Short string and empty string redaction.
- Integration mapping via `fetch_permissions()`.

All unit tests pass successfully.

---

## Live Deployment Note

> [!WARNING]
> Because the running bot has **not** been restarted, stopped, or interrupted, these code changes are currently inactive in the running process. The changes will take effect only upon the next controlled restart/next launch of the bot.

---

## What Remains for P2-035D Exit Redesign

While P2-035C prevents entering structurally bad trades, the main profit leak for *existing* active positions remains the exit logic. Currently, exits are heavily dominated by the blind 90-minute timeout exit. The upcoming **P2-035D** patch will address the exit redesign:
1. Dynamically adjusting take-profit/stop-loss boundaries based on execution quality.
2. Replacing/optimizing the hard-coded 90-minute holding limit with trend-adaptive exits.
3. Aligning exit thresholds to recover commissions and bid-ask spreads.
