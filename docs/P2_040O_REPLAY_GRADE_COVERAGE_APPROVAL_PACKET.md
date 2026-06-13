# P2-040O Replay-Grade Coverage Approval Packet

## Base Commit
`4160605a9f8b18b8471dcdad7f5af10898e61704` (after P2-040N)

## Evidence Chain
* P2-040M 7-day public backfill completed.
* P2-040N 7-day manifest validation passed.
* Raw inclusive candle count: 10081.
* Normalized replay candle count: 10080.
* Coverage audit pass: true.
* Coverage audit percent: 100.0.
* UTC aligned: true.
* Monotonic timestamps: true.
* Duplicate timestamps after normalization: false.
* Gaps after normalization: false.
* Schema preserved after normalization: true.
* Manifest provenance preserved or referenced: true.

## Dataset Scope
* **Provider:** coinbase_public
* **Symbol:** BTC/USD
* **Timeframe:** 1m
* **Range:** 7 days
* **Output Root:** /tmp

## Required Future Approval Phrase
`REPLAY_GRADE_COVERAGE_APPROVED for coinbase_public BTC/USD 1m 7-day dataset at 4160605a9f8b18b8471dcdad7f5af10898e61704`

## Decision State
* `REPLAY_GRADE_COVERAGE_READY_FOR_APPROVAL=true`
* `REPLAY_GRADE_COVERAGE_APPROVED=false`
* `ML_BLOCKED_UNTIL_REPLAY_GRADE_COVERAGE=true`

> [!WARNING]
> Approval would only allow replay-grade use for offline research/backtesting.
> It must not enable ML live influence.
> It must not enable trading changes.
> It must not change risk/sizing/capital.
> It must not approve broader fetches.
