# P2-011K — Controlled Aggressive Live Runtime Hardening

**Philosophy (as of this patch):**
- Keep live micro-exploration enabled on Coinbase (small caps).
- Learn from real (tiny) market and execution outcomes.
- Ruthlessly prevent the classes of mistakes that come from our own infrastructure:
  - Duplicate live processes
  - Corrupted daily counters on restart
  - Unclear operational state for the operator

This patch adds infrastructure hardening only. It does not change strategy, sizing, risk parameters, or the decision to keep the fill logger hook blocked until broker facts are proven.

## What Was Added

- `runtime_safety.py` — small module with:
  - Hardened `acquire_live_process_lock` / release (better stale recovery + logging)
  - Conservative `reconstruct_daily_counters_from_journal` + applicator
- `scripts/coinbase_ops_status.py` — read-only operator probe (process count, exposure, recent journal, warnings on duplicates/stale locks)
- `tests/test_coinbase_runtime_lock.py`
- `tests/test_coinbase_restart_safe_counters.py`
- `tests/test_coinbase_ops_status.py`
- This document

No changes were made to strategy logic, TP/SL, symbols, notional/exposure caps, config defaults, .env, LaunchAgents, scheduler, or order submission.

The existing P2-011H `dry_run_capture` seam and P2-011I probe continue to work and were not regressed.

## Process Lock

- Namespace aware (coinbase.lock vs alpaca.lock).
- Stale lock (dead PID) is now recovered with a clear warning instead of silent overwrite.
- Second live process for the same namespace exits early with a clear message before strategy/order flow.
- Different namespaces do not incorrectly block each other.

## Restart-Safe Counters

On startup (same UTC day), we now scan the journal for trades/exits that day and backfill:
- daily_trade_count
- daily_realized_pnl (sum of realized exits today)
- consecutive_losses (best-effort from recent EXIT rows)
- last_trade_at / last_exit_at
- `_last_daily_reset_date` is set to today so `maybe_daily_reset()` does not falsely emit "DAILY RESET" and zero the counters.

If reconstruction cannot be done safely for a particular counter, we leave a conservative value and log it.

## Ops Status Script

Run any time (read-only):

```bash
python3 scripts/coinbase_ops_status.py
python3 scripts/coinbase_ops_status.py --json
```

It surfaces:
- Whether the lock file indicates a live process
- Rough local exposure from state/
- Recent journal activity
- Warnings for duplicate processes or stale locks

## Remaining Limitations (by design for this patch)

- We still do not have perfect per-fill fee truth for exits until the full P2-011x capture + reconciliation work matures and the logger hook is enabled.
- api_error_count reconstruction is conservative (we do not over-count from logs).
- The lock is advisory (file + PID check). On systems without proper signal semantics it is best-effort.

## Next Steps (future patches, not this one)

- When broker-fact proof (P2-011J and follow-ups) confirms direct sell proceeds + stable per-fill IDs + per-fill fees on exits, we can consider enabling the first guarded writes to the append-only fill logger.
- Further lock robustness (e.g., fcntl advisory locks + heartbeat supervision) if needed.
- Making the ops status script part of routine operator workflow / alerts.

---

P2-011K complete. Runtime hardening focused on preventing self-inflicted operational mistakes while keeping controlled live exploration alive under tiny caps.
