# OHLCV_LOCAL_IMPORT (P2-025H)

## Why this exists
P2-025G added the local OHLCV loader and coverage reporting in the journal-window replay. Real journal still reports 0 coverage because no local OHLCV files exist for the required symbols (ALGO/USD, BTC/USD, ETH/USD, SOL/USD) and window (~2026-05-25 through 2026-06-03).

This tool provides a safe, offline-first way to import/validate local OHLCV files (CSV or JSON) and optionally export normalized CSVs to the conventional location `data/offline_ohlcv/coinbase/`.

## Safe design
- Default: **dry-run** (validation + report only; no writes).
- Explicit `--write` required to persist normalized output.
- No network fetch by default.
- No authentication, no API keys, no .env reads, no broker/trading endpoints.
- Pure offline validation + normalized CSV export for use by the replay harness.

## Usage
```bash
# Validate only (dry-run)
python3 scripts/coinbase_ohlcv_import_validate.py --json --input my_data.csv --symbol BTC/USD

# Validate + write normalized CSV (explicit)
python3 scripts/coinbase_ohlcv_import_validate.py --json --input my_data.json --symbol ETH-USD --write --output-dir data/offline_ohlcv/coinbase

# With journal for coverage hint in report
python3 scripts/coinbase_ohlcv_import_validate.py --json --input data.csv --symbol SOL/USD --journal journal_coinbase_crypto.csv
```

## File format expectations
Input (CSV or JSON array of objects):
- timestamp (or t, timestamp_utc, time)
- open (or o)
- high (or h)
- low (or l)
- close (or c)
- volume (or v) optional
- symbol optional (will be overridden by --symbol)

Normalized output CSV (written on --write):
timestamp_utc,symbol,open,high,low,close,volume

Naming convention for auto-discovery by replay report:
BTC-USD_5m_2026-05-25_2026-06-03.csv
(granularity and date range in name; tool uses --granularity for name)

## Where to put files
Place (or let the tool write) under:
data/offline_ohlcv/coinbase/

The journal-window replay report will auto-scan this directory for matching symbol files when no --ohlcv-fixture is passed, and report coverage.

## After placing data
Re-run:
python3 scripts/coinbase_journal_window_replay_report.py --json

Expect higher `cycles_with_ohlcv_window`, `coverage_rate`, and `cycles_replayed > 0` for covered windows.

## Safety
- trade_permission=none
- risk_increase=not_approved
- scaling_allowed=false
- No live trading, no orders, no config/risk changes, no restart.

Real market data files should not be committed to the repo unless they are tiny test fixtures and explicitly approved.

## Limitations
- This tool does not fetch data from exchanges (opt-in public fetcher would be future P2-025I if needed).
- Gap detection is heuristic (assumes ~5m bars).
- Coverage check is best-effort using journal entry/exit windows.
