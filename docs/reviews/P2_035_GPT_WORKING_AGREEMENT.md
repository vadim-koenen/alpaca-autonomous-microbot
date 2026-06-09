# P2-035 — Claude ⇄ GPT Working Agreement + Traction Plan

**Date:** 2026-06-09 · **Goal:** stop reviewing in circles, start shipping. One shared context source, clear lanes, one headline fix.

## How we share context (no Claude credits)
- A Mac launchd job runs `scripts/handoff_status_sync.sh` every 4h and writes **`docs/STATUS_AUTO.md`** on branch **`ops/status`** (current bot state + economics digest + audit verdict). Setup: `docs/AUTOMATION_SETUP.md`.
- **GPT:** read `ops/status:docs/STATUS_AUTO.md` at the start of any working session. That's the live truth — equity, positions, daily P/L, cycles/wins/net, audit verdict. No need to ask Claude for status.
- **Claude:** invoked only for (a) reviews at decision points, (b) specs, (c) when the audit verdict goes CRITICAL. Not for routine status. This is the credit-efficient split.

## Lanes (who does what)
- **GPT (PM/safety gate):** sequences patches, enforces the safety constraints, runs the Mac-only checks (`ps`/`launchctl`/`curl :8080`/pytest), owns merge decisions with Vadim.
- **Codex/Gemini (build):** implement one patch per review branch, with tests; never loosen a gate; never scale.
- **Claude (senior review):** spec + adversarial review at gates; not routine coding.

## The headline fix — make exits price-aware (P2-035D)
**Problem (confirmed in code, `position_manager.py` lines 803–822):** exits check stop-loss (−1.5%) and take-profit (+3.0%) every loop, but a 90-minute window on BTC/ETH almost never moves that far, so the **90-minute max-hold timer fires ~94% of exits (48/51) and sells regardless of P/L.** The dominant exit is blind to profit; fees then turn a flat exit into a loss. The 90-min timer was a "prove the bot can round-trip" placeholder — it has served its purpose and is now the main loss driver.

**Scope of P2-035D (offline first, validated on the backtester bake-off):**
1. Replace the blind timeout with a **fee-aware, P&L-aware exit**: do not close a flat/within-noise position just because the clock expired; only force-close on a real signal.
2. Add a **trailing stop** that locks in gains once a position moves favorably.
3. Re-tune take-profit to what price actually does in the holding window (data-driven), not an arbitrary 3%.
4. Add a **minimum-net-edge entry gate** (P2-035C dependency): reject entries whose expected move can't clear round-trip fees (~1.2% maker / ~1.6% taker) + spread + slippage.
**Validate on the Jesse/Freqtrade bake-off** (`docs/PATCH_SPEC_BACKTESTER_EVAL.md`) before any live change — the home-grown replay matched reality only ~50% of the time, so don't tune on it.
**DoD:** on the validated engine, the new exit policy beats the timeout policy in net-of-fee P/L on the 51 historical cycles. No live change until that's shown. No cap/size increase.

## This week — ordered, for traction
1. **P2-035A** — external (app-closed) alert + dead-man's heartbeat + **redact account IDs in logs** (they print cleartext every loop). Live-safe.
2. **P2-035C** — minimum-net-edge entry gate (stops the fee bleed now). Reject-only; live-safe; restart at next natural opportunity.
3. **Backtester bake-off** — stand up Jesse/Freqtrade offline, score fidelity vs the 51 live cycles (`PATCH_SPEC_BACKTESTER_EVAL.md`).
4. **P2-035D** — exit redesign above, validated on #3.
5. **App on the Dock** (parallel, read-only): pywebview wrap of the existing localhost dashboard → py2app bundle → drag to Dock (`P2_035_GPT_ROADMAP.md` §3).

## Standing constraints (unchanged)
Coinbase only (Alpaca parked until proven). Capital stays ~$60, size capped at $10, no scaling, no loosened gates, no forced trades, no live strategy change without offline evidence. Keys only in `.env`; never print account IDs/secrets. Review branch + Vadim/GPT approval before merge. A buy-and-hold BTC position, if any, must be fenced as external inventory or kept in a separate Coinbase portfolio so the bot never trades it.

## Definition of traction (so we know it's working)
- `ops/status` updating automatically (free).
- Account-ID leak closed; external alert tested app-closed.
- Fee-gate live → audit shows fewer fee-negative cycles.
- Backtester reproduces live cycles (direction-match ≥ 0.85) → exit redesign validated → net-of-fee positive in backtest before any live change.
- Dock app showing live read-only truth.
