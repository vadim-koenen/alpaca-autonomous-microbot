# IDE Prompt — P2-035C (fee-edge entry gate) + account-ID redaction

Paste the block below into your IDE coding agent (Cursor / Claude Code, Opus 4.6). It is self-contained. The agent works in the repo, on a review branch, and must not merge or change live behavior beyond what's specified.

---

You are working in the repo `alpaca-autonomous-microbot` (Coinbase crypto trading bot). Implement TWO small, safe patches as separate commits on a new branch `review/p2-035c-fee-edge-gate`. Do NOT merge, do NOT push to main, do NOT change risk caps, sizing, symbols, or restart anything. The live bot is running; these changes only take effect on its next natural restart.

CONTEXT (verified):
- The bot is net-negative: ~51 live cycles, 1 win, cumulative net ≈ −$1.44. Losses are dominated by fee drag on micro trades. Coinbase low-volume fees ≈ 0.60% maker / 0.80% taker → ~1.2–1.6% round-trip. Break-even move ≈ 0.74% symmetric.
- A fee-drag guard already exists (`coinbase_fee_aware_pilot.py`, wired into `strategy_crypto.py` around lines 960–1016, config keys under `crypto:` like `fee_drag_guard_enabled`, `fee_drag_spread_slippage_buffer_rate`). Audit it first — do NOT duplicate it. Strengthen it into a mandatory hard gate.
- Account IDs are printed in cleartext on every PERMISSIONS log line (Coinbase UUID and Alpaca numeric) in the permissions logger — a privacy leak.

TASK 1 — Mandatory minimum-net-edge entry gate (commit 1):
- Find the existing fee-drag/break-even logic. Make it a HARD pre-trade reject in the entry path (`risk_manager.py` or the order/entry path), so EVERY entry, regardless of strategy, is rejected unless: expected_gross_move >= round_trip_fee_rate + spread + slippage_buffer + safety_margin.
- Use the account's real fee tier if already fetched (see `broker_coinbase.py` ~L1223 where maker/taker are read); otherwise default conservatively to maker 0.006 / taker 0.008. Make rates + safety_margin config-driven under `crypto:` (e.g., `min_net_edge_safety_margin`, default a value that puts the hurdle near ~1.3–1.5% round trip).
- On reject: log a clear reason like `ENTRY_SKIPPED reason=min_net_edge_not_met expected=<x> required=<y>` and journal a skip row. Do NOT place the order.
- This is reject-only. It must never loosen any existing gate, raise caps, or force a trade.

TASK 2 — Redact account IDs in logs (commit 2):
- In the permissions logger (search for the `PERMISSIONS: Account:` log line), redact the account identifier — show only a short masked form (e.g., last 4 chars or a hash), never the full ID. Apply to both Coinbase and Alpaca code paths.
- Do not change any other log content.

CONSTRAINTS:
- Coinbase only. No `.env` reads. No secrets printed. No broker/order calls in tests.
- No changes to `main.py` unless strictly required; if required, explain why in the PR description.
- Add/adjust unit tests:
  - fee-negative candidate is rejected; fee-positive candidate passes; rate + margin are read from config; gate cannot be disabled into a fee-negative trade silently.
  - permissions logger output contains a masked ID and never the full account ID.
- Run the full test suite; report pass count. Keep diffs minimal.
- Leave a short PR description summarizing both commits, files touched, and test results. Stop for human (Vadim/GPT) review. Do NOT merge.

ACCEPTANCE:
- Both commits on `review/p2-035c-fee-edge-gate`. Tests green.
- A quick offline demonstration (script or test) showing a sample fee-negative entry is now rejected with a logged reason.
- Logs show masked account IDs only.
