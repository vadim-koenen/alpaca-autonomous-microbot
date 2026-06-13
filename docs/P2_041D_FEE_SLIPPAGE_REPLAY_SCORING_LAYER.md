# P2-041D Fee / Slippage Replay Scoring Layer

## Definition
The offline scoring layer is the final gate in the offline replay execution pipeline. It takes two inputs:
1. The **no-trade baseline** report (P2-041B)
2. The **candidate strategy** replay report (P2-041C)

## Goal
To programmatically ensure that we never adopt a strategy whose net profitability after fees and slippage is worse than simply doing nothing.

## Fail-Closed Paradigm
Because the bot currently holds an unproven, negatively-performing live strategy (`NET_PNL≈-$1.58`), the scoring layer is heavily biased toward safety and conservatism.

It explicitly **fails closed** (rejects the candidate) if:
* The candidate report is missing or malformed.
* The baseline report is missing or malformed.
* The candidate replay was blocked or stubbed (meaning its performance cannot be safely determined).
* The candidate traded but logged $0.00 in fees/slippage (indicating a missing or broken fee simulation model).
* The candidate's `net_pnl` is not strictly greater than the `net_pnl` of the no-trade baseline.

## Constraints
* Completely offline execution.
* Does not query live accounts or touch broker systems.
* Writes its output locally to `/tmp` to avoid permanently polluting the git repository with ephemeral replay data.
