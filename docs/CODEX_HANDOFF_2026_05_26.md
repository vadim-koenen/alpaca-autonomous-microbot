# Codex Handoff — 2026-05-26

> **Purpose:** Bring a fresh Codex (or Claude) session up to speed on the current
> state of this bot after the Claude session that ran through 2026-05-26 UTC
> exhausted its context window.  Read this before proposing any new patches.

---

## 1. Project overview

Two autonomous trading bots sharing a codebase:

| Bot label | Broker | Config file | launchd label |
|---|---|---|---|
| Alpaca stocks | Alpaca | `config_alpaca_stocks.yaml` | `com.vadim.alpaca-stocks-bot` |
| Coinbase crypto | Coinbase Advanced Trade | `config_coinbase_crypto.yaml` | `com.vadim.coinbase-crypto-bot` |

Both bots run via `launchd` on macOS, managed by `scripts/start_all.sh` and
`scripts/stop_all.sh`.  Logs live in `logs/`.  Heartbeat files are written to
`logs/heartbeat_*.txt`.

---

## 2. Account state at handoff (2026-05-26 ~19:00 UTC)

| Metric | Alpaca | Coinbase |
|---|---|---|
| Equity | $10.00 | $9.95 |
| Buying power | $10.00 | $9.95 |
| Open positions | 0 | 0 |
| `entry_allowed` | ✅ YES | ✅ YES (headroom $4.00) |
| Last known mode | live | live |

The Coinbase bot had been blocked by a "broker_recovered" ETH position from a
consumer wallet.  That was resolved this session: the user sold the ETH from
coinbase.com, `state/coinbase/open_positions.json` was cleared, and both bots
were restarted.  The ETH record is archived in
`state/coinbase/closed_positions.json` under key
`ETH/USD_broker_recovered_20260526`.

---

## 3. Test suite

**158 tests, all passing.**

Run with:
```bash
cd /Users/vadimkoenen/Documents/Claude/Projects/Investing/alpaca-autonomous-microbot
source .venv/bin/activate
python3 -m pytest tests/ -q
```

Test files:
- `tests/test_config.py`
- `tests/test_daily_distill_and_auth.py`
- `tests/test_duplicate_order_guard.py`
- `tests/test_event_store_memory.py`
- `tests/test_event_store_self_improvement.py`  ← added this session (20 tests)
- `tests/test_new_features.py`
- `tests/test_permissions.py`
- `tests/test_risk_manager.py`
- `tests/test_safety_state_plumbing.py`
- `tests/test_self_update_scaffold.py`

**Never submit a patch that drops the test count or leaves any test failing.**

---

## 4. Patches completed this session (Tasks 43–55)

| Task | Description | Risk class | Files changed |
|---|---|---|---|
| 43 | Skip exit evaluation for `broker_recovered` positions | 2 | `position_manager.py` |
| 44 | Daily reset for `consecutive_losses` counter at UTC midnight | 1 | `main.py` |
| 45 | Compile check + full test suite after Tasks 43–44 | 0 | — |
| 46 | Print effective risk config at every bot startup (`RISK_CONFIG` log) | 1 | `main.py` |
| 47 | Improve exposure guard log: name both caps, classify external/untradeable | 1 | `risk_manager.py` |
| 48 | Add `api_controllable` and `exit_evaluation_enabled` fields to broker_recovered state | 1 | `position_manager.py` |
| 49 | Add `scripts/reconcile.sh` — one-command broker reconciliation report | 1 | `scripts/reconcile.sh` |
| 51 | Compile check + full test suite after Tasks 46–50 | 0 | — |
| 52 | Post-restart verification assessment | 0 | — |
| 53 | Guide ETH consumer-wallet resolution (operational, no code) | 0 | — |
| 54 | Implement EventStore helper methods for self-improvement scaffold | 1 | `memory/event_store.py`, `tests/test_event_store_self_improvement.py` |
| 55 | Clear ETH from state files and restart bots | 0 | `state/coinbase/open_positions.json`, `state/coinbase/closed_positions.json` |

**Note on Task 50** (idempotent client order IDs): `build_client_order_id` is
already implemented in `utils.py` and wired into `broker_coinbase.py` and
`order_manager.py`.  The deferred part (pre-checking for an existing live order
with the same client_order_id before placing a new one — §10A of the feedback
doc) is **not yet implemented**.  It would be a Class 2 patch requiring human
approval.

---

## 5. Key architecture notes

### Exposure caps — two separate guards
1. `crypto.max_total_crypto_exposure_usd: $4.00` — asset-class guard (Coinbase
   config only).
2. `global_risk.max_total_live_exposure_usd: $6.00` — cross-asset guard (both
   configs).
Both are intentional and both appear in the `RISK_CONFIG` startup log.

### `RISK_CONFIG` log format
The startup log entry is **multi-line**.  To read the full output:
```bash
grep -A 10 "RISK_CONFIG effective" logs/coinbase_crypto.log | tail -15
```
`grep "RISK_CONFIG effective" | tail -1` captures only the header line — do not
use `tail -1` here.

### broker_recovered positions
When the bot loads a position whose order_id is blank or broker-unverifiable, it
marks it `broker_recovered` with:
- `api_controllable: false`
- `exit_evaluation_enabled: false`
- `counts_toward_exposure: true`

The 90-min exit timer is intentionally bypassed for these positions — see
`_evaluate_position()` in `position_manager.py`.  To clear a stale
broker_recovered entry safely, you must:
1. `bash scripts/stop_all.sh`
2. Edit `state/<broker>/open_positions.json` — remove the key.
3. Append an archive entry to `state/<broker>/closed_positions.json`.
4. `bash scripts/start_all.sh` (after Vadim approves).

A helper script `scripts/clear_recovered_position.sh` was discussed but **not
yet created** — it would be a good Class 1 candidate.

### Self-improvement scaffold (EventStore helpers)
`memory/event_store.py` now has 7 advisory-only methods:
- `record_patch_proposal()`
- `update_patch_proposal_status()`
- `record_approval_decision()`
- `record_paper_validation()`
- `record_experiment()`
- `record_deployment()`
- `record_rollback()`

All are advisory only.  `auto_deploy_enabled=False` is hardcoded in
`self_update/change_classifier.py`.  None of these methods deploy code, restart
bots, or place orders.

### Change-risk classifier
Located at `self_update/change_classifier.py`:
- Class 0: docs, comments, tests, read-only diagnostics → auto-proposable
- Class 1: logging, reconciliation, memory writes, heartbeat → auto-proposable
- Class 2: risk_manager, order_manager, position_manager, broker adapters → **requires human approval**
- Class 3: strategy expansion, new symbols, larger sizing, higher exposure, margin, shorting, options → **requires human approval + separate risk review**

See `docs/SELF_UPDATE_POLICY.md` for the full policy.

---

## 6. Hard constraints — must never be violated

- `LIVE_TRADING=true` is required for any live order.  Default is paper/dry_run.
- API keys live in `.env` only.  Never print, log, or commit them.
- The risk manager is mandatory and cannot be bypassed by any patch.
- No Docker.  No Chrome automation.  No browser automation.
- Never run bots with `sudo`.
- Never `launchctl start/stop/load/unload` without explicit Vadim approval.
- Never `python3 main.py --mode live` without explicit Vadim approval.
- Never edit `.env` or print secrets.
- Class 2+ patches require Vadim's explicit written approval before deployment.
- Class 3 patches require Vadim's approval + a separate risk review pass.
- Do not automatically restart bots after patching.
- Do not increase any risk limit, notional cap, or exposure cap without Vadim's
  explicit instruction.
- Do not place, cancel, or simulate live orders.

---

## 7. Suggested next patches (safe candidates)

The following are scoped, low-risk improvements in priority order.  All require
passing `python3 -m pytest tests/ -q` with 158+ tests before marking complete.

### 7a. `scripts/clear_recovered_position.sh` — Class 1

A utility script for safely removing stale `broker_recovered` entries from
state files.  Should:
1. Require bot to be stopped first (check PID file or error).
2. Accept `--broker <coinbase|alpaca>` and `--key <position_key>` arguments.
3. Read `state/<broker>/open_positions.json`, remove the key, write it back.
4. Append the removed entry to `state/<broker>/closed_positions.json` with a
   `cleared_at` timestamp and `cleared_reason` from the CLI argument.
5. Print a summary and remind the user to restart the bot manually.
6. Never restart the bot automatically.

No new tests required (it's a shell script), but document it in `docs/OPERATIONS.md`.

### 7b. Improve `scripts/status.sh` — Class 1

Currently shows equity, buying_power, positions, and heartbeat age.  Additions
that would be useful:
- Show `daily_trade_count` and `consecutive_losses` from the session state
  (readable from the log or a state file if one is added).
- Show `last_trade_at` and `last_exit_at` timestamps.
- Show bot uptime (time since PID was created).

### 7c. Add `scripts/daily_distill.py` auto-scheduling note to OPERATIONS.md — Class 0

The daily distillation script (`scripts/daily_distill.py`) exists but there is
no launchd plist for it.  Add a note to `docs/OPERATIONS.md` explaining how to
run it manually and that a future plist could automate it.  Docs-only change.

### 7d. Add `--dry-run` flag to `scripts/reconcile.sh` — Class 1

Currently `reconcile.sh` always calls the Coinbase and Alpaca APIs.  Add a
`--dry-run` flag that prints what it _would_ do without making API calls (useful
for CI).  This is purely a shell change with no impact on trading logic.

### 7e. Structured journal summary in `scripts/daily_distill.py` — Class 0/1

`journal_coinbase_crypto.csv` and `journal_alpaca_stocks.csv` accumulate trade
records.  `daily_distill.py` currently produces a text summary.  Consider
adding a `--json` flag that outputs a machine-readable summary of:
- Total trades, wins, losses, win_rate
- Net P&L after fees
- Best and worst trade of the day
This would be read by the capital growth plan gating logic (Phase 1 → Phase 2
trigger at $50 equity).

---

## 8. Capital growth plan (Phase 1 active)

Vadim's plan: grow from $10 → $50 (Phase 1) before considering any additional
capital deposit.  The Phase 1 trigger for Codex to note is:
- **Do not increase risk limits** even if equity grows during Phase 1.
- Current limits: max_trade_notional $2.00 (Coinbase), max_total_crypto_exposure
  $4.00, max_daily_loss $2.00.
- If equity reaches $20.00, keep the same limits — Vadim must explicitly update
  config to change sizing.

---

## 9. File map (key files)

```
alpaca-autonomous-microbot/
├── main.py                          # Bot entry point, heartbeat, daily reset
├── broker_coinbase.py               # Coinbase Advanced Trade adapter
├── broker_alpaca.py                 # Alpaca stocks/crypto adapter
├── risk_manager.py                  # Central risk gate — mandatory, not bypassable
├── order_manager.py                 # Order lifecycle, duplicate guard, client_order_id
├── position_manager.py              # Position state, reconcile loop, broker_recovered
├── market_data.py                   # Bar fetching, spread checks
├── strategy_crypto.py               # Crypto momentum/mean-reversion/breakout
├── permissions.py                   # Account eligibility checks
├── journal.py                       # Trade journal writes
├── utils.py                         # build_client_order_id, get_cfg, utc_now
├── memory/
│   ├── event_store.py               # SQLite audit log + self-improvement helpers
│   └── schema.sql                   # DB schema (includes self-improvement tables)
├── self_update/
│   └── change_classifier.py         # Change risk classifier (advisory only)
├── config_coinbase_crypto.yaml      # Coinbase bot config
├── config_alpaca_stocks.yaml        # Alpaca bot config
├── state/
│   ├── coinbase/open_positions.json
│   ├── coinbase/closed_positions.json
│   ├── alpaca/open_positions.json
│   └── alpaca/closed_positions.json
├── scripts/
│   ├── status.sh                    # Quick bot status check
│   ├── reconcile.sh                 # Broker reconciliation report
│   ├── start_all.sh / stop_all.sh
│   └── daily_distill.py
├── docs/
│   ├── OPERATIONS.md
│   ├── RISK_POLICY.md
│   ├── SELF_UPDATE_POLICY.md
│   └── MEMORY_POLICY.md
└── tests/                           # 158 tests — must all pass before any deploy
```

---

## 10. How to hand back to Vadim

After completing any patch:
1. Run `python3 -m pytest tests/ -q` — confirm ≥158 passing, 0 failing.
2. Run a compile check: `python3 -m py_compile <changed files>`.
3. Do **not** restart the bots.
4. Summarize what was changed, what risk class it is, and ask Vadim for
   approval to deploy (for Class 1+).

For Class 2 or 3 changes: present a full diff summary, the rollback plan, and
wait for explicit written approval before doing anything else.
