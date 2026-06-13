# P2-042C: Research Budget Monitor + Auto-Kill

## Overview
This document details the isolated budget-monitoring and auto-kill decision layer added for the "Live Research Sandbox". 

**Important:** This patch *does not* enable live research. It does not approve live trading for profit. It adds budget monitoring and auto-kill decision scaffolding *only*.

## Purpose
- Live research cannot proceed in the future without policy approval, journal capture, fill capture, fee capture, MFE/MAE capture, explicit budget caps, expiry, and allowed symbols.
- Losses in this sandbox are treated as research tuition, but they *must* stop at the approved budget.
- The budget monitor acts as an independent evaluator, computing real-time exposure and historic losses from the journal to return decisions: `ALLOW`, `PAUSE`, `KILL`, or `FAIL_CLOSED`.

## Budget Mechanics
The live research budget uses a strict **one-way ratchet** system for safety:
1. Losses from closed trades consume the budget.
2. Estimated fees from active or closed trades consume the budget.
3. Profits do *not* reverse consumed budget. If a budget cap is reached, a human must explicitly re-approve a new session to continue. This conservative default guarantees maximum loss is strictly bounded.
4. Auto-kill is a decision/event object only in this patch; it does not touch `STOP_TRADING` or runtime services.

## Next Steps
The next patch should be `P2-042D High-Volatility Exploration Strategy Queue`.
