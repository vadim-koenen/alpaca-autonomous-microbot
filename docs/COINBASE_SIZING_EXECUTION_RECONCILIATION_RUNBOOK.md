# ADVISORY ONLY — read-only analysis, no live trading calls.
# Do not import from: broker, order_manager, risk_manager, main.

# Coinbase Sizing / Execution Reconciliation Runbook — P2-006

## Overview

`scripts/coinbase_sizing_execution_reconciliation_report.py` is a **Class 1 advisory** tool that explains:

- Why live Coinbase transactions can look like they “cancel out” (buy then sell the same qty).
- Why entries appear fixed at **$0.50** (legacy probe) or **$1.00** (controlled exploration cap).
- How **P2-004 dynamic sizing** relates to config vs what the journal actually applied.
- Per-cycle filled buy/sell notionals, fees, net P/L, exit reason, and optional P2-003 MFE.

## Run

From repo root:

```bash
python3 scripts/coinbase_sizing_execution_reconciliation_report.py
```

Optional journal path override:

```bash
python3 scripts/coinbase_sizing_execution_reconciliation_report.py /path/to/journal_coinbase_crypto.csv
```

Stdout only. Redirect if needed:

```bash
python3 scripts/coinbase_sizing_execution_reconciliation_report.py > logs/sizing_reconciliation.txt
```

## Data sources (local, no API keys)

| Source | Purpose |
|--------|---------|
| `config_coinbase_crypto.yaml` | Probe notional, exploration cap, dynamic sizing flags |
| `journal_coinbase_crypto.csv` (or fallbacks) | BUY/EXIT pairing, notionals, P/L |
| `logs/coinbase_price_path.csv` | Optional intra-hold MFE vs break-even |

Does **not** read `.env` or call broker APIs.

## Interpretation

- **$1.00 entries:** `controlled_exploration.max_single_trade_notional_usd` wins over dynamic scaling at current equity.
- **$0.50 entries:** legacy `coinbase_probe_notional_usd` path (or historical probe rows).
- **Buy/sell similarity:** exit sells the opened quantity; notional differs only by price × qty.
- **Negative net with tiny gross:** fees (~$0.012/round trip at $1 notional) dominate small moves.
- **Class 2:** remain blocked until P2-005 shows enough price-path evidence (≥20 paths, ~2+ weeks).

## Tests

```bash
python3 -m py_compile scripts/coinbase_sizing_execution_reconciliation_report.py
python3 -m pytest tests/test_coinbase_sizing_execution_reconciliation_report.py -q
```

## Safety

- Read-only; no config/state/runtime/launchd changes.
- No order placement or cap changes.

---
**Last updated:** 2026-05-30  
**Status:** REVIEW — `review/p2-006-coinbase-sizing-execution-reconciliation`
