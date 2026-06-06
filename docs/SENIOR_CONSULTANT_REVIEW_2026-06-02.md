# Senior Consultant Review — Investing Bot

**Reviewer:** Claude (Opus) as senior strategy/architecture/risk consultant
**Date:** 2026-06-02
**Repo state verified:** `main = c395e2b` (P2-025B), working tree clean except a local edit to `docs/ACTIVE_HANDOFF.md`. Read-only smokes for execution-quality, market-context, and opportunity dashboard all run and emit valid JSON with `trade_permission=none`.
**Caveat:** I could not re-run the full pytest suite in my sandbox (the `.venv` is a macOS build and won't execute under Linux; system Python lacks pytest). I relied on git history, the report smokes, and direct reading of `journal_coinbase_crypto.csv`, `strategy_crypto.py`, `order_manager.py`, `broker_coinbase.py`, and `config_coinbase_crypto.yaml`. The brief's claim of `962 passed` at this commit is consistent with the git log and I have no reason to doubt it.

---

## Executive Assessment

- **Overall health:** Operationally safe, economically unproven, and **mis-prioritized**. The safety scaffolding is excellent. The trade economics are not just unproven — they are *proven negative* and the system is structurally configured to not see that.
- **Biggest strength:** Disciplined, reversible, gate-first engineering. Every patch preserves the same non-negotiables, nothing touches live risk, and the read-only registries are clean.
- **Biggest risk:** **The team is building measurement scaffolding around a strategy that the existing data already shows is losing money — and the `unsafe_to_aggregate` gate is hiding that fact.** The journal contains **47 live, broker-recorded closed cycles from May 25–Jun 2 with a 1/47 win rate (~2%) and cumulative net ≈ −$1.03.** This is not "no profit evidence yet." It is *repeatable evidence of loss* that the profit-readout gate refuses to aggregate. The brief is optimizing for a cleaner measurement of a result we can already see.
- **Immediate priority:** Stop adding read-only layers. (1) Aggregate the journal you already have and confront the −$1.03 / 2%-win reality; (2) kill the structurally-unprofitable micro paths still trading live; (3) build a backtest/replay harness so thresholds are validated against real-fee economics *before* any further capital or cap increase.

---

## Critical Gaps / Flaws

1. **The live result is already negative and the architecture hides it.** 47 live closed cycles, **46 losers**, net ≈ −$1.03. `profit_readout=unsafe_to_aggregate` is being treated as "we don't know yet," but the journal *is* broker-backed (real order IDs, fill prices, fees). The gate's purity standard ("perfect numeric-safe direct capture") is preventing the team from acting on adequate evidence. **You are 25 patches deep into measuring something the journal already answers.**

2. **Exits are essentially time-based only — there is no working profit-taking.** Of 47 live exits, **46 fired on "max hold time 90min exceeded"** and exactly **1 on a stop-loss**; zero clean take-profit exits. Config sets `take_profit_pct: 3.00` and `stop_loss_pct: 1.50`, but a 90-minute window on BTC/ETH almost never travels 3%, so the bot reliably holds to the timeout and dumps at the prevailing (usually adverse-after-fees) price. **The exit policy, not the entry signal, is the dominant cause of losses.**

3. **Strategy proliferation with overlapping live paths, including a structurally-impossible one.** Live exits came from four distinct strategies: `recovered` (13, net −0.65), `coinbase_exploration` (19, −0.24), `coinbase_probe` (13, −0.08), `mean_reversion` (2, −0.07). `coinbase_probe_enabled: true` with `coinbase_probe_notional_usd: 0.50` is **still enabled** — a $0.50 ticket against ~$0.012 round-trip fees is a ~2.4% break-even hurdle that no sane signal clears. This path *cannot* be profitable and is still running.

4. **No backtest / replay / simulation harness exists anywhere in the repo.** I searched scripts, tests, and root: nothing for backtest, replay, or strategy simulation over historical bars. Every threshold (RSI bands, regime gates, 90-min hold, 3%/1.5% targets, fee buffer) is set by intuition and validated only by watching live money. This is the single largest *capability* gap and it is not on the brief's P2-025C–G roadmap.

5. **The brief mis-locates several gaps that are actually already built — wasting future Codex cycles.** Reading the code: a fee/break-even gate already exists and runs in the live path (`coinbase_fee_aware_pilot.py`, wired into `strategy_crypto.py` ~L960–1016); entries already use `order_type="limit"` (not market) at every proposal site; reconciliation modules already exist (`coinbase_order_fills_reconciliation.py`, `coinbase_fill_proceeds_reconciliation_report.py`, `coinbase_fill_logger.py`); and a candidate-to-order audit already exists (`scripts/coinbase_candidate_to_order_audit.py`). The *real* missing pieces are narrower than the brief states (see Architecture below). Building "a fee model" or "a candidate tracker" from scratch would duplicate existing code.

---

## Recommended Next Patch

- **Patch ID:** P2-025C *(replacing the proposed "product metadata adapter" as the next patch)*
- **Title:** Journal-truth profit aggregator + structurally-unprofitable-path shutoff (offline analysis + config-only kill switch)
- **Why this next:** It is the highest-leverage, lowest-risk move available. It converts 8 days of already-captured broker-backed cycles into an honest P/L and win-rate readout, and it stops the live paths that are mathematically guaranteed to lose. It needs no live broker calls, no cap increase, no new risk. It directly attacks the core bottleneck — "can we prove net profitability?" — using data already on disk, and it removes the daily fee bleed while you decide what to do. Product metadata (old P2-025C) is real but lower-leverage; it prevents *invalid* orders, not *unprofitable* ones.
- **Files likely touched:**
  - New: `scripts/coinbase_journal_truth_pnl_report.py` (offline; reads `journal_coinbase_crypto.csv`).
  - New: `tests/test_coinbase_journal_truth_pnl_report.py` (fixture-backed).
  - Edit (config only): `config_coinbase_crypto.yaml` — set `coinbase_probe_enabled: false`; confirm `disable_legacy_btc_probe_when_enabled: true` is effective; document that `recovered` and `mean_reversion` live entry paths are paused pending backtest.
  - New: `docs/JOURNAL_TRUTH_PNL.md`.
- **Acceptance criteria:**
  - Report emits, from the journal only: total live closed cycles, wins, losses, win rate, gross P/L sum, fees sum, **net P/L sum**, and a per-strategy and per-symbol breakdown.
  - Report explicitly labels output as `journal_recorded_broker_backed` and distinguishes it from the stricter `numeric_safe_direct_capture` standard — i.e., it does **not** silently overwrite the existing `profit_readout` gate; it adds an honest second readout the operator can see.
  - Column-index parsing is robust to blank/WARN rows (the journal has malformed/short rows that shift naive CSV splits).
  - Config change verifiably disables the $0.50 probe path with no other gate relaxed.
  - Smoke output on current journal reproduces ≈ 47 cycles, 1 win, net ≈ −$1.03 (sanity anchor).
- **Tests:** Fixture journal with known rows → asserts exact win count, net P/L, per-strategy sums; asserts malformed rows are skipped, not miscounted; asserts the report never emits a `buy/sell/order/risk_increase` field; asserts config kill switch flips `coinbase_probe_enabled` to false and that no notional/cap/max-open value changes.
- **Safety constraints:** Offline only; no broker calls; no `.env`; no `--live-read-only`; no order/cancel/close; no restart/`launchctl`; no risk/notional/cap/max-open change; **only** flips the probe-enable flag (a *reduction* in activity, never an increase). `risk_increase=not_approved`, `scaling_allowed=false` preserved.

---

## Recommended Patch Sequence After That

1. **P2-025D — Offline backtest / replay harness (fixture + recorded-bars).** Replay historical OHLCV (start with recorded fixtures, then opt-in CoinGecko/Coinbase candles) through `strategy_crypto` + the fee model and report net P/L per threshold set. This is the missing capability that lets every later decision be evidence-based. No live anything.
2. **P2-025E — Exit-logic overhaul (offline design + simulated).** Replace "90-min hard dump" with: working take-profit, trailing stop, and a *fee-aware* minimum-edge exit (don't realize a loss into fees on a timeout if the position is within noise). Validate against the P2-025D backtester before any live change.
3. **P2-025F — Maker-first / post-only execution.** Narrow scope: entries already use limit orders, so this is `post_only=True` + a maker lifecycle (place → wait → reprice/cancel-if-stale → never silently cross to taker → reconcile partials). Cuts the fee hurdle roughly in half. Paper/fixture first.
4. **P2-025G — Coinbase product metadata + live execution-quality feed** (the brief's old P2-025C, now correctly sequenced): product increments/min-size/status + live book/depth to drive symbol ranking and prevent rounding-invalid orders. Needed before re-enabling broader live entries.
5. **P2-026 — All-asset read-only opportunity registry.** Only after crypto spot shows a positive backtested + live edge. Model stocks/ETFs/derivatives/prediction-markets as research-only; do not go live.

---

## Architecture Recommendations

- **Trading engine:** Consolidate the four overlapping live entry strategies into **one** gated path. The current `recovered` / `probe` / `exploration` / `mean_reversion` sprawl makes attribution and tuning nearly impossible and is responsible for most of the loss. One strategy, one config block, one set of thresholds, backtested.
- **Data/trend layer:** Keep advisory-only (correct as-is). The registries (P2-024A/025B) are fine as scaffolding but should not grow further until they have a live source behind them *and* a backtest proves the signal adds edge. Don't build more offline source models.
- **Fee/execution model:** A break-even/fee-drag model already exists and runs live — good. Upgrade it in place: tie it to the *actual* account fee tier (already fetched in `broker_coinbase.py` ~L1223), add a depth/slippage estimate for $5–$10 notional, and make it a **hard pre-trade reject** (not just a strategy-time skip) inside `order_manager` so every path inherits it. Do not let Coinbase preview PNL (fee-excluding) ever override it — the code already treats it as advisory; keep it that way.
- **Reconciliation/P&L:** Stop waiting for the "perfect" numeric-safe single cycle. The journal is broker-recorded and adequate for decision-making *today*. Maintain two readouts: `journal_recorded` (act on this now) and `numeric_safe_direct` (the rigorous standard you keep for eventual scaling sign-off). The current single all-or-nothing gate is producing analysis paralysis.
- **All-asset roadmap:** Correct in principle, premature in practice. At ~8–12% and with crypto spot net-negative, all-asset work is a distraction. Gate it behind "crypto spot shows positive backtested edge AND ≥1 month of positive live net P/L."
- **App/product layer:** Stabilize JSON contracts you *already* emit (dashboard, exec-quality, market-context all produce clean JSON). The missing one is the **journal-truth P/L contract** from the recommended patch. Don't build UI; freeze the backend contracts (`status`, `pnl`, `open_positions`, `blocked_candidates`, `risk_state`, `symbol_rankings`, `market_context`) and version them. That is "app-ready" without premature UI.

---

## Risk Policy Recommendations

- **Trade frequency:** 0–1/day is the right *ceiling*, but the real fix isn't frequency — it's that **current trades are −EV regardless of frequency**. Trade frequency should drop to **zero live entries** for the unproven paths until a backtest shows positive net-of-fee edge. The `max_trades_per_day=3` emergency ceiling is fine; lower the *operating* target to 0 until edge is proven.
- **Risk cap:** Hold all caps exactly where they are. Do **not** increase notional, exposure, or `max_open_positions`. Nothing in the data justifies more capital at risk; the data argues for less activity, not more.
- **Evidence required before scaling (propose as explicit config gate):**
  - **≥ 30** closed cycles on the *consolidated* strategy, post-fee, in the **backtest**, with net P/L > 0 and max drawdown within tolerance; **then**
  - **≥ 20** live closed cycles at current $5–$10 size with **win rate ≥ 45%** and **cumulative net P/L > 0 after fees**; **and**
  - maker-fill rate ≥ 70% (if maker-first shipped); **and**
  - reconciliation agreement between journal and broker fills within a tight tolerance on every one of those cycles.
  - Only when *all* hold does `scaling_allowed` flip — and even then, size increases stay small and human-approved.
- **Stop conditions:** Keep daily loss stop ($2–$3) and 2-loss/day halt. Add a **cumulative** stop: if live net P/L stays negative after the next 20 cycles of any "improved" strategy, halt live entries and return to backtest. Codify "structurally-impossible economics" as a permanent gate: reject any path whose min ticket × fee rate implies a break-even hurdle above a configured ceiling (e.g., 1.5%).

---

## Codex Prompt Draft

> **Task (P2-025C): Journal-truth P/L aggregator + disable structurally-unprofitable live probe.**
> Branch `review/p2-025c-journal-truth-pnl-and-probe-shutoff`. **Offline only. No live broker calls, no `.env`, no `--live-read-only`, no orders, no restart/launchctl, no risk/notional/cap/max-open changes.**
>
> 1. Add `scripts/coinbase_journal_truth_pnl_report.py`: read `journal_coinbase_crypto.csv`, filter `mode=live`, `action=EXIT`. Compute total cycles, wins (pnl_usd>0), losses, win rate, sum gross_pnl, sum fees_paid, sum pnl_usd, plus per-strategy and per-symbol breakdowns. Parse by header name (not fixed index); skip blank/WARN/short rows safely. Emit `--json`. Tag output `readout_class="journal_recorded_broker_backed"` and include `numeric_safe_direct_capture_available=false`. Must NOT emit any buy/sell/order/size/risk field and must NOT modify the existing `profit_readout` gate.
> 2. Config-only change in `config_coinbase_crypto.yaml`: set `coinbase_probe_enabled: false`. Change nothing else (no notional, cap, max_open, symbol, or threshold edits). Add a comment documenting that `recovered` and `mean_reversion` live entries are paused pending backtest (P2-025D).
> 3. Add `docs/JOURNAL_TRUTH_PNL.md` explaining the two-readout model.
> 4. Add `tests/test_coinbase_journal_truth_pnl_report.py` with a fixture journal: assert exact win count, net P/L, per-strategy sums, malformed-row skipping, no forbidden output fields, and that the config kill switch flips probe off while all caps/notionals are unchanged.
>
> **Acceptance:** smoke on the real journal reproduces ≈47 cycles / 1 win / net ≈ −$1.03. All new tests pass; full suite stays green. Do not merge to main without ChatGPT/Vadim approval.

---

## Red Flags / Things Not To Do

- **Do not interpret `unsafe_to_aggregate` as "no information."** You have 47 broker-backed live cycles. Act on them. Continuing to build capture/redaction/resolver layers to reach a "cleaner" version of a known-negative result is the central failure mode here.
- **Do not increase caps, notional, `max_open_positions`, symbols, or enable any new asset class.** Nothing in the evidence supports it; the evidence argues the other way. (Preserves all §14 non-negotiables.)
- **Do not keep the $0.50 probe (or any sub-$3 live ticket) running.** It is mathematically incapable of beating fees; every cycle is a guaranteed donation to Coinbase.
- **Do not ship more read-only registries before a backtest harness exists.** The marginal registry has near-zero leverage; the missing backtester has the most.
- **Do not "fix" entries while ignoring exits.** 46/47 losses exit on a timeout, not a signal. Tuning RSI/regime entry gates without fixing the 90-minute forced-dump exit will not move net P/L.
- **Do not let trend/news/sentiment gain trade authority, do not bypass the fee-drag guard, do not let external/staked SOL become tradable, do not restart the live bot without `RESTART_APPROVED`, and never touch `com.vadim.price-path-logger`.** (Restating §14 — all preserved by the recommendation above.)

---

### Appendix — Evidence pulled directly from the repo (2026-06-02)

- `git rev-parse --short HEAD` → `c395e2b`; log matches brief through P2-025B.
- Live closed cycles in `journal_coinbase_crypto.csv` (`mode=live`, `action=EXIT`): **47**, dated 2026-05-25 → 2026-06-02.
- Wins (pnl_usd > 0): **1**. Cumulative net pnl_usd: **≈ −$1.03**.
- Exit reasons: **46 × "max hold time 90min exceeded"**, **1 × stop-loss**, **0 clean take-profits**.
- Net by strategy: `recovered` −0.6482 (13), `coinbase_exploration` −0.2354 (19), `coinbase_probe` −0.0829 (13), `mean_reversion` −0.0666 (2).
- `config_coinbase_crypto.yaml`: `coinbase_probe_enabled: true`, `coinbase_probe_notional_usd: 0.50`; `take_profit_pct: 3.00`, `stop_loss_pct: 1.50`.
- `strategy_crypto.py`: entries propose `order_type="limit"` at all sites; fee-drag pilot eval wired ~L960–1016.
- `broker_coinbase.py`: `place_limit_order` → `limit_order_gtc(..., post_only=False)` (~L987–993); live fee tier fetched (~L1223).
- No backtest/replay/simulation module found in `scripts/`, `tests/`, or root.
