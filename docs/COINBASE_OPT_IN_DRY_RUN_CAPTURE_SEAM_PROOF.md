# P2-011H — Opt-in Dry-Run Coinbase Capture Seam Proof

**Status:** Narrow opt-in dry-run only. No logger writes. No default behavior change.

## What Was Done

- Added a minimal opt-in dry-run capture seam inside `position_manager.py` (the actual entry reconciliation and exit execution paths).
- The seam is **completely disabled by default** (`dry_run_capture=False`).
- When explicitly enabled via constructor (for tests or controlled dry-run experiments), it:
  - Calls the inert `broker.get_historical_fills(order_id=...)` (from P2-011E)
  - Calls the P2-011G `capture_entry` / `capture_exit` helpers
  - Records results in `self._dry_run_captures` (in-memory only, for inspection)
  - Logs clearly prefixed "DRY_RUN_CAPTURE[...]" messages
- No other behavior, decisions, P/L, or state is affected.

## Files Changed (minimal)

- `position_manager.py` (tiny guarded additions + private seam helpers + one constructor parameter)
- `docs/COINBASE_OPT_IN_DRY_RUN_CAPTURE_SEAM_PROOF.md` (this file)

No changes to:
- broker_*.py, main.py, order_manager.py, risk_manager.py (per hard rules)
- Any config, .env, LaunchAgents, runtime, strategy, risk, sizing, TP/SL, symbols, or order submission

## Verification Performed

- Default instantiation of PositionManager continues to work with zero behavior change.
- When `dry_run_capture=True` is passed, the seam exercises the full capture + reconciliation path using real (mockable) broker methods.
- All related Coinbase tests continue to pass.
- Grep confirmed: no calls to `append_coinbase_fill_row`, no writes to coinbase_fills.csv, and the seam is never active unless explicitly opted in.

## Logger Hook Status

**Remains blocked.**

This patch proves the *location* of the seam in the real flow. It does not wire any production capture, does not enable writes, and does not relax any blocking conditions from prior patches (missing direct exit proceeds in live close flow, end-to-end stable ID + fee proof on exits, etc.).

## Remaining Gaps Before Any Logger Hook Can Be Considered

- The dry-run seam must be exercised with real broker payloads in a controlled (still non-writing) way.
- Direct sell proceeds from actual close_position orders must be proven in the live(ish) path.
- Stable per-fill IDs + per-fill fees must be present together with exit proceeds for the legs we actually trade.

## Recommended Next Step

If the dry-run seam proves valuable in controlled experiments, the next patch could consider promoting a very narrow, still heavily guarded (feature-flagged, no default) capture that feeds the reconciliation, with the first optional writes behind additional explicit safeguards. But that would be P2-011I or later and would require explicit safety review.

---

P2-011H complete. Opt-in dry-run seam proven in the actual entry/exit flow. All hard rules followed. Logger hook remains blocked.
