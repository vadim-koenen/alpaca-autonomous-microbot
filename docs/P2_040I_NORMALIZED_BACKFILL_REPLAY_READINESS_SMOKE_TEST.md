# P2-040I Normalized Backfill Replay Readiness Smoke Test

## Current Main Commit
`3c039cce78cf69ef7ad4b30d9b710309003d5b1b`

## P2-040H Policy Basis
* `BOUNDARY_SEMANTICS=INCLUSIVE_START_AND_END`
* `REPLAY_WINDOW_POLICY=END_EXCLUSIVE`
* `STITCHING_DUPLICATE_BOUNDARY_POLICY=DROP_OVERLAPPING_AND_ENFORCE_END_EXCLUSIVE`

## Input Source
* Used existing `/tmp/BTC_USD/1m` P2-040F data for the single-window test.
* Used committed synthetic fixtures for the adjacent-window stitching test.
* `PUBLIC_FETCH_PERFORMED=false`

## Smoke Test Results
* `single_window_raw_count=1441`
* `single_window_normalized_count=1440`
* `two_window_raw_count=2882`
* `two_window_stitched_count=2880`
* `utc_aligned=true`
* `monotonic_timestamps=true`
* `duplicate_timestamps_found_after_normalization=false`
* `gaps_found_after_normalization=false`
* `schema_preserved=true`
* `manifest_provenance_preserved_or_referenced=true`
* `generated_data_committed=false`

## Decision
* `NORMALIZED_REPLAY_SMOKE_TEST_PASS=true`
* `REPLAY_GRADE_COVERAGE_APPROVED=false`
* `BROADER_FETCH_APPROVED=false`
* `ML_BLOCKED_UNTIL_REPLAY_GRADE_COVERAGE=true`

## Recommendation
The smoke test passed. The next patch should be P2-040J — Replay-Grade Coverage Gate for Multi-Day Fetch Approval, still no ML.
