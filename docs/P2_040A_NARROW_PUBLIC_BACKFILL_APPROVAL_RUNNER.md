# P2-040A Narrow Public Backfill Approval Runner

## Purpose

Adds a governed approval-runner layer around the P2-039D public OHLCV backfill adapter. Makes accidental real public fetches impossible by requiring both an explicit fetch flag **and** a mandatory approval token.

## Why This Exists After P2-039D

P2-039D established the dry-run-by-default public adapter with `--allow-public-fetch`. P2-040A adds a second gate: `--approval-token PUBLIC_BACKFILL_APPROVED`. This double-gate pattern ensures that:

1. No script or automation can accidentally trigger real network fetches.
2. Every approved fetch is auditable via the JSON report output.
3. The approval token can be changed or rotated if needed.

## Dry-Run Default

The runner defaults to plan-only mode. It reports what *would* be fetched without making any network calls or writing any data.

## Required Approval Flow

To execute a real public fetch (future, not yet implemented):

```bash
python3 scripts/p2_040a_public_backfill_approval_runner.py \
  --provider coinbase_public \
  --symbol BTC/USD \
  --timeframe 1m \
  --start 2026-01-01T00:00:00Z \
  --end 2026-01-01T01:00:00Z \
  --allow-public-fetch \
  --approval-token PUBLIC_BACKFILL_APPROVED \
  --report-json /tmp/backfill_report.json
```

Both `--allow-public-fetch` and `--approval-token PUBLIC_BACKFILL_APPROVED` are required. Missing either gate blocks execution and returns nonzero exit code.

## Authentication Constraints

- **NO** authenticated broker APIs.
- **NO** account data access.
- **NO** order submission, cancellation, or closing.
- **NO** `.env` secrets read or required.

## Generated Data Policy

- No generated Parquet, DuckDB, manifests, reports, or caches are committed.
- Test-generated data lives only in pytest `tmp_path` directories.

## Future Real Fetch

Real public fetch requires separate explicit user approval in a future patch. The current P2-039D adapter raises `NotImplementedError` for non-mock providers.

## ML Status

ML remains blocked. Predictions are conditional only — replay-trained, advisory-first, fee-hurdle veto/gating. No live strategy influence until replay-grade historical coverage exists.

## Current Economic Baseline

- 80 trades, gross PnL ≈ -$0.14, fees ≈ $1.44, net ≈ -$1.58
- 77 timeouts, 3 stop-losses, 0 take-profits, only 2/80 net winners
