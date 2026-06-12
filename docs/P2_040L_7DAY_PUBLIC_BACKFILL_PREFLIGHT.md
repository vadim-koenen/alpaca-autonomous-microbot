# P2-040L 7-Day Public Backfill Preflight

## Base Commit
Stacked on P2-040K commit (which is based on `d0f70f1759f565b5c7b87b200276fa3e8410ad3b`).

## Candidate Future Fetch
* **provider**: coinbase_public
* **symbol**: BTC/USD
* **timeframe**: 1m
* **range**: 7 days maximum
* **output_root**: /tmp

## Verification
* `PUBLIC_FETCH_PERFORMED=false`
* `APPROVAL_TOKEN_USED=false`
* `MULTIDAY_FETCH_APPROVED=false`
* `REPLAY_GRADE_COVERAGE_APPROVED=false`
* `ML_BLOCKED_UNTIL_REPLAY_GRADE_COVERAGE=true`

## Preflight Checklist
* [x] working tree clean
* [x] output path is /tmp or ignored
* [x] command range <= 7 days
* [x] symbol/timeframe/provider match approval packet
* [x] boundary normalization policy exists
* [x] normalized smoke test passed
* [x] post-fetch validation plan exists
* [x] generated data must remain uncommitted
* [x] no broker/account/order API access
* [x] no STOP_TRADING, launchctl, price-path logger, strategy, risk, sizing, notional, or capital changes

## Stop Conditions
* range exceeds 7 days
* output path tracked
* approval phrase absent
* command touches broker/account/order or live config
* generated data appears staged
* schema/gap/duplicate/UTC validation cannot be run after fetch

## Decision
* `PREFLIGHT_PASS=true`
* `PUBLIC_FETCH_PERFORMED=false`
* `MULTIDAY_FETCH_APPROVED=false`
* `USER_APPROVAL_REQUIRED_FOR_REAL_FETCH=true`
* `REPLAY_GRADE_COVERAGE_APPROVED=false`
