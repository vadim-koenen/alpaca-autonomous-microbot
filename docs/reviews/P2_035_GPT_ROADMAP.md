# P2-035 — Roadmap for ChatGPT (PM)

**Author:** Claude (senior review) · **Date:** 2026-06-09 · **Audience:** ChatGPT (project manager / safety gate)
**Scope now:** Coinbase only. Alpaca stays parked (equities/ETFs + crypto) until the Coinbase bot is *proven*. Don't spend cycles on Alpaca features.

> Not financial advice. The capital guidance below is risk-allocation logic derived from the bot's own measured results, not investment advice. Vadim decides the dollars.

---

## 1. Capital: how much to put in right now

**Add nothing beyond what's already there. Keep it at the current ~$60.**

Reasoning from the bot's own data, not opinion:
- 51 live closed cycles, **1 win (~2%)**, cumulative **net −$1.44**. Negative expectancy.
- Adding capital to a negative-expectancy system scales the *loss rate*, not the return. More money = faster bleed, not faster learning.
- The constraint on progress is **edge + fees + operational reliability**, none of which more money fixes.
- At ~$60 with a $10 max ticket, you already have enough to exercise every code path (sizing, fees, fills, reconciliation, alerts). Additional dollars buy zero additional information.

**Capital gate (when adding money becomes rational):** only after the bot clears the go-live evidence bar —
- backtester reproduces live cycles faithfully (direction-match ≥ 0.85), and
- ≥ 20 live closed cycles at current size with **net-of-fee P/L > 0** and **net win rate ≥ 45%**, and
- operational net is in place (external alerting + dead-man's heartbeat + atomic single-instance lock).

Until all three hold, treat the account as a **fixed ~$60 telemetry rig**, not an investment. When the bar is met, scale in *small* (e.g., to $100–$250) with the absolute ticket cap raised only by an explicit written decision — never auto-scaled.

## 2. Coinbase-only execution sequence (Alpaca parked)

Run in this order. Each is gated on the previous. Alpaca work is explicitly deferred.

1. **P2-035A — Operational net (do first).** External (app-closed) alert channel + dead-man's heartbeat tied to loop progress + **redact account IDs in logs** (currently printed cleartext every loop). Verify single-instance lock can't be bypassed.
2. **P2-035C — Fee-drag edge gate.** Mandatory pre-trade check: reject any entry whose expected net move can't clear round-trip fees (~1.2% maker / ~1.6% taker on Coinbase low-volume) + spread + slippage buffer. Reject-only; no cap/strategy loosening. This stops the structural bleed.
3. **Backtester bake-off** (`docs/PATCH_SPEC_BACKTESTER_EVAL.md`). Stand up Jesse / Freqtrade offline, score fidelity vs the 51 live cycles. Decision gate: adopt the engine that hits direction-match ≥ 0.85, or accept the strategy is near-random and pivot strategy class/venue.
4. **P2-035D — Exit redesign.** Replace the 90-min timeout dump (cause of 48/51 losses) with fee-aware take-profit / trailing / target exits — validated on the bake-off engine, not the old replay.
5. **App: desktop dashboard** (section 3) — can proceed in parallel; it's read-only and doesn't touch trading.

Everything else from the full review (multi-asset, prediction live-influence, sports module, Alpaca) is **deferred** until Coinbase shows net-of-fee edge.

## 3. Desktop app — getting it on your Dock

You already have the foundation: a localhost HTTPS app shell (P2-031A/P2-032A) with `/api/status`, `/api/runtime-truth`, `/api/profit-readout`, and `APP_SHELL_MAC_LAUNCHER.md`. The gap is (a) it was offline at review time and (b) it's a browser tab, not a Dock app. Don't rebuild it — wrap it.

**Recommended path (lowest friction, reuses your Python stack):**

1. **Keep the existing localhost server as the backend.** It already serves the truth JSON. Make it always-on via the existing launcher; ensure the dashboard shows **staleness** (heartbeat age) so it never implies fresh-when-stale.
2. **Wrap it in a native window with `pywebview`.** A ~30-line Python entry point opens the localhost dashboard in a real macOS window (no browser chrome). This is far lighter than Electron and stays in Python.
3. **Bundle into a `.app` with `py2app` (or Briefcase).** That produces `Investing Bot.app` — double-clickable, and **drag it to the Dock** for a permanent icon. Add a simple icon (`.icns`).
4. **Read-only v1.** No controls in the window yet — just live state, P/L, positions, gates, last decision + explanation, audit log. Controls (STOP_TRADING toggle, pause/resume) come later, behind an explicit confirm dialog.

**Why this over alternatives:** Electron works but is heavy and adds a JS toolchain; Tauri is lean but adds Rust. Since the dashboard is already a local web app and your codebase is Python, `pywebview` + `py2app` is the shortest path to a real Dock app and keeps one language. If you later want polish or mobile, revisit Tauri.

**App patch sequence:**
- **P2-035B — App shell relaunch + always-on + staleness display.** (Prereq: it must actually be running.)
- **P2-035E1 — pywebview native window** loading the localhost dashboard.
- **P2-035E2 — py2app bundle + .icns icon → drag to Dock.**
- **P2-035E3 — (later) gated controls** with confirm dialogs; mobile companion deferred.

Safety for the app: localhost-only binding; read-only first; any future control action requires explicit confirmation and is written to an audit log; never expose control to the network; keep Coinbase vs (future) Alpaca clearly isolated in the UI.

## 4. What ChatGPT should do next (this week)

1. Land **P2-035A** (alerting + heartbeat + account-ID redaction).
2. Land **P2-035C** (fee-drag edge gate).
3. Kick off the **backtester bake-off** (offline, parallel).
4. Get the **app shell running + bundled to the Dock** (P2-035B → E2), read-only.
5. Keep capital at ~$60. Keep size capped. Do not start Alpaca. Do not scale.

**Standing constraints:** no scaling, no loosened risk gates, no forced trades, no live strategy change without offline evidence, no Alpaca work yet, keys only in `.env`, never print account IDs/secrets, review-branch + ChatGPT/Vadim approval before any merge.
