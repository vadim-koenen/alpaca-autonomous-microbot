# P2-040J Replay-Grade Coverage Gate for Multi-Day Fetch Approval

## Current Main Commit
`b6f1f03d50f1a6676efbc2c4d7278632ee6a1505`

## Prior Evidence Chain
* P2-040F first narrow fetch completed
* P2-040G manifest validation passed
* P2-040H boundary policy defined
* P2-040I normalized replay smoke passed

## Candidate Future Fetch (Not Executed)
* **provider**: coinbase_public
* **symbol**: BTC/USD
* **timeframe**: 1m
* **range**: 7 days maximum
* **output_root**: /tmp or ignored local path

## Gate Decision Fields
* `COVERAGE_GATE_DEFINED=true`
* `PRIOR_NARROW_FETCH_VALIDATED=true`
* `NORMALIZED_REPLAY_SMOKE_TEST_PASS=true`
* `MULTIDAY_FETCH_READY_FOR_USER_APPROVAL=true`
* `MULTIDAY_FETCH_APPROVED=false`
* `PUBLIC_FETCH_PERFORMED=false`
* `REPLAY_GRADE_COVERAGE_APPROVED=false`
* `ML_BLOCKED_UNTIL_REPLAY_GRADE_COVERAGE=true`

## The Exact Future Approval Phrase Placeholder
`PUBLIC_BACKFILL_APPROVED for coinbase_public BTC/USD 1m 7-day fetch output_root=/tmp`

## The Exact Future Command Template
> [!WARNING]
> **NOT EXECUTED IN P2-040J**
> **INFORMATIONAL ONLY**
> **REQUIRES SEPARATE USER APPROVAL**

```bash
python3 scripts/p2_040a_public_backfill_approval_runner.py \
    --provider coinbase_public \
    --symbol BTC/USD \
    --timeframe 1m \
    --start 2026-06-03T23:00:00Z \
    --end 2026-06-10T23:00:00Z \
    --output-root /tmp \
    --allow-public-fetch \
    --approval-token PUBLIC_BACKFILL_APPROVED_...
```

## Stop Conditions
* prior smoke test failed
* boundary policy missing
* normalization utility missing
* output path is tracked
* fetch range exceeds 7 days
* provider differs from coinbase_public
* symbol differs from BTC/USD
* timeframe differs from 1m
* approval token is missing for future real fetch
* generated data appears in git status
* command attempts broker/account/order access
* command touches live config, STOP_TRADING, launchctl, or price-path logger
* ML or live strategy consumes data before replay-grade approval

## Recommendation
The coverage gate is satisfied. The next step may be asking the user for explicit approval for P2-040K — 7-Day Public Backfill Execution. Do not run P2-040K without the exact user approval phrase.
