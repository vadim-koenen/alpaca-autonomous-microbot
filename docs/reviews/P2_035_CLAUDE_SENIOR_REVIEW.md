# P2-035 — Claude Senior Review

**Reviewer:** Claude (senior technical reviewer / systems architect / product strategist)
**Date:** 2026-06-09
**Repo baseline:** `main` at `f903731` (one `auto: handoff sync` commit past the `2ac2df9` P2-034B baseline; `2ac2df9` present).
**Mode:** read-only review. No orders, no broker mutation, no restart, no `.env`, no `main.py` edits, no merge/push to main.

> **Environment caveat (important for interpreting this review):** this review ran in a Linux sandbox over the synced repo folder. It can read all repo/runtime/state/log **files** and run git/awk read-only. It **cannot** reach the Mac's live processes or ports, so `launchctl`, `ps auxww`, `curl http://127.0.0.1:8080/...`, the Mac-venv `pytest`, and `pbcopy` were **not executed here** — those must be run on the Mac by ChatGPT/Codex. Live-process and app-shell-port confirmations below are inferred from fresh heartbeat/state files, not from a process table.

---

## 1. Executive summary

Both bots are live, flat, and healthy at the runtime level: fresh heartbeats, no halt, no kill switch, `STOP_TRADING` absent, SOL correctly fenced as external/staked. The P2-034 resume/reconciliation/restart sequence did its job — the system came back safely and is observable.

But the **core economic problem is unchanged and now has one more data point confirming it.** The bot re-entered BTC/USD live, exited on the 90-minute max-hold timer, and lost to fees again. Journal truth is now **51 live closed cycles, 1 win (~2%), cumulative net −$1.4405**, with **48/51 exits time-based**. Today's Coinbase P/L is −$0.0619, gross-positive-but-fee-negative. This is the same fee-drag loop documented since the June 2 review; resuming live added a cycle of confirmation, not edge.

**Bottom line:** safe to keep running **only as tiny-size, no-scale learning/telemetry** while the economics are fixed offline. There is no demonstrated edge to scale. The highest-value next work is (a) lightweight live-monitoring hardening, (b) the fee/exit guardrail + timeout fix, and (c) the offline backtester bake-off already specced — not app features or asset expansion, which should be sequenced behind a proven (or explicitly accepted-as-negative) economic model.

## 2. Live status (from local files/logs only, 2026-06-09 ~12:30 UTC)

| Check | Finding | Source |
|---|---|---|
| Coinbase live? | **Yes** — status=running, mode=live, pid 20475 | `runtime/coinbase_heartbeat.json` |
| Alpaca live? | **Yes** — status=running, mode=live; **crypto INACTIVE** (agreement unsigned) | `runtime/alpaca_heartbeat.json`, `logs/alpaca.launchd.out.log` |
| STOP_TRADING absent? | **Yes, absent** | `runtime/STOP_TRADING` not present |
| Heartbeats fresh? | **Yes** — Coinbase last_loop 12:29:20Z, Alpaca 12:29:32Z; now ~12:29:58Z (≈30–40s) | heartbeats |
| Open positions? | **None** — `positions: {}` (saved 12:08:06Z) | `state/coinbase/open_positions.json` |
| Daily P/L? | Coinbase **−$0.0619**; Alpaca **$0.00**. Equity $59.88, BP $59.07, trades_today=2, consecutive_losses=1 | coinbase heartbeat |
| Active blockers? | **None** — halt_reason None, last_error None, no ENTRY_BLOCKED in recent log | heartbeat, log tail |
| SOL handled correctly? | **Yes** — external_staked, bot_inventory=false, blocks_new_entries=false, manual_close_allowed=false, operator_approved | `state/coinbase/external_inventory.json` |
| App shell running? | **Cannot confirm from sandbox**; per P2-034E it was offline. Mac must run the `curl :8080` checks | n/a |
| Cumulative live net (all cycles) | **−$1.4405 over 51 cycles, 1 win (2.0%)** | `journal_coinbase_crypto.csv` via `audit_snapshot.sh` |

## 3. Critical safety gaps

**Severity-ordered. None is an active emergency requiring STOP_TRADING right now, but two are real hygiene/leak issues.**

1. **Account IDs logged in cleartext (PRIVACY/LEAK).** Every `PERMISSIONS:` line prints the full account identifier — Coinbase (`Account: <uuid, redacted>`) once/minute, and Alpaca (`Account: <numeric, redacted>`). Logs are committed/synced artifacts; this is exactly the class of value the project rules say never to print. **Fix: redact account IDs in the permissions logger.** (Redacted here per scope.)
2. **Loose runtime transcripts untracked in repo root.** `p2_034d_controlled_restart_transcript.txt` and `p2_034e_post_restart_observation_transcript.txt` sit untracked at repo root. Risk: accidental `git add .` commits runtime artifacts to main. **Fix: move under `docs/reviews/` or add to `.gitignore`.**
3. **SOL exit-check fires every loop and errors.** `position_manager | SOL/USD: invalid price data from broker, skipping exit check` logs ~once/minute. SOL is correctly *non-tradable*, but it's still entering the per-loop exit-check path and erroring. Low severity, but it (a) spams logs and (b) could mask a real price-data failure on a tradable symbol. **Fix: short-circuit external/staked inventory before the exit-check/price-fetch path.**
4. **Stale-heartbeat false confidence (latent).** Heartbeat freshness is currently good, but "fresh file" is trusted as "healthy bot." If the writer thread survives while the trading loop wedges, the heartbeat could look fresh while the bot is effectively dead — the failure mode behind the earlier 48h blocker. **Mitigation: dead-man's semantics tied to loop progress + an external (app-closed) alert channel.** (Tracked in P2-035A.)
5. **App-shell/API truth mismatch (latent).** If the app shell serves cached or last-known state while the bot has moved on, the dashboard can show wrong truth. With the shell currently offline this is dormant, but it must show staleness explicitly when relaunched.
6. **Fee-drag loop with no economic pre-trade gate.** The bot will keep taking structurally fee-negative trades because nothing rejects an entry whose expected net edge can't clear the ~1.2–1.6% Coinbase round-trip fee wall. Not unsafe to the account (caps hold), but it is a guaranteed slow bleed. (P2-035C.)
7. **Duplicate-process risk — mitigated, verify.** A per-broker PID lock exists (`acquire_process_lock`, `runtime/<broker>.lock`). Confirm on the Mac that only one `main.py --mode live` per broker is running (the `ps` check couldn't run here). The check→write is not atomic; hardening tracked separately.

## 4. Profit / strategy findings

- **Timeout exits are the dominant mechanism of loss.** 48/51 live exits are the 90-minute max-hold. The strategy effectively has **no working profit-taking exit** — it holds and dumps. Take-profit 3.0% rarely triggers inside 90 min on BTC/ETH; stop-loss 1.5% occasionally; the timer does the rest, realizing tiny gross moves into fee losses.
- **Fees overwhelm gross.** Coinbase low-volume fees are ~0.60% maker / 0.80% taker → **~1.2–1.6% round-trip**. The replay break-even was ~0.74% symmetric (~1.48% round trip). A 90-minute micro-move cannot reliably clear that. Today's −$0.0619 on a gross-positive trade is the pattern in miniature.
- **Coherence check:** size ($5–10), fee model, TP/SL, max-hold, and candidate selection are **not jointly coherent**. A 90-minute horizon with a 3% TP on low-vol majors, on a 1.2–1.6% fee venue, is a structural mismatch — the exit horizon is too short to reach the TP and too fee-expensive to profit from noise.
- **Edge to scale? No.** 1 win in 51 cycles, net negative, direction quality ~coin-flip in prior replay (direction_match 0.5). There is no statistical case for scaling; size must stay capped.
- **What's needed before live edge:** maker/post-only execution (cuts fee toll ~1.6%→1.2%, but does **not** by itself clear the wall); a **minimum-expected-net-edge pre-trade gate**; volatility/spread/liquidity filters; and an exit model that targets moves larger than the round-trip fee. Critically, **none of these should be tuned on the current home-grown replay** (it matched reality only ~50% of the time) — validate on the bake-off engine first.
- **Shadow learner / backtest / parity stack:** present but not yet the decision authority. Until a backtester reproduces the 51 live cycles faithfully (direction_match ≥ 0.85), its outputs can't gate live changes. This is the gating dependency for all strategy work.

**Recommendation:** keep live in **tiny-size learning/telemetry mode only**. Do the economics fix offline. Consider whether 90-min scalping on Coinbase is the wrong *strategy class/venue* entirely (longer-horizon swing, or a lower-fee venue) rather than something tunable.

## 5. Desktop & mobile app roadmap

- **Current state:** `docs/APP_SHELL_MAC_LAUNCHER.md` exists; a localhost HTTPS app shell with `/api/status`, `/api/runtime-truth`, `/api/profit-readout` endpoints is built but **was offline** at review time.
- **Architecture recommendation: shared read-only backend first**, then desktop, then mobile companion. Do not build two UIs against divergent logic.
  - **Backend:** one local service that reads the same runtime/state/journal truth the bot writes, exposes versioned read-only JSON, and **explicitly surfaces staleness** (heartbeat age, last-loop age) so the UI can never imply fresh when it isn't.
  - **Desktop first** (matches your preference): local-only binding (127.0.0.1), HTTPS already present. Read-only dashboard: live state, P/L, positions, alerts, safety-gate status, strategy decision + plain-language explanation, audit log.
  - **Mobile second:** a mobile-web companion over **LAN or a cloud-assisted read-only relay** — never expose control to the network. Read-only on mobile to start.
- **Controls (later, gated):** STOP_TRADING create/clear and pause/resume behind **explicit multi-step confirmation**; mobile should be **read-only or alert-only** to avoid fat-finger live actions. Kill switch must be a single unambiguous control with a confirm.
- **Auth/safety:** localhost-only by default; if LAN/cloud, require auth + TLS; broker/account isolation in the UI (clearly label Coinbase vs Alpaca; never blend P/L); full audit log of any control action.
- **Notifications:** the missing piece from the 48h incident — at least one **external, app-closed** channel (push/email) for: heartbeat stale, blocked >30 min, failed close, duplicate process, daily-loss stop hit.

## 6. Asset expansion roadmap

- **Sequence:** Coinbase crypto (live, capped) → Alpaca equities/ETFs (after edge exists) → precious-metals via ETFs (e.g., broad gold/silver ETFs) → broader crypto majors. **Ignore Alpaca crypto** until the crypto agreement is signed (currently INACTIVE; bot correctly disables it).
- **Fee-first gating:** every new asset must pass a **break-even-vs-fee/spread screen** before live. The lesson from crypto is that micro-size + high round-trip cost = guaranteed bleed. Equities/ETFs at Alpaca are commission-free but have spread/slippage and the $10 Alpaca balance is too small to matter yet.
- **Risk allocation:** max exposure **per broker** and per asset class, enforced centrally; never let one broker's positions consume another's risk budget (the SOL-slot bug class). Keep `max_open_positions` and notional caps per-broker.
- **Trade-cap design:** keep **fixed small cap now** ($10 absolute). Move to **hybrid (balance-relative with an absolute ceiling)** only after edge is demonstrated — and even then the ceiling stays until explicitly raised by Vadim. Balance-relative sizing on a negative-edge strategy just scales the bleed.
- **Liquidity/fee/spread requirements:** per-symbol min liquidity, max spread, and min-expected-net-edge gates, shared across asset classes.

## 7. Prediction systems & external signals

- **Advisory-only by default.** News/social/sentiment and shadow-learner outputs must not influence live entries until validated. Keep the existing `trading_authority=none` posture.
- **Path to influence (strict):** offline backtest on faithful data → walk-forward (rolling retrain, no leakage) → **live shadow scoring** (predict, log, never trade) for a meaningful sample → only then allow it to *gate* (veto) entries, and only later to *propose*. Veto power before proposal power.
- **Validation bar:** a signal earns live influence only if it improves net-of-fee outcomes in walk-forward **and** in live shadow scoring, with an explainability record per decision.
- **Infra:** a small **SQLite feature store** (timestamped features + outcomes + decision explanations) is the right lightweight backbone — it serves backtest, shadow scoring, the dashboard's "why" panel, and later the sports module. Avoid heavyweight ML infra at this scale.
- **Overfitting guards:** walk-forward only, out-of-sample holdout, no hyperparameter tuning on the test window, prefer simple robust signals. (This is exactly the failure mode the FinRL literature warns about.)

## 8. Sports-betting research module

- **Strictly research/advisory.** No sportsbook connections, no wagering, no automation, no ToS/legal bypass. Paper-only simulation phase, indefinitely, until a separate legal/compliance/ToS review is done.
- **Shared code, separated execution:** it can reuse the **prediction/feature-store/backtest/walk-forward/shadow-scoring** infrastructure, but must live behind a hard boundary from any brokerage/order path — a separate module, separate storage namespace, no import path to execution.
- **Concerns to flag now:** data quality/availability (odds/lines data is messy and often ToS-restricted), bankroll-risk modeling (Kelly-style sizing is its own discipline), and the same overfitting trap amplified by small samples. Treat predicted edge with extreme skepticism.
- **Phase plan:** model + paper-sim + calibration metrics (Brier score, calibration curves) only. No money, ever, without the separate compliance review.

## 9. Git / repo hygiene

- **Branch/HEAD:** on `main` at `f903731`. `2ac2df9` present.
- **Working tree:** `MM docs/ACTIVE_HANDOFF.md` (staged+unstaged modifications); untracked `p2_034d_controlled_restart_transcript.txt`, `p2_034e_post_restart_observation_transcript.txt` at repo root.
- **Actions:** (1) move/relocate the two loose transcripts under `docs/reviews/` or gitignore them; (2) finish/clean the `ACTIVE_HANDOFF.md` change and refresh it for P2-034E + this review; (3) update app-shell docs to note the shell was offline and add a "relaunch + verify endpoints" runbook; (4) restart docs appear current (P2-034D); (5) commit this P2-035 review doc on a review branch only.
- **Do not commit:** runtime/state JSON, logs, transcripts (except sanitized copies intentionally under `docs/reviews`).

## 10. Recommended next patches (ranked)

> Legend — **Live-safe?** = can run while bot is live without restart. **Needs STOP/restart?**

### P2-035A — Immediate live monitoring hardening  *(do first)*
- **Goal:** external (app-closed) alerting + dead-man's heartbeat tied to loop progress; redact account IDs in logs.
- **Why:** the 48h blocker proved in-app/file-only alerting is insufficient; account-ID leak is an active hygiene defect.
- **Files:** alerting/heartbeat modules, permissions logger, `scripts/` watchdog, docs.
- **Tests:** stale-heartbeat triggers alert; account-ID redaction in log output; alert fires with app closed (manual Mac test).
- **Safety risks:** low; observation-only. Don't touch order path.
- **DoD:** a forced stale heartbeat and a simulated failed close both produce an external alert; logs contain no raw account IDs.
- **Live-safe?** Yes. **Needs STOP/restart?** No (alerting); log redaction ideally applied at next natural restart, not a forced one.

### P2-035B — App shell relaunch + dashboard availability
- **Goal:** reliable local relaunch of the app shell; endpoints serve truth with explicit staleness.
- **Why:** shell offline = no operator visibility; dashboard must never imply fresh-when-stale.
- **Files:** app shell launcher/server, `docs/APP_SHELL_MAC_LAUNCHER.md`, app-shell tests.
- **Tests:** the four `test_app_shell_*` suites (run on Mac); endpoint returns heartbeat age + staleness flag.
- **Safety risks:** low (read-only server). Bind localhost only.
- **DoD:** `curl :8080/api/runtime-truth` returns current truth + staleness; tests green on Mac.
- **Live-safe?** Yes. **Needs STOP/restart?** No.

### P2-035C — Profit / fee-drag guardrail  *(highest economic leverage)*
- **Goal:** mandatory pre-trade **minimum-expected-net-edge gate**: reject entries whose expected move can't clear round-trip fees + spread + slippage buffer.
- **Why:** directly stops the structural bleed; nothing currently rejects fee-negative entries.
- **Files:** `risk_manager.py` / strategy entry path (logic add, no cap/strategy change), config (thresholds), tests.
- **Tests:** fee-negative candidate is skipped with reason; fee-positive candidate passes; fee rate parameterized.
- **Safety risks:** medium (touches entry gating) — must be reject-only, never loosen existing gates; keep `main.py` untouched if possible.
- **DoD:** offline replay shows fee-negative entries rejected; live shows skip reasons; no cap/notional change.
- **Live-safe?** Yes (it only *reduces* trades). **Needs STOP/restart?** Restart only to load the new gate; can wait for a natural one.

### P2-035D — Strategy timeout / exit review
- **Goal:** evaluate (offline) replacing the 90-min hard-dump with fee-aware/trailing/target exits — **on the bake-off backtester**, not the current replay.
- **Why:** timeout exits cause 48/51 losses; but must be validated on a faithful engine.
- **Files:** `eval/` backtester work, strategy exit module (offline branch), docs.
- **Tests:** exit alternatives improve net-of-fee vs timeout on validated replay.
- **Safety risks:** low (offline). No live change until validated.
- **DoD:** a documented exit policy that beats timeout on the validated engine.
- **Live-safe?** Yes (offline). **Needs STOP/restart?** No.

### P2-035E — Desktop app foundation
- **Goal:** read-only desktop dashboard over the shared backend (live state, P/L, positions, gates, decision explanations, audit log).
- **Why:** operator visibility; foundation for later gated controls.
- **Files:** app shell/desktop UI, backend contracts, docs, tests.
- **Tests:** renders from runtime truth; shows staleness; no control actions in v1.
- **Safety risks:** low (read-only). **Live-safe?** Yes. **Needs STOP/restart?** No.

### P2-035F — Mobile companion planning
- **Goal:** plan a read-only mobile-web companion (LAN/cloud-assisted relay), no control actions.
- **Files:** design doc only at this stage.
- **Safety risks:** none (planning). **Live-safe?** Yes. **Needs STOP/restart?** No.

### P2-035G — Multi-asset expansion guardrails
- **Goal:** per-broker exposure caps, per-asset fee/spread/liquidity screens, Alpaca equities/ETFs read-only registry; keep Alpaca crypto disabled until agreement signed.
- **Files:** risk allocator, asset registry, config, tests.
- **Safety risks:** medium — must not enable anything live without screens passing. **Live-safe?** Yes (registry read-only). **Needs STOP/restart?** No.

### P2-035H — Prediction / shadow-learner integration
- **Goal:** SQLite feature store + live shadow scoring (predict-and-log, no trade authority).
- **Files:** feature store, shadow scorer, dashboard "why" panel, tests.
- **Safety risks:** low if strictly advisory. **Live-safe?** Yes. **Needs STOP/restart?** No.

### P2-035I — Sports research / prediction module (paper-only)
- **Goal:** reuse prediction infra for sports modeling; paper-sim + calibration only; hard boundary from execution.
- **Files:** separate module + storage namespace.
- **Safety risks:** compliance/ToS — research only, no sportsbook/wager. **Live-safe?** Yes (offline). **Needs STOP/restart?** No.

## 11. Final recommendation

- **Continue trading live now?** Yes, but **only as tiny-size, capped, learning/telemetry** — not as a profit attempt. It is net-negative with no edge; the value of running is operational telemetry, not P/L.
- **Keep size capped?** **Yes — absolutely.** $10 absolute cap stays. No scaling, no balance-relative sizing, until edge is demonstrated on a validated backtester.
- **Fix before scaling:** (1) external alerting + dead-man's heartbeat + account-ID redaction (P2-035A); (2) fee-drag pre-trade edge gate (P2-035C); (3) faithful backtester + exit redesign validated on it (P2-035D + the specced bake-off). Scaling is gated on net-of-fee positive evidence, not on account balance.
- **Build next for the app:** the **shared read-only backend + desktop dashboard with explicit staleness** (P2-035B → P2-035E). Mobile and controls later, gated.
- **ChatGPT/Codex/Gemini next:** run the Mac-only verifications (`ps`/`launchctl`/`curl :8080`/app-shell pytest); land P2-035A and P2-035C; execute the backtester bake-off (`docs/PATCH_SPEC_BACKTESTER_EVAL.md`); relocate the loose transcripts; refresh `ACTIVE_HANDOFF.md`.
- **Defer:** asset expansion beyond Coinbase, prediction live-influence, the sports module, and balance-relative sizing — all behind a proven (or explicitly accepted-as-negative) economic model.

## 12. Verification transcript summary

Run in Linux sandbox over the synced repo (read-only). Mac-only commands (`launchctl`, `ps`, `curl :8080`, Mac-venv `pytest`, `pbcopy`) were **not executed** and must be run on the Mac.

- `git branch --show-current` → `main`; `git rev-parse --short HEAD` → `f903731`; `2ac2df9` present.
- `STOP_TRADING` → **ABSENT**.
- Coinbase heartbeat: running, live, pid 20475, open_positions 0, daily_pnl −0.0619, equity 59.88, bp 59.07, trades_today 2, consecutive_losses 1, halt None, kill_switch false, last_loop 12:29:20Z (fresh).
- Alpaca heartbeat: running, live, open_positions 0, daily_pnl 0.0, last_loop 12:29:32Z (fresh); **crypto INACTIVE** (agreement unsigned), equity $10, options L1.
- `state/coinbase/open_positions.json` → `positions: {}` (flat).
- SOL → external_staked, non-tradable, non-blocking, operator_approved.
- Logs: clean except (a) **account IDs printed in cleartext** every PERMISSIONS line, and (b) **SOL "invalid price data, skipping exit check"** every loop. No ENTRY_BLOCKED, no errors.
- `audit_snapshot.sh` → 51 live cycles, 1 win (2.0%), cumulative net **−$1.4405**, 48/51 timeout exits → **WARN** (probe disabled; no CRITICAL).

## 13. Git status summary

- Branch `main` @ `f903731`. `2ac2df9` present.
- `MM docs/ACTIVE_HANDOFF.md`; untracked `p2_034d_controlled_restart_transcript.txt`, `p2_034e_post_restart_observation_transcript.txt`.
- **No** runtime/state JSON staged. This review doc is the only intended commit, on a review branch.
- **Git writes were not performed from the review environment** (sandbox `.git` unlink restricted); branch creation + commit must be done on the Mac (commands provided in the handback).
