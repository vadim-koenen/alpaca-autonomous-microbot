# P2-011G — Inert Coinbase Entry/Exit Capture Wiring Proof

**Status:** Advisory / Proof-only. No logger hook. No live behavior changes.

## What Was Added

- `coinbase_entry_exit_capture.py`
  - Thin, pure, side-effect-free capture layer on top of the P2-011F reconciliation helper.
  - Provides `capture_entry(...)`, `capture_exit(...)`, and the unified `capture_leg(...)`.
  - Returns a `CaptureResult` that makes logger readiness, blocking reasons, and raw payloads explicit.
  - Contains a strong ADVISORY ONLY header per ACTIVE_HANDOFF rules.

- `tests/test_coinbase_entry_exit_capture.py`
  - Focused tests proving the capture abstraction works for entry and exit legs.
  - Covers blocking conditions (missing proceeds, missing stable IDs, etc.).

- `docs/COINBASE_ENTRY_EXIT_CAPTURE_WIRING_PROOF.md` (this file)

No changes were made to:
- `broker_coinbase.py` (get_historical_fills remains the only addition from P2-011E)
- `main.py`, `position_manager.py`, `order_manager.py`, `journal.py`, strategies, runtime, LaunchAgents, config, or risk files.
- `coinbase_fill_logger.py` or any write paths.

## Design

The new module is a "wiring proof" layer. It represents the future seam where one would call:

```python
order_status = broker.get_order_status(order_id)
fills = broker.get_historical_fills(order_id=order_id)
result = capture_exit(order_status, fills, symbol=symbol, ...)
```

In this patch, the functions are **never** called from any live code path. They exist only to prove the data shape and readiness logic are correct.

## Key Findings from This Patch

- The capture layer cleanly surfaces:
  - `has_direct_sell_proceeds` for exit legs
  - `has_stable_fill_ids`
  - `has_direct_fees`
  - `logger_ready` + `blocking_reasons`

- When using the existing high-quality fixtures from prior patches, entry legs with complete data become `logger_ready`.
- Exit legs are correctly blocked when `filled_value` (direct sell proceeds) is missing on the SELL order payload.
- Missing stable per-fill IDs (trade_id / entry_id) correctly blocks readiness.

## Live Behavior

**None changed.**  
`grep` verification at the end of the patch confirmed:
- No new calls to `append_coinbase_fill_row`
- No references to `logs/coinbase_fills.csv` from new code
- The new `coinbase_entry_exit_capture` module is not imported by any live trading file.

## Logger Hook Status

**Still explicitly blocked.**

This patch does not:
- Wire the capture functions into `position_manager.py` or anywhere else.
- Call `append_coinbase_fill_row`.
- Mark any readiness flag that would enable logging.

Even when `CaptureResult.logger_ready == True` for a perfect fixture, the hard rule of the series is respected: **no writes, no hook**.

## Missing Facts Still Blocking Real Fill Logging (as of P2-011G)

1. **Direct sell proceeds for exit legs** — Requires reliable `filled_value` (or equivalent) from the SELL order status payload of `close_position` orders. This is not yet captured in the live flow.
2. **End-to-end exit leg capture** — We have the reconciliation math, but we have not yet proven in a live (even inert) path that we actually fetch the exit order status + its fills after a close.
3. **Production wiring of the capture seam** — The functions exist but are not called from the two known safe points (post-entry reconciliation and post-exit).

## Recommended Next Patch

P2-011H (or equivalent) should:

- Add the first narrow, **still-inert** capture call sites (behind a test-only or dry-run-only flag) at the entry reconciliation point and the exit point in `position_manager.py`.
- Exercise `capture_entry` / `capture_exit` with real payloads returned by the broker (via the already-proven `get_order_status` + `get_historical_fills`).
- At that point, if all direct facts + stable IDs are present for both legs, a subsequent guarded patch could introduce the first writes to the append-only logger.

This keeps the safety invariant: we only enable logging after the full chain (fetch → reconcile → capture → readiness check) has been exercised with actual broker data in the real code paths (even if writes are still disabled).

---

P2-011G complete. Narrow inert capture wiring proof. All safety rules followed. Logger hook remains blocked.
