# EXTERNAL_INVENTORY_MAX_OPEN_SLOT_FIX (P2-024F)

## Summary
After P2-024D (expanded live basket: BTC/ETH/ADA/AVAX/DOGE/LINK/LTC under shared pilot caps), post-restart observation showed ADA/LTC as dashboard "candidates" but zero trades executed. Root cause (P2-024E diagnostic): RISK_GATE_BLOCK.

The live risk path (main.py building AccountState for risk_manager.check) was setting `open_positions=len(broker.get_all_positions())`. For Coinbase, broker.get_all_positions() includes the user-staked/external SOL/USD (visible on account, classified as external_staked_position with bot_inventory=false, tradable_by_bot=false, manual_close_allowed=false, blocks_new_entries=false).

Result: even with 0 bot-owned positions in local state/session/open_positions.json (and hb open_positions=0), the max_open_positions=1 check saw count=1 (the external SOL) and emitted "max open positions 1 reached", skipping the ADA signal after it reached "SIGNAL coinbase_exploration".

SOL was (and remains) correctly excluded from live symbol lists and never adopted into bot open_positions by position_manager (external_inventory_observed + not rehydrating).

## The Fix (P2-024F)
- In main.py, AccountState.open_positions / open_position_symbols for risk/duplicate checks now come from the bot's SessionState.open_positions (local tracked bot-owned positions only).
- Broker list is still fetched (for abandoned/external detection in position_manager, equity exposure calcs for other asset classes, etc.).
- risk_manager._check_max_open_positions continues to use `s.open_positions` (now guaranteed bot-owned).
- External/staked SOL (and future similar) visible in state/coinbase/external_inventory.json and position_manager logs, reported in dashboards/audit, but does not increment the cap count or trigger max_open block / manual_review block for other symbols.
- With only external SOL (bot_owned=0), max_open_slot_available=true; expanded candidates can pass the max_open gate (subject to all other gates: regime/rsi/bb/spread/fee/daily_trades/exposure/etc.).
- With 1 true bot-owned open position, new entry blocked by max_open=1 (even with external also present).
- SOL remains 100% excluded from entries, non-tradable, no bot close/remediate/adopt.

## Guardrails Preserved (no violations)
- max_open_positions=1 (now correctly applied to bot-owned only)
- max_trades_per_day=3
- final_trade_notional ~5.0 (balance relative), hard cap 10, max_trade_notional=10
- shared caps across expanded basket
- fee_drag_guard_enabled
- risk_increase=not_approved
- profit_readout=unsafe_to_aggregate (aggregation/scaling still false)
- trade_permission=none (dashboards/audit/digest remain read-only advisory)
- SOL/USD + derivatives/perps/prediction markets excluded
- No live broker calls, no --live-read-only, no .env, no orders, no launchctl, no restart during dev/tests

## Files Changed
- main.py (state construction for risk)
- risk_manager.py (comments clarifying semantics)
- scripts/coinbase_opportunity_dashboard.py (load external + report bot_owned/external/slot in runtime)
- scripts/coinbase_dashboard_observation_loop.py (forward new runtime fields)
- scripts/coinbase_operator_digest.py (surface runtime)
- scripts/coinbase_candidate_to_order_audit.py (new; reports external_count, bot_owned_count, max_open_slot_available, impact on ADA/LTC, sol_excluded, trade_permission=none)
- tests/test_coinbase_external_inventory_max_open_slot.py (new; 10+ required scenarios + isolation)
- docs/EXTERNAL_INVENTORY_MAX_OPEN_SLOT_FIX.md (this)
- docs/ACTIVE_HANDOFF.md (top note)

## Verification Performed
- git branch setup per spec (main at 41447eb, new review/p2-024f-... branch)
- py_compile on touched + new
- pytest on new test + related (controlled expansion, dashboards, risk plumbing, safety)
- smokes: dashboard --json, loop --iterations 1 --json, digest --json, audit --json
- safety grep: no forbidden patterns in tests/smokes/source changes
- No orders placed, no broker, no changes to caps/notional/SOL enablement

## Next Success Metric
First closed broker-backed net P/L cycle from an expanded-symbol (ADA/LTC/BTC/etc.) trade under the (now correctly gated) pilot. External SOL remains untouched by bot.

## References
- P2-024D: CONTROLLED_LIVE_SYMBOL_EXPANSION.md
- P2-024E diagnostic
- SOL_MANUAL_REMEDIATION_DECISION_TREE.md (operator still owns any manual action on SOL)
- BROKER_TRUTH_AND_PL_EVIDENCE_GATE.md
- ANTI_STALE...WATCHDOG.md
