# P2-011E — Coinbase Historical Fills Wrapper Proof

**Status:** Discovery / Proof only. No logger hook. No live changes.

## What Was Added

- File: `broker_coinbase.py`
- New inert method: `BrokerCoinbase.get_historical_fills(product_id=None, order_id=None, **kwargs) -> list[dict]`

The method follows the exact existing patterns in the file:
- Uses `self._client.get_fills(...)` (matching SDK style used by list_orders/get_order/etc.)
- Wrapped in `_retry(..., self)`
- Uses `_r()` normalization and `_cb()` for product_id
- Returns list of raw/normalized fill dicts
- Does nothing unless explicitly called

## Live Behavior

- **No change.** The method is never called from `main.py`, `position_manager.py`, `order_manager.py`, strategies, journal, or any runtime/launchd path.
- Completely inert addition for future capture proof.

## Fields Preserved as Direct Broker Facts (from raw payload)

From the wrapper + test fixtures:
- product_id
- order_id
- trade_id / entry_id (stable per-fill identifier)
- trade_time / time
- side
- price (per fill)
- size (per fill)
- fee / commission
- fee_currency
- liquidity_indicator (maker/taker)
- Full raw fill dict available to caller

## What Remains Unproven (Logger Hook Still Blocked)

Per the hard rule of this patch series:

- Direct capture of exit order status for sell legs (close_position flow) is still not implemented in this patch.
- End-to-end reconciliation of order + fills for both entry and exit legs has not been wired.
- Stable per-fill idempotency for multi-fill orders when both trade_id and entry_id are missing is not yet solved in production paths.
- No proof yet that we can safely write to the append-only logger without estimates for fees/proceeds on exit legs.

**Conclusion after this patch:** Logger hook remains **blocked**.

## Recommended Next Patch

P2-011F or equivalent should:
1. Wire a narrow capture point (likely in position_manager after entry reconciliation and after exit close) that calls both `get_order_status` (for the order) **and** `get_historical_fills(order_id=...)`.
2. Implement reconciliation logic that matches fills to their parent order.
3. Add real (sanitized) capture of exit order fills.
4. Only then evaluate whether the logger hook can be enabled with proper idempotency and direct-fact guarantees.

## Validation Performed

- py_compile on broker_coinbase.py: clean
- All new tests pass (mocked, no live calls)
- git diff --check: clean
- No other files modified outside allowed set

---

P2-011E complete. Minimal wrapper + proof only. Safety invariants preserved.
