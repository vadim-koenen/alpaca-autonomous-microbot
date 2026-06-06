# Backtester Bake-off Results (P2-030-EVAL)

## Executive Summary
This evaluation compares the fidelity of various backtesting engines against actual realized live trading results.

## Status
status=blocked_dependency_install_required
blocker=Jesse and Freqtrade are not installed in the current environment. offline_ohlcv data is missing.

## Data Availability Audit
- offline_ohlcv_present=false
- live_cycle_journal_present=true
- cycle_count_detected=50 (estimated from journal_coinbase_crypto.csv)
- symbols_detected=ADA/USD, SOL/USD, BTC/USD, ETH/USD
- windows_detected=pending_missing_ohlcv
- blocker_if_any=data/offline_ohlcv/ was removed during previous git clean.

## Engine Availability Audit
- jesse_installed=false
- freqtrade_installed=false
- installation_required=true (requires explicit operator approval for network install)

## Methodology
1. Port production strategy rules to each engine.
2. Run backtests on historical windows matching the 50 live cycles.
3. Compare engine P/L and signals against realized journal facts.
4. Calculate residuals and direction match.

## Head-to-Head Comparison
| Metric | Current Replay | Jesse | Freqtrade |
| :--- | :--- | :--- | :--- |
| engine_available | true | false | false |
| ran_full_eval | false | false | false |
| direction_match | 0.50 | N/A | N/A |
| reconciliation_gap_usd | $1.34 | N/A | N/A |

## Verdict
verdict=blocked_missing_dependencies
