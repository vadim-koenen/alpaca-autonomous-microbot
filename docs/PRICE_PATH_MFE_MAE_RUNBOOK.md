# ADVISORY ONLY — read-only analysis, no live trading calls.
# Do not import from: broker, order_manager, risk_manager, main.

# Coinbase Price-Path MFE/MAE Analyzer Runbook — P2-005

## Overview

`scripts/coinbase_price_path_mfe_mae_report.py` is a **Class 1 advisory** tool. It reads `logs/coinbase_price_path.csv` (written by the P2-003 logger) and prints Maximum Favorable Excursion (MFE), Maximum Adverse Excursion (MAE), threshold-crossing timing, fallback behavior, and a conservative verdict on whether Class 2 SL/TP/hold-time tuning is supported.

It does **not** place orders, change config, or import core trading modules.

## Prerequisites

- P2-003 logger running (or manual snapshots) so `logs/coinbase_price_path.csv` accumulates rows while `coinbase_exploration` positions are open.
- Each row must include `position_id`, `symbol`, and `entry_timestamp` for grouping.

## Run the report

From the repo root:

```bash
python3 scripts/coinbase_price_path_mfe_mae_report.py
```

Optional custom CSV path:

```bash
python3 scripts/coinbase_price_path_mfe_mae_report.py /path/to/coinbase_price_path.csv
```

Output goes to **stdout only** (redirect to a file if needed):

```bash
python3 scripts/coinbase_price_path_mfe_mae_report.py > logs/mfe_mae_report.txt
```

## What the report includes

1. **Per-position** — sample count, first/last snapshot, entry/latest prices, MFE/MAE, hold minutes, threshold crossings (+0.60% … +2.40%), fallback after +1.20% / +1.50%.
2. **By-symbol** — positions observed, total samples, average/max MFE, average/min MAE, % crossing +1.20% and +2.40%.
3. **Advisory verdict** — data sufficiency, maker break-even reach, fallback patterns, Class 2 tuning guidance.

## Conservative gates (built into verdict)

| Gate | Rule |
|------|------|
| Position paths | Fewer than **20** distinct paths → sample too small |
| Calendar span | Fewer than **14 days** of snapshot span → Class 2 tuning premature (~2–3 weeks recommended) |
| Class 2 changes | Remain **blocked** until gates pass and a human approves a separate Class 2 patch |

## Optional context

If `journal_coinbase_crypto.csv` exists, the report notes it but **does not** join or match journal rows (avoids uncertain position matching).

## Tests

```bash
python3 -m py_compile scripts/coinbase_price_path_mfe_mae_report.py
python3 -m pytest tests/test_coinbase_price_path_mfe_mae_report.py -q
```

## Safety

- Read-only: no writes to `state/`, `runtime/`, or config.
- No `launchctl`, bot restarts, or broker API trading calls.
- Does not raise trade size, exposure, SL, TP, or hold time.

## Related

- P2-003 logger: `docs/PRICE_PATH_LOGGER_RUNBOOK.md`
- P2-004 sizing (merged): hard exploration cap remains $1.00 until a separate Class 2 approval.

---
**Last updated:** 2026-05-30  
**Status:** REVIEW — `review/p2-005-price-path-mfe-mae-analyzer`
