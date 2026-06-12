# P2-040H Boundary Normalization / Window Stitching Policy

## Current Main Commit
`013e1243f75da421ec284b8d8500a37a62436a90`

## Source Finding
P2-040G validated the narrow BTC/USD 1m fetch as inclusive start and inclusive end.
A 1-day range produced 1441 timestamp rows.
The end-exclusive replay expectation for 24 hours is 1440 rows.

## Policy Decision
Replay windows should use end-exclusive semantics.
Public fetch outputs with inclusive end boundary must be normalized before replay/stitching.
For adjacent windows, drop exactly one duplicated boundary candle at the start of every window after the first, or equivalently slice each replay window as `[start, end)`.
Never double-count a shared candle boundary.

## Expected Examples
**Single 24-hour 1m replay window:**
* requested source range inclusive may contain 1441 rows
* normalized replay slice should contain 1440 rows

**Two adjacent 24-hour windows:**
* raw inclusive outputs may contain 1441 + 1441 rows
* stitched normalized replay output should contain 2880 unique minute candles, not 2881 or 2882

## Validation Requirements
* UTC alignment required
* monotonic timestamps required
* no duplicate timestamps after stitching
* no gaps after stitching
* schema consistency required
* manifest provenance preserved
* partial/latest candle excluded or explicitly marked
* generated data remains uncommitted
* replay-grade coverage remains false until normalization is implemented and tested

## Stop Conditions
* duplicate boundary candle remains after stitching
* timestamp gap appears after normalization
* non-UTC timestamp detected
* schema drift detected
* source manifest missing
* generated data appears staged or committed
* broader fetch attempted without explicit approval

## Decision
* `BOUNDARY_POLICY_DEFINED=true`
* `NORMALIZATION_REQUIRED_BEFORE_REPLAY=true`
* `REPLAY_GRADE_COVERAGE_APPROVED=false`
* `BROADER_FETCH_APPROVED=false`
* `ML_BLOCKED_UNTIL_REPLAY_GRADE_COVERAGE=true`
