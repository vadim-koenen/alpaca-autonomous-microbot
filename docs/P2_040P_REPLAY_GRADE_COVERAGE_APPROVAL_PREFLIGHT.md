# P2-040P Replay-Grade Coverage Approval Preflight

## Base Commit
`67c75c9e7264a74267077088b95fc80313cd1ab6`

## Stack Info
* `STACKED_ON_P2_040O=true`

## Dataset Scope
* **Provider:** coinbase_public
* **Symbol:** BTC/USD
* **Timeframe:** 1m
* **Range:** 7 days

## Preflight Checks
* P2-040M fetch summary exists.
* P2-040N validation review exists.
* P2-040O approval packet exists or is pending merge if stacked.
* Coverage audit is 100.0%.
* Normalized replay count is 10080.
* No duplicates after normalization.
* No gaps after normalization.
* Schema preserved.
* Manifest provenance preserved or referenced.
* Generated data remains uncommitted.
* Replay-grade approval would be offline-only.
* ML remains blocked.
* Live influence remains blocked.

## Decision
* `PREFLIGHT_PASS=true`
* `REPLAY_GRADE_COVERAGE_READY_FOR_USER_APPROVAL=true`
* `REPLAY_GRADE_COVERAGE_APPROVED=false`
* `ML_BLOCKED_UNTIL_REPLAY_GRADE_COVERAGE=true`
