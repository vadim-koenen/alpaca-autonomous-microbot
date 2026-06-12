# P2-040E First Narrow Public Backfill Preflight

This document serves as the final no-fetch preflight validation before authorizing the first real public OHLCV backfill execution.

## State Verification
* **Current Main Commit:** 11f8ae6cfffbc2bf4db15d7edb2aadf18ab867b1

## Candidate Under Review
* **Provider:** `coinbase_public`
* **Symbol:** `BTC/USD`
* **Timeframe:** `1m`
* **Range:** 1 day preferred, 7 days maximum

## Confirmations
* `PUBLIC_FETCH_PERFORMED=false`
* `APPROVAL_TOKEN_USED=false`
* `REAL_FETCH_APPROVED=false`

## Future Command
> [!WARNING]
> **NOT EXECUTED IN P2-040E**
> **INFORMATIONAL ONLY**
> **REQUIRES SEPARATE USER APPROVAL**

```bash
python3 scripts/p2_040a_public_backfill_approval_runner.py \
  --provider coinbase_public \
  --symbol BTC/USD \
  --timeframe 1m \
  --start 2026-06-04T23:00:00Z \
  --end 2026-06-11T23:00:00Z \
  --output-root /tmp/p2_040e_market_data \
  --allow-public-fetch \
  --approval-token PUBLIC_BACKFILL_APPROVED
```

## Approval Phrase Placeholder
For the next step, execution requires the exact approval phrase:
`PUBLIC_BACKFILL_APPROVED for coinbase_public BTC/USD 1m 2026-06-04T23:00:00Z to 2026-06-11T23:00:00Z output_root=/tmp/p2_040e_market_data`

## Output Path Policy
* Generated OHLCV, Parquet, DuckDB, cache, reports, manifests, and runtime artifacts must remain uncommitted.
* Only docs/tests/source changes may be committed.

## Pre-fetch Checklist
- [ ] Working tree clean
- [ ] Current branch known
- [ ] Main commit known
- [ ] Command reviewed
- [ ] Range is narrow
- [ ] Output path ignored or `/tmp`
- [ ] Approval token present only for real fetch
- [ ] Artifact scan ready
- [ ] Rollback cleanup command documented (`rm -rf /tmp/p2_040e_market_data`)

## Post-fetch Checklist (for future patch)
- [ ] Manifest exists
- [ ] Candle count plausible
- [ ] Timestamps UTC aligned
- [ ] No duplicate candles
- [ ] No partial/latest candle contamination
- [ ] No schema drift
- [ ] No committed generated data
- [ ] Replay-grade coverage not yet assumed until validated

## Stop Conditions
Abort immediately if any of the following occur:
- Wrong provider
- Wrong symbol
- Range exceeds 7 days
- Output path inside tracked repo data
- Approval token missing or malformed
- Command attempts broker/account/order access
- Command touches live config, `STOP_TRADING`, `launchctl`, or price-path logger
- Generated data appears in `git status` as staged/tracked

## Decision
* `PREFLIGHT_PASS=true`
* `REAL_FETCH_APPROVED=false`
* `USER_APPROVAL_REQUIRED_FOR_REAL_FETCH=true`
* `ML_BLOCKED_UNTIL_REPLAY_GRADE_COVERAGE=true`
