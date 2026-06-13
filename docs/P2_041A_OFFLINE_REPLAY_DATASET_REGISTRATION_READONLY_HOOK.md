# P2-041A Offline Replay Dataset Registration / Read-Only Hook

## Current Main Commit
`ebdc651b707e257e58d57ac19000a830b30fc72a`

## Dataset Registration
* **provider**: `coinbase_public`
* **symbol**: `BTC/USD`
* **timeframe**: `1m`
* **range**: `2026-06-03T23:00:00+00:00` to `2026-06-10T23:00:00+00:00`
* **raw_inclusive_candle_count**: `10081`
* **normalized_replay_candle_count**: `10080`
* **replay_grade_coverage_approved**: `true`
* **offline_replay_only**: `true`

## Consumer Behavior
* **read_only_consumer_hook_added**: `true`
* **public_fetch_performed**: `false`
* **ml_training_started**: `false`
* **live_influence_approved**: `false`
* **broker_order_mutation**: `false`

## Local Data Behavior
* `/tmp` path is only a hint
* missing local data does not trigger fetch
* generated data remains uncommitted

## Decision
* `OFFLINE_REPLAY_DATASET_REGISTERED=true`
* `READ_ONLY_CONSUMER_HOOK_READY=true`
* `ML_TRAINING_APPROVED=false`
* `ML_LIVE_INFLUENCE_ENABLED=false`
* `LIVE_TRADING_CHANGES_APPROVED=false`

## Recommendation
Next patch should be **P2-041B — Offline No-Trade Baseline Replay Harness**.
Do not start ML yet.
