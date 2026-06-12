# P2-040K 7-Day Public Backfill Approval Packet

## Base Commit
`d0f70f1759f565b5c7b87b200276fa3e8410ad3b`

## Prior Evidence Chain
* P2-040F first narrow public fetch completed.
* P2-040G manifest validation passed.
* P2-040H boundary normalization policy defined.
* P2-040I normalized replay smoke passed.
* P2-040J coverage gate passed and says multiday fetch is ready for user approval.

## Candidate Future Fetch
* **provider**: coinbase_public
* **symbol**: BTC/USD
* **timeframe**: 1m
* **range**: 7 days maximum
* **output_root**: /tmp

## Required Future Approval Phrase
`PUBLIC_BACKFILL_APPROVED for coinbase_public BTC/USD 1m 7-day fetch output_root=/tmp`

## Future Command Template
> [!WARNING]
> **NOT EXECUTED IN P2-040K**
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

## Decision
* `APPROVAL_PACKET_WRITTEN=true`
* `PUBLIC_FETCH_PERFORMED=false`
* `MULTIDAY_FETCH_APPROVED=false`
* `USER_APPROVAL_REQUIRED_FOR_REAL_FETCH=true`
* `REPLAY_GRADE_COVERAGE_APPROVED=false`
* `ML_BLOCKED_UNTIL_REPLAY_GRADE_COVERAGE=true`
