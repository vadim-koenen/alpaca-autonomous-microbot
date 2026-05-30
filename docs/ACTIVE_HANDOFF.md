# ACTIVE HANDOFF — Alpaca/Coinbase Autonomous Trading Bot
<!-- This file is the shared context layer between Claude (advisor) and ChatGPT/Copilot (executor). -->
<!-- Update this file after every session. Both AIs read from here. Do not let it go stale. -->

**Last updated:** 2026-05-30 04:12 UTC — P2-001H committed; Re-baselines Coinbase exploration using live-only BTC/ETH/SOL data excluding dry_run, ALGO, probe, and recovered noise
**Updated by:** Claude  
**Repo:** https://github.com/vadim-koenen/alpaca-autonomous-microbot.git  
**Branch:** main

---

## 1. Project Identity

This is a live autonomous trading bot running on a Mac under launchd.  
- **Coinbase bot** — primary live trading, crypto spot, $1.00 controlled exploration  
- **Alpaca bot** — secondary, equity/crypto scanning, currently inactive due to after-hours stale quotes  

The project has moved past execution plumbing. Current focus is measurement, fee analysis, and entry/exit quality improvement.

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
| Coinbase equity | ~$40.94 |
| Coinbase status | RUNNING_BY_LAUNCHD (PID 44548, uptime ~11h) |
| Alpaca equity | $10.00 |
| Alpaca status | RUNNING_BY_LAUNCHD (PID 40509, outside market hours) |
| Kill switch | INACTIVE (trading allowed) |
| Open positions | 0 |
| Last Coinbase trade | 2026-05-29T17:15:37 UTC |
| Last Coinbase exit | 2026-05-29T18:46:11 UTC |
| Current regime | dead_chop (bot correctly sitting out) |

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

---

## 6. Git State (as of last update)

```
Latest functional patch commit: 9ac606a
Latest handoff commit: 466685f
Clean: no dirty tracked files (except handoff update)

Recent commits:
  9ac606a P2-001H: Coinbase live-only performance re-baseline
```

P2-002 files are advisory-only. Safe to commit after review of `prediction_features.py` for future-data leakage. Not urgent.

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
**None — awaiting Claude review / explicit approval before Class 2 live tuning**

### QUEUED (do not start until P2-001E is complete)
- **P2-002 commit** — review prediction_features.py for future-data leakage first
- **SL/TP/hold-time tuning** — Class 2, needs P2-001E report to justify changes
- **P2-003** — Entry quality gate (Class 2, requires P2-001E first)

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
