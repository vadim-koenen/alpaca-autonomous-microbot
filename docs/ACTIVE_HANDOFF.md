# ACTIVE HANDOFF — Alpaca/Coinbase Autonomous Trading Bot
<!-- This file is the shared context layer between Claude (advisor) and ChatGPT/Copilot (executor). -->
<!-- Update this file after every session. Both AIs read from here. Do not let it go stale. -->

**Last updated:** 2026-05-30 19:45 UTC — P2-009 committed; Adds advisory-only open-source bot plumbing survey, read-only reference checker, and tests. The survey captures Freqtrade, Hummingbot, Jesse, OctoBot, and CCXT as architecture references only, with no copied code, installs, live behavior changes, or strategy tuning.
**Updated by:** Claude  
**Repo:** https://github.com/vadim-koenen/alpaca-autonomous-microbot.git  
**Branch:** main

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
| Coinbase equity | $40.94 |
| Coinbase status | RUNNING_BY_LAUNCHD |
| Alpaca equity | $10.00 |
| Alpaca status | RUNNING_BY_LAUNCHD (outside market hours) |
| Kill switch | INACTIVE (trading allowed) |
| Open positions | 0 |
| Last Coinbase trade | 2026-05-25T12:06:37 UTC (journal; all SKIPPED — max trades/day) |
| Last Coinbase exit | 2026-05-25T12:06:37 UTC |
| Current regime | dead_chop (BTC/ETH/SOL — bot correctly sitting out) |

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

---

## 6. Git State (as of last update)

```
Latest functional patch commit: 1b49c11
Commit hashes for handoff updates should be verified with `git log`; this file intentionally avoids storing a self-referential handoff commit hash.
Clean: no dirty tracked files (except handoff update)

Recent commits:
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
**P2-009 integrates public trading-bot plumbing ideas as architecture references only. Freqtrade, Hummingbot, Jesse, OctoBot, and CCXT are reference patterns, not dependencies or copied strategy code. Current blocker remains measurement truth: `logs/coinbase_fills.csv` is missing, realized gross/net P/L must remain `n/a`, and Class 2 tuning remains blocked. Next safe patch should be P2-010: read-only Coinbase fill logging implementation discovery to map order submission, response parsing, journal writing, and available fill/proceeds/fee fields before any execution-path implementation is attempted.**

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
