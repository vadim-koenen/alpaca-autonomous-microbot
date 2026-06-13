# P2-041C Offline Current Strategy Replay Harness

## Definition
The offline strategy replay harness is intended to simulate the current live strategy (`strategy_crypto.py`) strictly in an offline context using backfilled market data, without touching production variables.

## Current Status: BLOCKED / STUBBED
The current integration of `strategy_crypto.py` cannot be fully decoupled from the live event loop and broker-facing classes without invasive structural rewrites. Because the strict governance explicitly forbids risk of breaking production behavior or touching live config:

1. A **stubbed placeholder** script (`scripts/run_current_strategy_replay_offline.py`) has been deployed instead of a risky overbuilt integration.
2. The stub safely asserts all offline, no-ML guardrails.
3. It emits a structurally valid (but zeroed) `replay_report_{dataset_id}.json` to `/tmp`.

This ensures the `P2-041D` offline fee/slippage scoring layer can be fully built, tested, and structurally proven around the offline reporting contract without forcing an immediate architecture rewrite.

## Guardrails Enforced
* Does not perform public fetch.
* Asserts `ml_training_approved == False` and `live_influence_approved == False`.
* Does not touch `com.vadim.price-path-logger` or `launchctl`.
* Generates report data strictly to `/tmp`.
