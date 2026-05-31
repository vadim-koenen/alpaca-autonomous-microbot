# ACTIVE HANDOFF — Alpaca/Coinbase Autonomous Trading Bot

## P2-014D complete — read-only open/orphan Coinbase position status report

Functional patch commit: `39a3408`

P2-014D added a read-only operator report for Coinbase open/orphan position status:
- current/open position evidence
- dropped/re-associated/orphan evidence
- broker close capability status
- manual-review requirements
- profit/readout blockers
- machine-readable `--json` output

Current report result:
- SOL/USD unresolved/re-associated broker-close blocker detected from local journal evidence
- broker close capability remains unconfirmed unless direct later evidence proves otherwise
- realized P/L remains unsafe-to-aggregate while open/orphan status is unresolved
- report is intentionally conservative and advisory-only

Safety / scope:
- no runtime/config/order/risk/strategy files changed
- no broker API calls added
- no `.env` reads added
- no fill logger writes enabled
- no `logs/coinbase_fills.csv` changes
- no `append_coinbase_fill_row` production call
- no leverage, margin, futures, perps, options, commodities, GOLD/SILVER/XAU/XAG enabled

Profit / momentum readout:
- build momentum: strong positive
- trading/profit readout: unsafe-to-aggregate
- no risk/cap/aggressiveness increase is justified

## P2-014C complete — local review-gate automation for Grok/Codex patches

Functional patch commit: `1e66b94`

P2-014C added reusable local review-gate scaffolding to reduce copy/paste, false positives, and human verification errors during Grok/Codex buildout.

Changed files:
- `scripts/local_review_gate.py`
- `tests/test_local_review_gate.py`
- `docs/GROK_CODEX_REVIEW_GATE.md`

Purpose:
- verify review branches with one command
- check expected changed files
- block protected runtime/config/order/risk/log files
- require explicit permission for `docs/ACTIVE_HANDOFF.md` changes
- avoid false positives where `append_coinbase_fill_row` appears only in protective tests
- block production fill logger writes/references unless explicitly approved
- produce compact final reports for ChatGPT merge review

Safety / scope:
- no live trading behavior changed
- no strategy/order/risk/symbol/cap/config/runtime behavior changed
- no broker API calls added
- no `.env` reads added
- no fill logger writes enabled
- `logs/coinbase_fills.csv` remains protected
- no leverage, margin, futures, perps, options, commodities, GOLD/SILVER/XAU/XAG enabled

Profit / momentum readout:
- build momentum: strong positive
- trading/profit readout: still unsafe-to-aggregate
- no risk/cap/aggressiveness increase is justified


## P2-014B complete — read-only fill/proceeds/P&L reconciliation readout

Functional patch commit: `1eb2007`

P2-014B improved `scripts/coinbase_fill_proceeds_reconciliation_report.py` and its tests so the local reconciliation report now clearly separates:
- direct broker facts available from local rows
- locally derived values
- unsafe/missing values
- matched-pair summaries
- open/unresolved position evidence
- SOL/USD broker-close blocker evidence

Verified:
- `tests/test_coinbase_fill_proceeds_reconciliation_report.py`: 16 passed
- `tests/test_coinbase_fill_logging_contract_check.py`: 10 passed
- `tests/test_coinbase_entry_exit_capture.py`: 5 passed
- report smoke passed
- patch remained read-only/local CSV inspection only

Current report result:
- direct order/client-order coverage exists
- direct sell proceeds are not available locally
- direct fees are not available locally in enough form for immutable P/L aggregation
- no paired cycle has both actual buy cost and direct sell proceeds locally available
- realized P/L remains unavailable / unsafe-to-aggregate
- SOL/USD open/re-associated blocker remains active
- broker close capability remains unconfirmed

Safety / scope:
- no runtime/config/order/risk/strategy files changed
- no fill logger writes enabled
- no `append_coinbase_fill_row` production call
- no `.env`, `logs/coinbase_fills.csv`, LaunchAgent, state, runtime, or broker API behavior changed
- no leverage, margin, futures, perps, options, commodities, GOLD/SILVER/XAU/XAG enabled

Profit / momentum readout:
- build momentum: positive
- trading/profit readout: unsafe-to-aggregate
- no risk/cap/aggressiveness increase is justified


## P2-014A — ACTIVE_HANDOFF live status preservation + P2-014 preflight (docs-only)

Functional patch commit (latest complete): `e90e678` (P2-013C: read-only local price data coverage diagnostics + targeted regressions)

P2-014A (this patch): docs-only update to preserve latest live Coinbase operational/reconciliation blocker status in ACTIVE_HANDOFF.md. No runtime strategy, config, risk, order, .env, LaunchAgent, or logging behavior changes of any kind. This patch exists solely to improve operational/profit truth by documenting grim reality accurately.

**Preserved live status (as of latest local auto-sync; treat strictly as operational/reconciliation blocker, NOT strategy success):**
- Coinbase equity around $45.73
- SOL/USD open/re-associated (bot-origin position)
- broker close capability unconfirmed
- close failures logged (position may have been dropped from tracking after 3 failed close attempts)
- latest functional patch remains e90e678
- no risk/aggressiveness increase justified

P2-013C diagnostic results (retained for continuity):
- outcome evaluator remains read-only
- price data status remains read-only
- local run still reports `Evaluable telemetry rows: 0`
- hit rates remain non-actionable until dense local price coverage exists
- strategy tuning remains premature

Safety / scope (unchanged):
- no strategy/order/risk/symbol/cap/config/runtime changes
- no leverage, margin, futures, perps, options, commodities, GOLD/SILVER/XAU/XAG order placement enabled
- fill logger remains blocked
- `append_coinbase_fill_row` is not called by production code
- no `.env`, `logs/`, or `coinbase_fills.csv` changes
- profit/readout remains required in every status update and handoff

Profit / momentum readout:
- last verified realized P&L remains `-$0.0358` unless newer journal/status output proves otherwise
- current outcome scoring is still not actionable because evaluable telemetry rows remain `0`
- **current profit readout is unsafe-to-aggregate until direct fill/proceeds/fees reconciliation is proven** (see P2-014 preflight below)
- no risk/cap/aggressiveness increase is justified

<!-- This file is the shared context layer between Claude (advisor) and ChatGPT/Copilot (executor). -->
<!-- Update this file after every session. Both AIs read from here. Do not let it go stale. -->

**Last updated:** 2026-05-31 18:57 UTC — P2-014C complete; added local review-gate automation for Grok/Codex patches to reduce copy/paste, false positives, and human verification error. Latest functional patch commit 1e66b94. No strategy/order/risk/symbol/cap/config/runtime behavior changed. Profit readout remains unsafe-to-aggregate until direct fill/proceeds/fees and open-position status are proven.
**Updated by:** Grok (per P2-014A ritual)
**Repo:** https://github.com/vadim-koenen/alpaca-autonomous-microbot.git  
**Branch:** review/p2-014a-coinbase-live-status-and-reconciliation-preflight

## P2-014 Preflight — Profit Readout Safety (reconciliation blocker)

**Current profit readout (realized P&L, outcome scoring, hit rates) is unsafe-to-aggregate** until direct fill/proceeds/fees reconciliation is proven from broker data for entry and exit legs.

This is especially critical given the open SOL/USD position (broker close capability unconfirmed after logged close failures; position possibly dropped from tracking).

Existing reconciliation modules/scripts/tests already exist and should be reused for the next step:
- `coinbase_order_fills_reconciliation.py` (P2-011F) — pure `reconcile_order_with_fills()` returning `ReconciliationResult` with `direct_broker_fact` / `locally_derived` / `unavailable` classifications for proceeds, fees, filled_value, logger_ready gate, raw payloads preserved, blocking_reasons.
- `coinbase_entry_exit_capture.py` (P2-011G) — inert `capture_leg` / `capture_entry` / `capture_exit` wrappers over the above (never called from live paths in current code).
- `scripts/coinbase_fill_proceeds_reconciliation_report.py` + `tests/test_coinbase_fill_proceeds_reconciliation_report.py`
- `tests/test_coinbase_fill_logging_contract_check.py`
- `tests/test_coinbase_entry_exit_capture.py`

**Next patch should focus on read-only reconciliation reporting**: exercise the above modules against the current journal (and any available local broker history/fixtures for the open SOL position and recent exits) to determine whether stable per-fill trade_ids, actual sell proceeds on exits, and per-fill fees are recoverable. Produce advisory report only. No network calls in tests, no writes, no append_coinbase_fill_row, no live behavior changes, no config/risk/strategy modifications.

Until that proof exists, all P&L, expectancy, and "profit" numbers must be treated as provisional/unsafe-to-aggregate. The SOL position with unconfirmed broker close is an explicit reconciliation blocker.

No risk/aggressiveness increase or strategy changes are justified while this state persists.

---

## 1. Project Identity

Two bots, one repo, running on a Mac under launchd.

| Bot | Exchange | Status | Config file |
|---|---|---|---|
| **Coinbase bot** | Coinbase Advanced | ✅ PRIMARY — active optimization | `config_coinbase_crypto.yaml` |
| **Alpaca bot** | Alpaca | ⏸ SECONDARY — on hold | `config.yaml` |

**Coinbase bot** is the active focus. Running $1 controlled exploration across BTC/USD, ETH/USD, SOL/USD. All current patches (P2-001x through P2-002) are Coinbase-only.

**Alpaca bot** is running but on hold — constant stale quote skips during off-hours, zero trades placed, not current priority. Will revisit when equity market hours align or when Coinbase work reaches a stable plateau.

Note: repo name (`alpaca-autonomous-microbot`) reflects the project's origin. Both bots live here.

---

## 2. Hard Rules (both AIs must respect these always)

```
DO NOT:
  - restart bots
  - run launchctl
  - run live mode manually
  - place / cancel / modify orders
  - edit .env
  - read or print secrets or API keys
  - touch broker_*.py, order_manager.py, risk_manager.py, main.py
  - touch launchd/, state/, runtime files
  - change config_coinbase_crypto.yaml or config.yaml risk caps
  - raise notional, exposure caps, max open positions, or daily loss cap
  - connect prediction/ML outputs to live trading decisions
  - approve paper-to-live model promotion

ALWAYS:
  - Advisory/read-only patches are Class 1 (safest)
  - Live behavior changes are Class 2+ (require explicit approval)
  - New report/script files are always Class 1
  - Tests must accompany new scripts
  - Every new file must have ADVISORY ONLY comment block at top
```

---

## 3. Current Live State

| Item | Value |
|---|---|
| Coinbase equity | $45.73 |
| Coinbase status | RUNNING_BY_LAUNCHD |
| Alpaca equity | $10.00 |
| Alpaca status | RUNNING_BY_LAUNCHD (outside market hours) |
| Kill switch | INACTIVE (trading allowed) |
| Open positions | 1 (SOL/USD — bot_opened, broker_close_capability_unconfirmed) |
| Last Coinbase trade | 2026-05-31T16:30:23 UTC (SOL/USD entry, filled) |
| Last Coinbase exit | 2026-05-25T11:19:39 UTC (ETH/USD, max-hold) |
| Current regime | downtrend (AVAX/USD scan; bot correctly sitting out) |

---

## 4. Coinbase Controlled Exploration Config (do not change)

```yaml
controlled_exploration:
  enabled: true
  approved_symbols: [BTC/USD, ETH/USD, SOL/USD]
  max_single_trade_notional_usd: 1.00
  max_total_exploration_exposure_usd: 6.00
  max_round_trips_per_day: 12
  max_entries_per_symbol_per_day: 4
  per_symbol_cooldown_minutes: 30
  daily_stop_loss_usd: 3.00
  max_consecutive_losses: 3
  max_open_positions: 2

fee_model:
  maker_fee_pct: 0.006   # 0.60%
  taker_fee_pct: 0.012   # 1.20%
  # Round-trip taker break-even: 2.40% gross move required
```

---

## 5. Completed Milestones

| ID | Name | Status |
|---|---|---|
| P1-001 | Shadow learner schema/scaffold | DONE |
| P1-002 | Shadow learner log/state ingestion | DONE |
| P1-003/004 | Outcome labeling scaffold | DONE |
| P1-004B/F | Price history + retrospective/prospective samples | DONE / advisory |
| P1-006 | News/trend context scaffold | DONE |
| P1-006C | Prospective diagnostics — no deployable edge found | DONE |
| P1-006D | Scoring reconciliation | DONE / committed |
| P2-001 | Controlled Coinbase exploration | DONE / live |
| P2-001B | State-aware LRU rotation (BTC→ETH→SOL proven) | DONE / committed `adbebf4` |
| P2-001C | Coinbase exploration fee/performance report | DONE / committed `0a6c82c` |
| P2-001D | Controlled exploration status accuracy fix | DONE / committed `e10a722` |
| P2-001E | Coinbase exit quality report | DONE / committed `535298c` |
| P2-001F | Coinbase maker order audit | DONE / committed `f835e74` |
| P2-001G | Patch completion automation | DONE / committed `5fcca5c` |
| P2-001H | Coinbase live-only performance re-baseline | DONE / committed `9ac606a` |
| P2-001I | Handoff automation daemon | DONE / committed `0028733` |
| P2-002 | Review and commit advisory prediction features | DONE / committed `012ab07` |
| P2-003 | Intra-hold price path logger | DONE / committed `bd89891` |
| P2-004 | Dynamic equity-based Coinbase sizing groundwork | DONE / committed `4903014` |
| P2-005 | Coinbase Price-Path MFE/MAE Analyzer | DONE / committed `7ddf6d7` |
| P2-006 | Coinbase Sizing / Execution / Profitability Reconciliation Report | DONE / committed `49135bc` |
| P2-007 | Coinbase Fill / Proceeds Reconciliation Report | DONE / committed `1b6ce77` |
| P2-008 | Coinbase Immutable Fill Logging Contract Spec | DONE / committed `fbe3867` |
| P2-009 | Open-Source Bot Plumbing Survey | DONE / committed `1b49c11` |
| P2-010 | Coinbase Fill Logging Implementation Discovery | DONE / committed `0bc4d87` |
| P2-010B | Stabilize Coinbase Fill Logging Discovery Report | DONE / committed `d1de493` |
| P2-010C | Remove Volatile Skipped Paths From Discovery Report | DONE / committed `3a7a953` |
| P2-011A | Coinbase Fill Logger Scaffold | DONE / committed `818ded7` |
| P2-011B | Coinbase Fill Response Discovery | DONE / committed `90f68fa` |
| P2-011C | Coinbase Raw Payload Fixture Proof | DONE / committed `081c04b` |
| P2-011D-alt | Coinbase Fills Payload Discovery | DONE / committed `0b2a629` |
| P2-011E | Coinbase Historical Fills Wrapper Proof | DONE / committed `af1eb87` |

---

## 6. Git State (as of last update)

```
Latest functional patch commit: `39a3408`
Commit hashes for handoff updates should be verified with `git log`; this file intentionally avoids storing a self-referential handoff commit hash.
Clean: no dirty tracked files (except handoff update)

Recent commits:
  90f68fa P2-011B: Coinbase Fill Response Discovery
  818ded7 P2-011A: Coinbase Fill Logger Scaffold
  3a7a953 P2-010C: Remove Volatile Skipped Paths From Discovery Report
  d1de493 P2-010B: Stabilize Coinbase Fill Logging Discovery Report
  0bc4d87 P2-010: Coinbase Fill Logging Implementation Discovery
  1b49c11 P2-009: Open-Source Bot Plumbing Survey
  fbe3867 P2-008: Coinbase Immutable Fill Logging Contract Spec
  1b6ce77 P2-007: Coinbase Fill / Proceeds Reconciliation Report
  49135bc P2-006: Coinbase Sizing / Execution / Profitability Reconciliation Report
```

P2-002 advisory prediction features are committed (`012ab07`); do not connect to live decisions without explicit approval.

---

## 7. Current Performance Diagnosis

From confirmed live trade data (6 completed cycles):

| Cycle | Gross | Fee | Net |
|---|---|---|---|
| BTC/USD #1 | -$0.0074 | -$0.0120 | **-$0.0193** |
| ETH/USD #1 | -$0.0046 | -$0.0120 | **-$0.0166** |
| SOL/USD #1 | +$0.0150 | -$0.0121 | **+$0.0029** ✓ |
| BTC/USD #2 | +$0.0039 | -$0.0120 | **-$0.0081** |
| ETH/USD #2 | -$0.0050 | -$0.0120 | **-$0.0169** |
| SOL/USD #2 | -$0.0082 | -$0.0120 | **-$0.0202** |

- **All 26 journal exits are max-hold exits** — SL/TP thresholds have never triggered
- Fee per round trip ≈ $0.012 at $1 notional
- Break-even requires 2.4% gross move in 90 min; actual avg is ~0.1–0.5%
- 1 of 6 net positive. Current expectancy is negative.
- Root cause: fee drag + forced time exits, not execution failure

---

## 8. Active Patch Queue

### IN PROGRESS
**P2-011H completed the narrow opt-in dry-run Coinbase capture seam proof in the actual entry/exit flow. Key finding: `position_manager.py` now has a disabled-by-default `dry_run_capture=False` seam that can call the inert capture/reconciliation helpers only when explicitly enabled, storing results in memory via `_dry_run_captures` and performing no writes. Dedicated tests prove default constructor compatibility, default-disabled behavior, opt-in entry/exit capture behavior, no `append_coinbase_fill_row` calls, no logger writes, and logger readiness remaining blocked when broker facts are missing. Logger hook remains blocked. Next safe patch: P2-011I — controlled dry-run broker-data capture/probe proof to exercise the seam with real or captured broker payloads, still no writes. Do not tune TP/SL, hold time, notional size, symbols, predictions, risk caps, config, runtime, or live strategy until actual fills/proceeds/fees are captured and reconciled.**

### QUEUED (blocked — data + explicit approval required)
- **SL/TP/hold-time tuning** — Class 2; use P2-001E exit-quality and P2-005 MFE/MAE reports only after ≥20 price-path samples, ~2+ weeks of P2-003 data, and explicit human approval

### DO NOT START YET
- Any TP/SL/hold-time config changes
- Notional increase
- P2-003 entry quality gate
- Connecting P2-002 features to live decisions
- Alpaca equity work (after-hours stale quotes are expected, not a bug)

---

## 9. How to Update This File

**After Claude session:** Claude updates sections 3, 6, 7, 8 based on what was reviewed.  
**After Copilot execution:** Update section 8 (mark patch done, add new queued item).  
**After each git push:** Update section 6 with new HEAD commit.  

Keep this file committed and pushed. Both AIs reference it at session start.

---

## 10. Session Start Checklist

For any AI beginning a session on this project:

```bash
cd /Users/vadimkoenen/Documents/Claude/Projects/Investing/alpaca-autonomous-microbot

# 1. Confirm repo state
git status --short
git log --oneline -5

# 2. Confirm bots running
bash scripts/status.sh

# 3. Confirm exploration state
CONFIG_FILE=config_coinbase_crypto.yaml python3 scripts/controlled_exploration_status.py

# 4. Read this file
cat docs/ACTIVE_HANDOFF.md
```

Do not recommend or execute anything until all four commands have been run and reviewed.

---

## 11. Automated Status Log
<!-- Appended automatically by Claude scheduled tasks. Do not edit manually. -->
<!-- Format: YYYY-MM-DD HH:MM | equity=$X | positions=X | regime=X | errors=X | head=commit -->

- 2026-05-29 20:30 | equity=$40.94 | positions=0 | regime=dead_chop | errors=0 | head=adbebf4
- 2026-05-30 02:53 | equity=$40.94 | positions=0 | regime=dead_chop | errors=0 | head=8bbaae0 | P2-001D committed+pushed, auto-sync installed, P2-001E now active
- 2026-05-30 03:35 UTC | head=535298c | P2-001E committed+pushed; Class 2 SL/TP/hold tuning awaiting explicit approval
- 2026-05-30 03:53 UTC | head=f835e74 | P2-001F committed+pushed; 6/6 entries likely passive-priced; actual maker/taker fee flags still unproven
- 2026-05-30 03:56 UTC | head=f835e74 | P2-001F committed+pushed; 6/6 entries likely passive-priced; actual maker/taker fee flags still unproven
- 2026-05-30 04:05 UTC | head=5fcca5c | P2-001G complete; Automates ACTIVE_HANDOFF updates, handoff commits, pushes, and raw GitHub verification
- 2026-05-30 04:12 UTC | head=9ac606a | P2-001H complete; Re-baselines Coinbase exploration using live-only BTC/ETH/SOL data excluding dry_run, ALGO, probe, and recovered noise
- 2026-05-30 04:23 UTC | head=0028733 | P2-001I complete; Adds polling daemon to automate ACTIVE_HANDOFF updates
- 2026-05-30 12:41 | equity=$40.94 | positions=0 | regime=dead_chop | errors=0 | head=b4da00f
- 2026-05-30 12:41 UTC | head=012ab07 | P2-002 complete; Shadow learner features reviewed for future-data leakage and committed
- 2026-05-30 12:52 UTC | head=bd89891 | P2-003 complete; Adds read-only Coinbase price path logger to collect intra-hold snapshots for true MFE/MAE analysis before Class 2 tuning
- 2026-05-30 14:28 UTC | head=4903014 | P2-004 complete; Adds Coinbase-only dynamic equity sizing framework while preserving hard $1 trade cap, exposure cap, stop-loss cap, and existing risk gates
- 2026-05-30 14:44 UTC | head=7ddf6d7 | P2-005 complete; Adds advisory-only Coinbase price-path MFE/MAE analyzer, tests, and runbook to evaluate intra-hold excursions before any Class 2 tuning.
- 2026-05-30 18:26 UTC | head=49135bc | P2-006 complete; Adds advisory-only Coinbase sizing/execution reconciliation report, tests, and runbook. The report explains fixed-cap controlled exploration, legacy $0.50 vs $1.00 sizing, missing sell-fill data, fee drag, max-hold exits, and why P/L must remain unavailable when sell proceeds are not present.
- 2026-05-30 19:15 UTC | head=1b6ce77 | P2-007 complete; Adds advisory-only Coinbase fill/proceeds reconciliation report, tests, and runbook. Confirms 37 exit/sell rows, zero direct sell proceeds, zero fee rows, zero reconstructable gross/net P/L pairs; realized P/L must remain n/a until immutable fill/proceeds/fee logging is fixed.
- 2026-05-30 19:35 UTC | head=fbe3867 | P2-008 complete; Adds Coinbase immutable fill logging contract spec, read-only contract checker, and tests. Confirms `logs/coinbase_fills.csv` is missing and realized P/L must remain n/a until actual fill/proceeds/fee logging is implemented safely.
- 2026-05-30 19:45 UTC | head=1b49c11 | P2-009 complete; Adds open-source bot plumbing survey, read-only reference checker, and tests. Integrates Freqtrade, Hummingbot, Jesse, OctoBot, and CCXT as architecture references only. No external code copied, no installs, no live behavior changes, no strategy tuning. Next patch should be P2-010 read-only Coinbase fill logging implementation discovery.
- 2026-05-30 19:50 UTC | head=0bc4d87 | P2-010 complete; Adds read-only Coinbase fill logging implementation discovery, generated report, scanner, and tests. Identifies broker/status/journal seams for future append-only fill logging. No live behavior changes, no external API calls, no config/risk/state/runtime/launchd changes, and no strategy tuning.
- 2026-05-30 19:55 UTC | head=d1de493 | P2-010B complete; Stabilizes Coinbase fill logging discovery report generation and tests deterministic regeneration. No live behavior changes, no external API calls, no config/risk/state/runtime/launchd changes, and no strategy tuning.
- 2026-05-30 20:00 UTC | head=3a7a953 | P2-010C complete; Removes volatile `.git/` skipped-path preview entries from the Coinbase fill logging discovery report and confirms deterministic regeneration. No live behavior changes, no external API calls, no config/risk/state/runtime/launchd changes, and no strategy tuning.
- 2026-05-30 23:06 UTC | head=818ded7 | P2-011A complete; Adds tested append-only Coinbase fill/proceeds/fee logger scaffold, deterministic CSV schema, append/header safety tests, raw payload serialization tests, and implementation plan. No broker/journal hook, no live behavior changes, no external API calls, no config/risk/state/runtime/launchd changes, and no strategy tuning.
- 2026-05-30 23:26 UTC | head=90f68fa | P2-011B complete; Adds read-only Coinbase fill response discovery script, generated report, and tests. Confirms logger hook remains blocked because direct sell proceeds and actual exit-leg fees are not yet proven from current broker response handling. No broker/journal hook, no live behavior changes, no external API calls, no config/risk/state/runtime/launchd changes, and no strategy tuning.
- 2026-05-31 03:34 UTC | head=081c04b | P2-011C complete; Added raw Coinbase order/status + fills fixture proof and committed required fixtures. Tests passed. Logger hook remains blocked because direct sell proceeds and current exit-leg stable fill-level idempotency are still not proven from the current broker response path. No live behavior/config/risk/runtime/strategy changes.
- 2026-05-31 03:38 UTC | head=0b2a629 | P2-011D-alt complete; Added Coinbase fills payload discovery with fixtures/tests. Finding: no fills/history wrapper exists; historical fills path is required for per-fill fee/liquidity/stable fill IDs, and order/status alone is insufficient. Logger hook remains blocked. No live behavior/config/risk/runtime/strategy changes.
- 2026-05-31 03:44 UTC | head=af1eb87 | P2-011E complete; Added minimal inert BrokerCoinbase.get_historical_fills wrapper proof with tests/docs. Wrapper is not called by live paths. Logger hook remains blocked pending end-to-end order + fills capture/reconciliation for entry and exit legs. No live behavior/config/risk/runtime/strategy changes.

## P2-011F complete — Coinbase Order/Fills Reconciliation Proof

Last updated: 2026-05-31 18:24 UTC

P2-011F functional patch commit: 989292b

P2-011F completed pure Coinbase order-status + historical-fills reconciliation proof.

Added side-effect-free reconcile_order_with_fills() helper.

The helper preserves raw order/fill payloads, direct broker facts, stable per-fill idempotency keys, and blocks logger readiness when fees, stable IDs, or exit proceeds are missing.

The helper is not called by live trading paths.

Logger hook remains blocked.

Next patch after P2-011F was P2-011G narrow inert capture wiring at entry/exit seams, still no writes.

No live behavior, config, risk, runtime, strategy, .env, LaunchAgent, or order-submission changes were made.
- 2026-05-31 04:04 UTC | head=6ccf1fe | P2-011G complete; Added inert Coinbase entry/exit capture wiring proof with helper, tests, and docs. The helper can structure entry/exit reconciliation readiness and missing broker facts, but is not imported by live trading paths and performs no writes. Logger hook remains blocked pending opt-in dry-run proof in actual entry/exit flow and direct broker proof of sell proceeds, stable fill IDs, and fees. No live behavior/config/risk/runtime/strategy changes.
- 2026-05-31 04:21 UTC | head=20ce3df | P2-011H complete; Added opt-in dry-run Coinbase capture seam in actual entry/exit flow plus dedicated tests. The seam is disabled by default, stores in-memory dry-run results only when explicitly enabled, performs no logger writes, and does not call append_coinbase_fill_row. Logger hook remains blocked pending controlled broker-data proof of direct sell proceeds, stable fill IDs, and fees. No default live behavior/config/risk/runtime/strategy/order-submission changes.
- 2026-05-31 13:14 UTC | head=5fb6ffa | P2-011I complete; Added controlled dry-run broker-data capture/probe proof with documentation, script, and tests. The probe uses controlled Coinbase-like broker payloads through the opt-in dry-run seam, remains in-memory/test-only, performs no logger writes, does not call append_coinbase_fill_row, and does not change live behavior/config/risk/runtime/strategy/order-submission behavior. Logger hook remains blocked pending direct broker proof of sell proceeds, stable fill IDs, and fees.
- 2026-05-31 13:26 UTC | head=5b7e73e | P2-011J complete; Added read-only Coinbase broker-fact discovery/probe proof with documentation, script, and tests. The probe remains disabled by default for live calls, redacts sensitive identifiers, performs no writes, does not call append_coinbase_fill_row, and does not add or call order submission/cancel/modify paths. Logger hook remains blocked pending direct broker proof of sell proceeds, stable fill IDs, and per-fill fees.
- 2026-05-31 14:03 UTC | head=0ac6112 | P2-011K complete; Added controlled aggressive live runtime hardening: namespace-aware single-process lock, stale-lock recovery, conservative journal-driven counter reconstruction, honest startup logging, and read-only Coinbase ops status script. Live exploration remains enabled under tiny caps. Logger hook remains blocked; append_coinbase_fill_row is not called. Profit/readout metric must be included in every future status/handoff. Grok usage was around half during this run, so future Grok prompts should be compact and used only when local verification cannot resolve the issue.
- 2026-05-31 14:12 UTC | head=33b3ef1 | P2-011L complete; Fixed Coinbase ops status accuracy. Status now trusts the active lock PID on macOS/launchd, counts actual symbols under state/coinbase/open_positions.json, and calculates local exposure from notional with qty*entry fallback. No strategy/risk/notional/exposure/TP/SL/hold-time/symbol/order/logger changes. Profit/readout remains required in every status update and handoff.
- 2026-05-31 14:24 UTC | head=d8ad784 | P2-012A complete; Added universal Coinbase market universe and prediction telemetry scaffold. Product metadata can be classified conservatively, gold/silver-like products are classification candidates only, all newly discovered products default to live-disabled, and prediction/derivative-style feature helpers are available for future scoring. No strategy/risk/notional/exposure/TP/SL/hold-time/symbol/order/logger changes. Profit/readout remains required in every status update and handoff.
- 2026-05-31 14:56 UTC | head=f3ecb41 | P2-012B complete; Wired prediction telemetry into live scan/proposal/skip flow and added conservative multi-asset spot candidate plumbing/reporting. Telemetry is append-only and non-fatal. No notional/exposure/TP/SL/hold-time/current-symbol/order/leverage/perp/future/gold/silver/logger changes. Profit/readout remains required in every status update and handoff.
- 2026-05-31 15:11 UTC | head=9274b01 | P2-012C complete; Added controlled multi-asset Coinbase spot micro-trading enablement with explicit config gating, micro-size posture, prediction telemetry, max open/new-symbol gates, and deterministic exclusion reasons. Spot-only filter remains enforced. No leverage/perp/future/gold/silver/commodity/fill-logger enablement. Profit/readout remains required in every status update and handoff.
- 2026-05-31 15:22 UTC | head=a54cf52 | P2-012D complete; Turned on controlled multi-asset Coinbase spot micro-trading through explicit config allowlist. Micro-size posture preserved, prediction telemetry active, spot-only filters enforced, no leverage/perp/future/gold/silver/commodity/fill-logger enablement. Profit/readout remains required in every status update and handoff.
- 2026-05-31 15:33 UTC | head=cdc2450 | P2-012E complete; Fixed multi-asset config/status/runtime drift and symbol normalization so expanded allowlisted spot symbols can join live scans. ADA/USD and AVAX/USD are eligible scan expansion symbols when hard filters pass. Prediction telemetry active, P2-012D caps unchanged, no derivative/gold/silver/fill-logger enablement. Profit/readout remains required in every status update and handoff.
- 2026-05-31 15:55 UTC | head=81616ff | P2-013A complete; Added read-only prediction outcome evaluator + trade attribution with crash-proof default price loader, 15/30/60/90m outcome scaffolding, skipped-reason/conversion summaries, and best-effort journal attribution. Required tests and smoke script passed. No strategy/order/risk/symbol/cap/config/runtime changes. No leverage/perps/futures/gold/silver/commodities enabled. Fill logger remains blocked; append_coinbase_fill_row is not called. Profit/readout remains required in every status update and handoff.
- 2026-05-31 18:03 UTC | head=6e3b939 | P2-013B complete; Improved prediction outcome data-quality diagnostics and attribution matching. Script now reports evaluable/unevaluable horizon counts, no_price_data counts, candidate-to-trade conversions, unmatched telemetry candidates, unmatched journal trades, and clearer None-hit-rate explanations. Tests and script smoke passed. No strategy/order/risk/symbol/cap/config/runtime changes. No leverage/perps/futures/gold/silver/commodities enabled. Fill logger remains blocked; append_coinbase_fill_row is not called. Profit/readout remains required in every status update and handoff.
- 2026-05-31 18:30 | equity=$45.73 | positions=1 | regime=downtrend | errors=4 | head=b0bdca6 | SOL/USD open (broker_close_capability_unconfirmed); close failures logged — asset may be held in consumer wallet, position dropped from tracking after 3 retries
- 2026-05-31 18:30 UTC | head=b0bdca6 | P2-014 preflight/live status; Coinbase equity around $45.73, one SOL/USD bot-origin position open/re-associated, broker close capability unconfirmed, close failures logged, and visible recent journal exits remain negative. Preserve risk gates; no sizing/risk increase.
- 2026-05-31 (P2-014A) | head= (to be filled on commit) | P2-014A docs patch complete: ACTIVE_HANDOFF.md cleanly updated on review/p2-014a-... branch to preserve exact live SOL/USD reconciliation blocker status (equity ~$45.73, open/re-associated, unconfirmed close, failures logged, dropped from tracking possible). Added explicit P2-014 preflight section on unsafe-to-aggregate profit readout until direct fill/proceeds/fees reconciliation proven via reuse of existing P2-011F/G modules + tests. No runtime/strategy/risk/config/order/logger changes. git status clean, only doc changed. All invariants preserved.
- 2026-05-31 | head=39a3408 | P2-014D complete; Added read-only Coinbase open/orphan position status report with JSON output. SOL/USD broker-close/orphan blocker remains unresolved from local evidence. Realized P/L remains unsafe-to-aggregate. No runtime/config/order/risk/strategy changes. No fill logger writes. No leverage/margin/futures/perps/options/commodities/GOLD/SILVER/XAU/XAG enabled.
