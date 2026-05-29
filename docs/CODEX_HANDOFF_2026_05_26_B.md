# Codex Handoff — 2026-05-26 (Session B)

> **Prepared by:** Claude (Cowork session — usage limit reached)
> **Continues from:** `docs/CODEX_HANDOFF_2026_05_26.md` (Session A)
> **Repo:** `/Users/vadimkoenen/Documents/Claude/Projects/Investing/alpaca-autonomous-microbot`

---

## 1. Current State at Handoff

| Metric | Alpaca | Coinbase |
|---|---|---|
| Equity | $10.00 | ~$29.93 (Vadim deposited $20) |
| Open positions | 0 | 1 — BTC/USD coinbase_probe, $0.50 notional |
| `entry_allowed` | ✅ YES | ✅ YES (headroom $3.50) |
| Mode | live | live |
| Both bots running | ✅ launchd PIDs 54351 / 54353 | |

**BTC/USD position (current, fully controllable):**
- `order_status: filled` | `api_controllable: True` | `bot_opened: True`
- `order_id: 8d552559-51d2-4435-845a-48b79c6f3371`
- `client_order_id: cb-coinbase_probe-BTCUSD-buy-20260526T233034Z-entry-b831`
- `stop_loss: 74672.84` | `take_profit: 78273.82` | 90-min max-hold active
- Journal evidence confirmed. Close capability: ✅ YES.

The $20 deposit is operating buffer only. **Do not increase any risk limit.**

---

## 2. Test Suite

**218 tests passing.** (was 158 in Session A → 218 after Session B additions)

```bash
cd /Users/vadimkoenen/Documents/Claude/Projects/Investing/alpaca-autonomous-microbot
source .venv/bin/activate
python3 -m pytest tests/ -q
```

Never submit a patch that drops the count or leaves any failing.

---

## 3. What Was Done This Session (after Session A handoff)

| Task | Description | Risk class | Files |
|---|---|---|---|
| 57 | `scripts/coinbase_position_capability_diagnose.py` — read-only diagnostic for broker_recovered positions | 1 | `scripts/coinbase_position_capability_diagnose.py`, `tests/test_coinbase_capability_diagnose.py` (11 tests), `scripts/status.sh`, `docs/OPERATIONS.md` |
| 58 | `status.sh` improvements: consecutive_losses, risk_halt_active/halt_reason, bot uptime via `ps`, last_entry/last_exit from journal CSVs | 1 | `scripts/status.sh` |
| 59 | `--dry-run` flag for `reconcile.sh` | 1 | `scripts/reconcile.sh` |
| 60 | `--json` / `--no-files` flags for `daily_distill.py` + `_journal_metrics()` function (entries_placed, wins, losses, win_rate, net_pnl, best/worst trade, capital growth plan fields) | 0/1 | `scripts/daily_distill.py` |

---

## 4. Diagnostic Script Usage

```bash
# Local state only (no broker API):
python3 scripts/coinbase_position_capability_diagnose.py --no-broker

# With broker (requires LIVE_TRADING=true in .env):
python3 scripts/coinbase_position_capability_diagnose.py

# JSON output:
python3 scripts/coinbase_position_capability_diagnose.py --no-broker --json
```

Output when BTC/USD is normally bot-placed and controllable:
```
✅ VERDICT: All tracked positions are bot-managed and closeable via Advanced Trade API.
```

Output when a broker_recovered position exists (consumer wallet):
```
⚠️  VERDICT: 1 position(s) require manual review
  coinbase_close_capability = unknown
  recommended_diagnostic = python3 scripts/coinbase_position_capability_diagnose.py
```

---

## 5. Daily Distill — Compact JSON

```bash
# Print compact trade metrics to stdout (for capital growth gating):
python3 scripts/daily_distill.py --date 2026-05-26 --json --no-files

# Write full distillation files AND print metrics:
python3 scripts/daily_distill.py --date 2026-05-26 --json
```

Key fields emitted: `entries_placed`, `exits_completed`, `wins`, `losses`, `win_rate`,
`gross_pnl`, `fees_paid`, `net_pnl`, `best_trade`, `worst_trade`,
`coinbase_equity`, `alpaca_equity`, `phase1_target_equity`.

---

## 6. Hard Constraints (unchanged, must never be violated)

- `LIVE_TRADING=true` required for any live order.
- API keys in `.env` only. Never print, log, or commit them.
- Risk manager mandatory, cannot be bypassed.
- No Docker. No browser automation. No `sudo`.
- Never `launchctl start/stop/load/unload` without explicit Vadim approval.
- Never `python3 main.py --mode live` without explicit Vadim approval.
- Class 2+ patches require Vadim's written approval before deployment.
- Class 3 patches require approval + separate risk review.
- Do not restart bots automatically after patching.
- Do not increase any risk limit, notional cap, or exposure cap.
- The $20 deposit is buffer only — do not resize trades.
- Do not tune Alpaca until a full market session with valid quotes is observed.

---

## 7. Suggested Next Patches (safe, Class 0–1)

### 7a. Add `daily_distill.py` to launchd — Class 1

Create `launchd/com.vadim.daily-distill.plist` to run
`python3 scripts/daily_distill.py` automatically at 23:55 UTC each day.
Model after the existing bot plists in `launchd/`. Add a note to `docs/OPERATIONS.md`.

### 7b. Add `--since` flag to `alpaca_no_trade_diagnose.py` — Class 0/1

Currently the script has `--hours` (default 24). A `--since YYYY-MM-DD` flag
would let you diagnose a specific calendar day. Useful for post-market review.
Log parsing is already in `_safe_lines()` / `_parse_ts()`.

### 7c. Add `OPERATIONS.md` note about `daily_distill.py --json` — Class 0

One-paragraph docs addition explaining the `--json` output and how it feeds
capital growth plan gating. Zero risk.

### 7d. Persist `last_trade_at` / `last_exit_at` in heartbeat — Class 1

`main.py` writes the heartbeat dict. Add two fields: `last_trade_at` and
`last_exit_at` (ISO-8601 UTC strings, updated on each entry/exit in
`order_manager.py` or `position_manager.py`). This lets `status.sh` read them
directly from heartbeat instead of scanning the journal CSV on every status call.

**Files to change:** `main.py` (heartbeat writer), `order_manager.py` or
`position_manager.py` (set the fields on SessionState).
**Risk class:** 1 — logging only, no impact on trading logic.
**Requires restart:** yes (to pick up the new heartbeat fields).
**Requires Vadim approval:** yes (restart).

### 7e. Idempotent client order ID pre-check (§10A) — Class 2

Before placing a new entry order, check whether an order with the same
`client_order_id` already exists at the broker (call `get_order_status()` with
the prospective ID). If it's already open or filled, adopt the existing order
rather than placing a duplicate. This is the deferred §10A item.

**Risk class: 2** — requires Vadim approval before deployment.
**Files:** `order_manager.py`, `broker_coinbase.py`.

---

## 8. File Map (additions since Session A)

```
scripts/
├── coinbase_position_capability_diagnose.py  ← NEW (Task 57)
├── status.sh                                  ← UPDATED (Task 58)
├── reconcile.sh                               ← UPDATED (Task 59, --dry-run)
└── daily_distill.py                           ← UPDATED (Task 60, --json)
tests/
└── test_coinbase_capability_diagnose.py       ← NEW (Task 57, 11 tests)
docs/
├── OPERATIONS.md                              ← UPDATED (clearing recovered pos section)
├── CODEX_HANDOFF_2026_05_26.md               ← Session A handoff
└── CODEX_HANDOFF_2026_05_26_B.md             ← THIS FILE
```

---

## 9. How to Hand Back to Vadim

After completing any patch:
1. `python3 -m pytest tests/ -q` — confirm ≥218 passing, 0 failing.
2. `python3 -m py_compile <changed files>` — compile check.
3. `bash -n <changed shell scripts>` — syntax check.
4. Do **not** restart the bots.
5. For Class 1: summarise changes and ask Vadim for deployment approval.
6. For Class 2+: present full diff summary, rollback plan, and wait for
   explicit written approval before anything else.
