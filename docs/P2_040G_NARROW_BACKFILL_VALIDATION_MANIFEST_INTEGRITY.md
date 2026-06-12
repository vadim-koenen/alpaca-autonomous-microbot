# P2-040G Narrow Backfill Validation / Manifest Integrity Review

This document summarizes the validation and integrity check for the first narrow public Coinbase BTC/USD 1m backfill output.

* **Current Main Commit:** a06dfaf94db5b6256bc922c2c034342df203a69f

## Source P2-040F Fetch Metadata
* **Provider:** `coinbase_public`
* **Symbol:** `BTC/USD`
* **Timeframe:** `1m`
* **Range:** `2026-06-10T23:00:00Z` to `2026-06-11T23:00:00Z`
* **Output Directory:** `/tmp/BTC_USD/1m`
* **Manifest Path:** `/tmp/BTC_USD/1m/coinbase_public_BTC_USD_1m.manifest.json`

## Validation Results
* `candle_count=1441`
* `expected_count_under_inclusive_boundary=1441`
* `expected_count_under_end_exclusive_boundary=1440`
* `boundary_semantics=INCLUSIVE_START_AND_END`
* `utc_aligned=true`
* `monotonic_timestamps=true`
* `duplicate_timestamps_found=false`
* `gaps_found=false`
* `schema_validated=true`
* `partial_latest_candle_excluded_or_marked=true`
* `manifest_integrity_valid=true`
* `generated_data_committed=false`

## Decision
* `NARROW_BACKFILL_VALIDATED=true`
* `REPLAY_GRADE_COVERAGE_APPROVED=false`
* `BROADER_FETCH_APPROVED=false`
* `ML_BLOCKED_UNTIL_REPLAY_GRADE_COVERAGE=true`

## Recommendation
The validation confirms `1441` rows, which perfectly matches an **inclusive start and end boundary** (`INCLUSIVE_START_AND_END`) over a 24-hour period. Because this indicates an off-by-one risk when stitching consecutive days, we recommend:

**A. Normalize replay windows to end-exclusive slices before replay, OR**
**B. Formally document inclusive candle-start semantics and avoid double-counting window boundaries in multi-day stitching.**

The current behavior is fully valid as a standalone slice, but requires awareness before broader fetches.
