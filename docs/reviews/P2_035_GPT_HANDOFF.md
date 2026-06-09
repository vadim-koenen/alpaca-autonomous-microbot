# P2-035 — Handoff for GPT (session summary + roadmap)

**Date:** 2026-06-09 · **From:** Claude (senior review session with Vadim) · **Scope:** Coinbase only; Alpaca parked.

## What we did this session
1. **Senior review committed** — `docs/reviews/P2_035_CLAUDE_SENIOR_REVIEW.md` + `P2_035_LIVE_STATUS_SPOTCHECK.md` on branch `review/p2-035-claude-senior-review`. Live state at review: both bots running/flat/fresh; Coinbase equity ~$59.88; daily P/L −$0.0619; STOP_TRADING absent; SOL correctly fenced.
2. **Confirmed the core loss mechanism (in code).** `position_manager.py` ~L803–822: stop-loss (−1.5%) and take-profit (+3.0%) are checked each loop, but the **90-minute max-hold timer fires ~94% of exits (48/51) and sells regardless of P/L**. The timer was a "prove it round-trips" placeholder and is now the main loss driver. Fees (~1.2–1.6% round-trip on Coinbase) turn flat exits into losses.
3. **Fee-wall analysis.** Coinbase low-volume ≈ 0.60% maker / 0.80% taker. A 90-min micro-move can't reliably clear it. Maker-first helps but doesn't by itself clear the wall; the real fix is exit logic + strategy horizon.
4. **Capital guidance.** Stay at ~$60. Adding capital to a negative-expectancy bot scales the bleed, not learning. Capital gate = backtester fidelity ≥ 0.85 AND ≥20 live cycles net-of-fee positive at ≥45% win rate AND operational net in place. (Buy-and-hold BTC, if any, must be a SEPARATE Coinbase portfolio or fenced as external inventory so the bot never trades it.)
5. **Killed the Claude credit burn.** Disabled scheduled Claude tasks `coinbase-bot-spot-check` and `bot-handoff-sync` (was every 4h). Replaced with Mac-native `scripts/handoff_status_sync.sh` (zero credits) on launchd `com.vadim.status-sync`. It writes **`docs/STATUS_AUTO.md` on branch `ops/status`** every 4h. Verified working (`synced+pushed`). Setup: `docs/AUTOMATION_SETUP.md`.
6. **Working agreement** — `docs/reviews/P2_035_GPT_WORKING_AGREEMENT.md`.

## GPT: how to operate now
- **Read live truth from `ops/status:docs/STATUS_AUTO.md`** at the start of each session (equity, positions, P/L, cycles/wins/net, audit verdict). No need to ask Claude for status.
- Pull Claude in only for specs/reviews at decision points or when the audit verdict is CRITICAL.
- Commit/push happens on Vadim's Mac (the Cowork sandbox can't write `.git` reliably).

## Roadmap (ordered) toward the real goals
**Now — traction (this week):**
1. **P2-035C** — mandatory minimum-net-edge entry gate (harden the existing fee guard into a hard reject) + **redact account-ID leak in logs**. IDE prompt ready: `docs/reviews/P2_035C_IDE_PROMPT.md`. Live-safe, reject-only.
2. **P2-035A** — external (app-closed) alert + dead-man's heartbeat (the 48h blocker proved in-app/file alerts insufficient).
3. **Backtester bake-off** — Jesse vs Freqtrade vs current replay, scored on fidelity to the 51 live cycles (`docs/PATCH_SPEC_BACKTESTER_EVAL.md`). Gate: direction-match ≥ 0.85.
4. **P2-035D** — exit redesign: replace the blind 90-min timer with trailing-stop + P&L-aware + fee-aware exits; data-driven take-profit. Validate on the backtester BEFORE any live change. This is the profit lever.

**Profit model:** only after P2-035D shows net-of-fee positive in the validated backtester does live edge get re-evaluated; only then is scaling/capital considered.

**App (parallel, read-only):** wrap the existing localhost dashboard with pywebview → bundle with py2app → drag to Dock. Read-only v1; gated controls (STOP_TRADING, pause) later behind confirm dialogs. Details: `P2_035_GPT_ROADMAP.md` §3.

**Later (deferred until Coinbase is proven):** Alpaca equities/ETFs; precious-metals via ETFs; prediction/shadow-learner with SQLite feature store (advisory → shadow-score → veto → propose); sports-betting as paper-only research sharing the prediction infra, hard-walled from execution. All in the full review doc.

## Standing constraints
Coinbase only. ~$60, $10 cap, no scaling, no loosened gates, no forced trades, no live strategy change without offline evidence. Keys only in `.env`; never print account IDs/secrets. Review branch + Vadim/GPT approval before merge. Don't restart the bot without `RESTART_APPROVED`; never touch `com.vadim.price-path-logger`.
