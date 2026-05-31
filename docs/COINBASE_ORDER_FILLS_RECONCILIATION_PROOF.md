# P2-011F — Coinbase Order + Fills Reconciliation Proof

**Patch type:** Pure capture/reconciliation proof only  
**Logger hook:** Explicitly not enabled

## What Was Added

- `coinbase_order_fills_reconciliation.py` — standalone pure helper
- `tests/test_coinbase_order_fills_reconciliation_proof.py` — comprehensive static/mocked test suite (8+ scenarios)
- `docs/COINBASE_ORDER_FILLS_RECONCILIATION_PROOF.md` (this file)
- Reused/extended sanitized fixtures under `tests/fixtures/coinbase/`

The helper `reconcile_order_with_fills(...)` is completely side-effect free. It is **never** imported or called by any live file (main, position_manager, order_manager, broker_coinbase, journal, strategies, runtime, etc.).

## Key Behaviors Proven

- Combines order status payload + historical fills list
- Extracts and classifies all required direct broker facts
- Generates stable idempotency keys: `account_mode:product_id:order_id:(trade_id or entry_id)`
- Correctly blocks on:
  - Missing stable fill ID on any fill
  - Missing per-fill fees
  - Exit legs without direct sell proceeds (filled_value on SELL)
  - Zero fills returned
- Marks derived values (e.g. gross quote value) clearly as `locally_derived`
- Preserves full `raw_order_payload` and `raw_fills_payload`

## Test Results

All tests pass with static fixtures and inline data. No live API calls.

## Live Behavior

**None changed.**  
The reconciliation helper is not referenced from any execution path. It exists solely for proof and future seam design.

## Logger Hook Status After This Patch

**Still BLOCKED**

### Exact Blocking Reasons (per hard rule)

Even when a fixture produces `logger_ready=True`, this patch deliberately does **not** enable the hook. The series safety rule requires:

- Proven direct capture of **exit order status** for close legs (this patch only proves the reconciliation helper, not the wiring)
- End-to-end proof that both entry **and** exit legs can supply direct per-fill fees + stable IDs + sell proceeds together
- The actual append-only call site to `coinbase_fill_logger` must be introduced in a subsequent guarded patch

Current state after P2-011F:
- We now have a clean, testable reconciliation seam
- We have proven the data model and blocking logic
- We have **not** proven the live capture wiring for exits + the final write path

## Recommended Next Patch

P2-011G (or equivalent) should:

1. Add narrow, inert capture logic (still not writing) that actually calls:
   - `broker.get_order_status(...)` for the order
   - `broker.get_historical_fills(order_id=...)` for the fills
2. Wire this at the two known safe seams (post-entry reconciliation and post-exit in position_manager) **behind a feature flag or dry-run-only path**
3. Exercise the reconciliation helper with real (sanitized) captured payloads
4. Only then decide whether to introduce the first guarded write to the append-only logger

This keeps the multi-patch safety invariant intact: no logger writes until the full chain (order + fills + exits + stable IDs + direct facts) is proven end-to-end with the actual broker.

---

P2-011F complete. Proof-only. Safety invariants preserved.
