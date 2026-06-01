# ANTI-STALE MANUAL-REVIEW BLOCKER WATCHDOG (P2-021C2)

## Why This Exists

The live Coinbase bot can enter a state where entries are repeatedly skipped with:

ENTRY_BLOCKED reason=manual_review_position_open

This is a valid safety mechanism when there is an unresolved bot-owned position (e.g., SOL/USD with broker_close_capability_unconfirmed after failed close attempts).

However, if this state persists indefinitely without operator visibility or escalation, the bot silently stops trading despite having buying power and being "running".

P2-021C2 adds a durable, offline, read-only watchdog that detects when such blockers have become stale, surfaces age/count/severity, distinguishes external locked inventory from true bot-owned unresolved positions, and produces explicit operator action requirements.

It prevents silent indefinite suspension while preserving all existing safety invariants.

## What the Watchdog Detects

- Repeated ENTRY_BLOCKED/manual_review_position_open events in the local journal over a configurable window (default 180 minutes).
- Correlation with open_positions.json having user_action_required + api_controllable=false + manual_review_reason.
- Heartbeat freshness, last trade age, trades_today.
- Classification of the open SOL (or other) position:
  - External/staked/non-bot inventory (staked_external_position, external_inventory_classification, tradable_by_bot=false, bot_inventory=false, manual_close_allowed=false) → reported as external locked inventory; never auto-closed, never treated as bot inventory for P/L or blocking in the same way.
  - True unresolved bot-owned position (bot_opened=true, api_controllable=false or broker close unconfirmed) → still blocks trading, but escalates to STALE_BLOCKER_REQUIRES_OPERATOR_ACTION when age exceeds threshold.
- Stale state bug: repeated manual review blocks in journal but no actual open position with the flag → STALE_STATE_BUG_REQUIRES_RESET_REVIEW.

## What It Refuses To Do (Hard Boundaries)

- Never calls any broker API.
- Never reads .env or prints secrets.
- Never places, cancels, closes, or modifies orders.
- Never auto-unblocks trading or auto-clears state for unresolved bot-owned positions.
- Never writes logs/coinbase_fills.csv or calls append_coinbase_fill_row.
- Never mutates runtime or state files.
- Never lowers risk gates or approves scaling.
- Never treats local journal P/L as broker truth.
- Never treats external staked inventory as bot-owned tradable inventory.

## Safe Operator Flow (Current + Future)

1. Run `python3 scripts/coinbase_operator_status.py` (now includes stale blocker section via P2-021C2 integration).
2. Run `python3 scripts/coinbase_stale_blocker_watchdog.py --json --stale-threshold-minutes 180` for focused diagnosis.
3. If STALE_BLOCKER or STALE_STATE_BUG:
   - Run the P2-021C read-only evidence capture checklist.
   - Obtain explicit human approval for a one-time read-only broker evidence capture (if needed).
   - Only after evidence confirms no bot-owned unresolved position should any state reconciliation or trading resumption for affected symbols be considered.
4. External staked positions: Confirm classification, exclude from bot inventory, do not attempt remediation/close via bot.

This connects directly to the P2-021C read-only evidence capture bridge: the watchdog escalates visibility so that the controlled, human-approved, redacted capture path (P2-021C) can be used when evidence is required.

## Current Live Problem This Addresses

Before P2-021C2, the bot could (and did) sit all day with buying power, in live mode, heartbeat fresh, but 0 trades because of repeated manual_review_position_open blocks, with no age tracking, no severity escalation, and no explicit "operator must act" signal in the main status tools.

The watchdog makes this state loud, aged, classified, and actionable without lowering any safety bars.

## Integration Notes

- The watchdog is a standalone diagnostic.
- Its JSON report is safely pulled into coinbase_operator_status.py for the main operator view.
- Future live-loop integration (periodic call inside the trading loop to update heartbeat with stale fields) is a low-risk follow-up that can be done in a later patch once this diagnostic is proven.

All changes in this patch are read-only, offline, and respect the global hard rules of the project.