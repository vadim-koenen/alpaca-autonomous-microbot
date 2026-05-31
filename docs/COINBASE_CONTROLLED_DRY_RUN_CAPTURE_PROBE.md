# P2-011I — Controlled Dry-Run Broker-Data Capture Probe

**Status:** Proof / instrumentation only. No logger writes. No production changes.

## Purpose

This patch adds a self-contained, controlled harness (`scripts/coinbase_dry_run_capture_probe.py`) that exercises the P2-011H opt-in dry-run capture seam inside `PositionManager` using fully deterministic, sanitized Coinbase-like payloads.

It proves the seam works end-to-end for both entry and exit legs while guaranteeing:
- Zero file system writes
- Zero calls to the production append-only logger
- Raw broker payloads are preserved exactly
- Correct readiness / blocking decisions based on presence or absence of direct broker facts

## What Was Added

- `scripts/coinbase_dry_run_capture_probe.py` — the main controlled probe/harness
- `tests/test_coinbase_controlled_dry_run_capture_probe.py` — dedicated tests for the probe
- `docs/COINBASE_CONTROLLED_DRY_RUN_CAPTURE_PROBE.md` (this file)

No changes were made to:
- `position_manager.py` (the seam added in P2-011H is exercised as-is)
- Any live trading, strategy, risk, sizing, order submission, scheduler, LaunchAgent, config, .env, or runtime code
- `ACTIVE_HANDOFF.md`

## How the Probe Works

1. Defines several `ProbeScenario` objects with realistic (sanitized) payloads:
   - Good entry with one fill + stable ID + fee
   - Good exit with direct sell proceeds (`filled_value`) + stable ID + fee
   - Exit missing direct sell proceeds
   - Fill missing stable ID (trade_id / entry_id)
   - Fill missing per-fill fee
   - Order marked filled but no fills returned from historical endpoint

2. For each scenario it:
   - Builds a `MagicMock` broker that returns the controlled `get_order_status` and `get_historical_fills` responses.
   - Instantiates `PositionManager(..., dry_run_capture=True)`
   - Triggers the exact seam methods (`_maybe_dry_run_capture_entry` / `_maybe_dry_run_capture_exit`)
   - Captures the `CaptureResult` objects stored in `pm._dry_run_captures`
   - Verifies readiness and blocking reasons against expectations

3. All execution is in-memory. The production `coinbase_fill_logger.append_coinbase_fill_row` is never invoked.

## Key Proof Points

- Default behavior of `PositionManager` (dry_run_capture=False) is completely unaffected.
- When the flag is True, the seam correctly calls `broker.get_historical_fills(order_id=...)` and the P2-011G capture helpers.
- Raw order status and raw fills payloads are stored verbatim in the result.
- `logger_ready` is True only when all required direct broker facts are present.
- Any missing fact (stable per-fill ID, per-fill fee, direct sell proceeds on exit) correctly produces blocking reasons and `logger_ready=False`.

## Running the Probe

```bash
python3 scripts/coinbase_dry_run_capture_probe.py
```

Or via pytest (recommended for CI):

```bash
python3 -m pytest tests/test_coinbase_controlled_dry_run_capture_probe.py -q
```

## Relationship to Previous Patches

- Reuses the inert `get_historical_fills` wrapper (P2-011E)
- Reuses `reconcile_order_with_fills` (P2-011F)
- Reuses `capture_entry` / `capture_exit` (P2-011G)
- Exercises the actual seam added to `position_manager.py` in P2-011H

This patch is the next logical step: a controlled, repeatable way to drive the seam with known-good and known-bad data before any write path is ever considered.

## Safety / Non-Regression

All existing Coinbase-related tests continue to pass:

- test_coinbase_entry_exit_capture
- test_coinbase_order_fills_reconciliation_proof
- test_coinbase_fill_logger
- test_coinbase_fill_logging_contract_check

No production logging code was executed or modified.

---

P2-011I complete. Controlled dry-run probe added. Logger hook remains blocked. No writes of any kind.
