# Claude Handoff: Controlled Coinbase Exploration (2026-05-29)

## Executive Summary
I have successfully implemented and enabled **P2-001: Controlled Aggressive Coinbase Live Exploration**. The bot is now configured to rotate micro-trades ($1.00 notional) across BTC, ETH, and SOL to gather diverse live data for the Shadow Learner. I also implemented **P1-006D: Scoring Reconciliation** to provide unified advisory reports comparing evaluator and diagnostic conclusions.

**CRITICAL**: A Coinbase launchd restart is **REQUIRED** for the live bot to pick up the new code and configuration.

## Environment & Git State
- **Current Branch**: `main`
- **Latest Commit (Pre-Commit)**: `c12a9a1` (add P1-006C prospective diagnostics report)

## P1-006D: Scoring Reconciliation
- **Feature**: Added `shadow_learner/scoring_reconciliation.py` and `scripts/shadow_scoring_reconciliation.py`.
- **Reconciled Conclusion**: `RECONCILED_WEAK_SIGNAL_TRACK_ONLY`.
- **Watchlist Buckets**: `prospective_mean_reversion_v0 | BTC/USD | 15m/30m`.
- **Gate Status**: **Paper Trading Gate is CLOSED** (requires human review).

## P2-001: Controlled Exploration
- **Status**: **ENABLED** (`controlled_exploration.enabled: true`).
- **Approved Symbols**: `BTC/USD`, `ETH/USD`, `SOL/USD`.
- **Risk Settings**:
  - Max Notional: $1.00.
  - Max Round Trips / Day: 12.
  - Max Total Exposure: $6.00.
  - Per-Symbol Cooldown: 30 minutes.
  - Daily Stop Loss: $3.00.
  - Consecutive Loss Stop: 3.
- **Legacy BTC Probe**: **DISABLED** while exploration is active (`disable_legacy_btc_probe_when_enabled: true`).

## Files Changed
- `config_coinbase_crypto.yaml`: Enabled exploration and set aggressive risk limits.
- `strategy_crypto.py`: Surgically added `_coinbase_exploration` rotation logic.
- `shadow_learner/scoring_reconciliation.py`: Core reconciliation logic.
- `scripts/shadow_scoring_reconciliation.py`: CLI for reconciled reports.
- `scripts/controlled_exploration_status.py`: Safety and status monitoring.
- `docs/CONTROLLED_EXPLORATION_RUNBOOK.md`: Runbook for P2-001.
- `docs/SHADOW_SCORING_RECONCILIATION_RUNBOOK.md`: Runbook for P1-006D.
- `tests/test_controlled_exploration.py`: Unit tests for rotation/cooldown.
- `tests/test_shadow_scoring_reconciliation.py`: Unit tests for reconciliation.

## Validation Summary
- `py_compile`: All modified files compiled successfully.
- `controlled_exploration_status.py`: Verified `Enabled: True`, `Approved symbols`, and `Risk Cap Integrity: OK`.
- `config integrity check`: Verified no duplicate `live_symbols` and correct aggressive settings.

## Important Warning
**The live bot running under launchd has NOT yet picked up these changes.** You must restart the Coinbase bot process manually.

## Next Commands for Claude/User

### 1. Status Check
```bash
python3 scripts/controlled_exploration_status.py
```

### 2. Coinbase-only Restart
```bash
launchctl stop com.vadim.coinbase-crypto-bot
launchctl start com.vadim.coinbase-crypto-bot
```

### 3. Monitor Exploration Logs
```bash
tail -f logs/bot_$(date -u +%Y%m%d).log | grep -E "EXPLORE|coinbase_exploration|ENTRY_BLOCKED|rejected|cooldown"
```

## Safety Gates
- **.env**: Not touched.
- **Core Modules**: No changes to `broker_coinbase.py`, `order_manager.py`, `risk_manager.py`, or `main.py`.
- **Manual Orders**: No orders were placed or modified during this implementation.

## Recommendation
Run controlled exploration for a few hours. Monitor the account transactions to confirm rotation across BTC/ETH/SOL instead of repeated BTC-only round trips.
