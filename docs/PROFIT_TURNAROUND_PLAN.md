# Profit Turnaround Plan — for ChatGPT (PM) and Codex (build)

**Date:** 2026-06-02 · **Repo main:** `c395e2b` · **Author:** Claude (senior consultant)
**Companion doc:** `docs/SENIOR_CONSULTANT_REVIEW_2026-06-02.md`

## The problem in one paragraph
The live bot is not "unproven" — it is **proven net-negative**. The journal holds **47 live broker-recorded closed cycles (May 25–Jun 2): 1 win, 46 losses, cumulative net ≈ −$1.03.** Three fixable causes: (1) exits are time-based, not signal-based (46/47 dumped on a 90-min timeout, 0 take-profits); (2) a $0.50 probe path is still live and is mathematically incapable of beating fees; (3) four overlapping live strategies make tuning impossible. The team has been building read-only measurement scaffolding instead of fixing trade economics, and the `unsafe_to_aggregate` gate has been hiding the loss.

## The goal
Move from −EV churn to **demonstrable, backtested, net-of-fee edge** before risking another dollar. Order of operations: **stop the bleed → see the truth → prove edge offline → fix exits → cut fees → only then consider scaling.**

---

## Operating rules (unchanged, non-negotiable)
- No increase to notional, exposure, `max_open_positions`, symbols, or asset classes.
- No live broker calls in any patch below; offline/fixture only unless explicitly stated.
- No restart without `RESTART_APPROVED`; never touch `com.vadim.price-path-logger`; true bot is `com.vadim.coinbase-crypto-bot`.
- Codex does not merge to main without ChatGPT/Vadim approval.
- Keys stay in `.env`, never printed/committed. `risk_increase=not_approved`, `scaling_allowed=false` stay in force.
- Every change must be a *reduction* in live activity or an *offline* analysis until edge is proven.

---

## Phase 0 — Stop the bleed + see the truth (do first, this week)

**P2-025C — Journal-truth P/L aggregator + probe shutoff** *(offline + config-only)*
- Add `scripts/coinbase_journal_truth_pnl_report.py`: from `journal_coinbase_crypto.csv`, filter `mode=live, action=EXIT`; output (JSON) total cycles, wins, losses, win rate, sum gross_pnl / fees / **net pnl_usd**, and per-strategy + per-symbol breakdowns. Parse by header name; skip blank/WARN/short rows. Tag `readout_class="journal_recorded_broker_backed"`; do **not** modify the existing `profit_readout` gate (add a second honest readout alongside it).
- Config-only in `config_coinbase_crypto.yaml`: set `coinbase_probe_enabled: false`. Pause `recovered` and `mean_reversion` live entries (comment + flag). Change nothing else.
- Tests: fixture journal asserts exact win count, net P/L, per-strategy sums, malformed-row skipping, no forbidden output fields, and that the kill switch flips probe off with all caps/notionals unchanged.
- **Done when:** smoke on the real journal reproduces ≈47 cycles / 1 win / net ≈ −$1.03; full suite green; probe path verifiably off.

## Phase 1 — Prove edge offline (the missing capability)

**P2-025D — Backtest / replay harness** *(offline)*
- Replay historical OHLCV (start with recorded fixtures, then opt-in CoinGecko/Coinbase candles) through `strategy_crypto` + the existing fee model. Report net-of-fee P/L, win rate, and max drawdown **per threshold set**.
- No live calls. This is the tool that makes every later decision evidence-based.
- **Done when:** harness reproduces the journal's directional result on matching dates (sanity), and can sweep at least entry thresholds, hold time, and take-profit/stop levels.

## Phase 2 — Fix the economics

**P2-025E — Exit-logic overhaul** *(offline design, validated on P2-025D)*
- Replace the 90-min hard dump with: working take-profit, trailing stop, and a **fee-aware minimum-edge exit** (don't realize a within-noise loss into fees on a timeout). Validate against the backtester before any live change.
- **Done when:** backtest shows the new exit logic raises net P/L vs the current timeout policy on the same data.

**P2-025F — Maker-first / post-only execution** *(paper/fixture first)*
- Entries already use limit orders; set `post_only=True` and add a maker lifecycle: place → wait → reprice/cancel-if-stale → never silently cross to taker → reconcile partials. Roughly halves the fee hurdle.
- **Done when:** simulated maker-fill rate and fee reduction are demonstrated offline.

**P2-025G — Product metadata + live execution-quality feed**
- Product increments / min-size / status + live book/depth to drive symbol ranking and prevent rounding-invalid orders. (This is the brief's old "P2-025C," correctly resequenced to here.)

## Phase 3 — Only after edge is proven
**P2-026 — All-asset read-only opportunity registry.** Model stocks/ETFs/derivatives/prediction-markets as research-only. Do not go live. Gate behind: crypto spot shows positive backtested edge **and** ≥1 month positive live net P/L.

---

## Gate to re-enable broader live trading or scaling (all must hold)
1. Backtest: ≥30 closed cycles on the **consolidated** strategy, net-of-fee P/L > 0, drawdown within tolerance.
2. Live: ≥20 closed cycles at current $5–$10 size, **win rate ≥ 45%**, **cumulative net P/L > 0 after fees**.
3. If maker-first shipped: maker-fill rate ≥ 70%.
4. Journal-vs-broker reconciliation agrees within tight tolerance on every one of those cycles.
Only then may `scaling_allowed` flip — and increases stay small and human-approved.

## Permanent guardrail to add
Reject any strategy path whose `min_ticket × round_trip_fee_rate` implies a break-even hurdle above a configured ceiling (e.g., 1.5%). This makes "structurally-impossible economics" (like the $0.50 probe) impossible to re-enable by accident.

---

## Division of labor
- **ChatGPT (PM/safety gate):** sequence patches as above; enforce the operating rules; require each patch to show its acceptance evidence (smoke output + test pass) before merge; own the merge decision with Vadim.
- **Codex (build):** implement one patch per branch, offline/fixture-first, with tests; never relax a gate; never increase risk; surface backtest numbers, not opinions.
- **Claude (consultant, as needed):** review backtest design and the scaling-gate evidence before any live re-enable; do not use for routine implementation.

## What NOT to do
- Don't build more read-only registries before the backtester exists.
- Don't tune entry signals while the timeout-dump exit is unchanged.
- Don't treat `unsafe_to_aggregate` as "no data" — act on the 47-cycle journal now.
- Don't raise caps/notional/symbols/assets, don't give trend/news trade authority, don't bypass the fee-drag guard, don't make staked SOL tradable.
