# ETH Recovery Loop Hotfix Deployment Checklist - 2026-05-28

## Status

This checklist is for a controlled deployment review only.

Restart/reload status: NOT EXECUTED.

The hotfix is not active in the currently running launchd bot processes until
the operator performs a controlled restart or reload.

## Summary

The Coinbase bot could repeatedly churn recovered ETH state when broker
visibility flickered:

```text
drop ETH from local state -> see ETH again -> adopt as broker_recovered -> repeat
```

The existing exit guard already prevented stop-loss, take-profit, and max-hold
exit evaluation for recovered positions. The remaining issue was state cleanup:
if a `broker_recovered` position disappeared from a single broker position
snapshot, the local session could remove it. If the position reappeared later,
the bot adopted it again as a new recovered/manual-review position.

## What Changed

Changed file:

```text
position_manager.py
```

Test file:

```text
tests/test_position_manager_reassociation.py
```

Behavior change:

- `broker_recovered` positions are retained when absent from one broker
  position snapshot.
- Manual-review recovered positions with conservative safety fields are retained
  for operator cleanup instead of being automatically dropped.
- Retained recovered positions remain counted toward exposure.

Recovered ETH remains:

```text
api_controllable=false
exit_evaluation_enabled=false
counts_toward_exposure=true
user_action_required=true
```

## Why This Fixes The Loop

The loop depended on automatic removal of a recovered position during a missing
broker snapshot. By retaining `broker_recovered` manual-review state, the bot no
longer sees the next visible ETH snapshot as a fresh abandoned position.

This preserves the exposure guard and prevents repeated recovered-state
adoption. It does not add any ability to close, modify, or trade ETH.

## Risk Classification

Risk class: Class 2 safety/state-management hotfix.

Reason:

- This touches `position_manager.py`, which affects live position-state behavior
  after restart.
- No trading logic, strategy logic, risk caps, order sizing, Coinbase
  `dead_chop`, broker adapter behavior, or config values were changed.
- No order placement, cancellation, modification, preview, or submission was
  added.

## Verification Already Completed

```bash
python3 -m pytest tests/test_position_manager_reassociation.py -q
python3 -m pytest tests/ -q
python3 -m py_compile position_manager.py
```

Accepted results:

```text
tests/test_position_manager_reassociation.py -> 11 passed
full suite -> 353 passed
py_compile position_manager.py -> passed
```

## Pre-Restart Checks

Run from:

```bash
cd /Users/vadimkoenen/Documents/Claude/Projects/Investing/alpaca-autonomous-microbot
```

Read current bot and state health:

```bash
bash scripts/status.sh
bash scripts/reconcile.sh
bash scripts/state_maintenance_preflight.sh
```

Confirm before restart:

- No manual-review surprise exists except known recovered ETH, if present.
- No duplicate live bot process is running.
- Kill switch is inactive only if that is the intended operator state.
- Coinbase recovered ETH, if present, is understood as manual-review exposure.
- `api_controllable=false` and `exit_evaluation_enabled=false` are preserved for
  recovered ETH.
- No `.env` edits occurred.
- No risk cap, strategy, or config drift occurred.
- No order, close, cancel, preview, or submit command has been run.

## Controlled Restart Plan

Status: NOT EXECUTED.

Only execute during a controlled maintenance window with explicit operator
approval.

Plan:

1. Stop/reload only during the maintenance window.
2. Restart Coinbase first if the ETH recovery loop is the active concern.
3. Verify the Coinbase heartbeat becomes fresh after restart.
4. Verify recovered ETH state is retained rather than repeatedly dropped and
   re-adopted.
5. Verify no automatic close attempt occurs for `api_controllable=false`.
6. Verify exposure guard behavior remains conservative while recovered ETH is
   present.
7. Restart Alpaca only if needed by the same approved maintenance window.

Do not manually run live mode as a substitute for launchd restart verification.

## Post-Restart Checks

Run:

```bash
bash scripts/status.sh
bash scripts/reconcile.sh
bash scripts/state_maintenance_preflight.sh
```

Inspect Coinbase state:

```bash
python3 -m json.tool state/coinbase/open_positions.json
```

Check logs for recovered-state churn and close attempts:

```bash
rg -n "broker_recovered|ABANDONED POSITION|no longer at broker|close_position|EXIT triggered" logs/coinbase.launchd.out.log
```

Expected post-restart result:

- Recovered ETH, if still present, remains one stable manual-review state entry.
- The bot does not repeatedly log drop/adopt cycles for ETH.
- The bot does not attempt an automatic close for recovered ETH.
- Exposure remains blocked or constrained according to existing risk rules.
- Heartbeat files are fresh for restarted bot processes.

## Rollback Plan

If behavior worsens after deployment:

1. Stop the affected bot only through the approved operator-controlled restart
   procedure.
2. Revert the hotfix changes to:

```text
position_manager.py
tests/test_position_manager_reassociation.py
```

3. Re-run:

```bash
python3 -m pytest tests/test_position_manager_reassociation.py -q
python3 -m pytest tests/ -q
python3 -m py_compile position_manager.py
```

4. Do not manually close anything through the bot.
5. Use the Coinbase UI only if the operator independently decides to clean up
   wallet exposure.
6. Re-run status, reconcile, and preflight checks after rollback deployment.

## Explicit Warning

This hotfix is not active in running launchd processes until a controlled
restart or reload is performed.

Do not treat the current running bot behavior as patched until post-restart
verification confirms the new code path is live.

## Final Recommendation

Wait for a controlled maintenance window before restart/reload unless the ETH
recovery loop is actively causing state churn or blocking safe operation.

Do not continue P1-004F or any shadow-learner follow-on work until this hotfix
has been deployment-reviewed.
