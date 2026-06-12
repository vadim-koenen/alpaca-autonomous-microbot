# P2-040F First Narrow Public Backfill Execution

## Execution Summary
This document summarizes the execution of the first authorized real public OHLCV backfill for the Investing Bot project.

* **Current Main Commit:** ecb8014f77f734c456d62a44f8ffaf079b369fc0

* **User Approval Phrase:**
  `PUBLIC_BACKFILL_APPROVED for coinbase_public BTC/USD 1m 1-day narrow fetch output_root=/tmp`

* **Executed Scope:**
  * **Provider:** `coinbase_public`
  * **Symbol:** `BTC/USD`
  * **Timeframe:** `1m`
  * **Range:** 1 day (`2026-06-10T23:00:00Z` to `2026-06-11T23:00:00Z`)
  * **Output Root:** `/tmp`

## Confirmations
* `PUBLIC_FETCH_PERFORMED=true`
* `GENERATED_DATA_COMMITTED=false`
* `AUTHENTICATED_BROKER_API_USED=false`
* `ACCOUNT_ACCESS_USED=false`
* `BROKER_ORDER_MUTATION=false`
* `LIVE_RESTARTED=false`
* `STOP_TRADING_TOUCHED=false`
* `LAUNCHCTL_TOUCHED=false`
* `PRICE_PATH_LOGGER_TOUCHED=false`
* **STRATEGY/RISK/SIZING** unchanged
* `ML_BLOCKED_UNTIL_REPLAY_GRADE_COVERAGE=true`

## Output Metadata
* **Output Directory:** `/tmp/BTC_USD/1m`
* **Manifest Path:** `/tmp/BTC_USD/1m/coinbase_public_BTC_USD_1m.manifest.json`
* **Candle Count:** 1441
* **Timestamp Range:** `2026-06-10T23:00:00+00:00` to `2026-06-11T23:00:00+00:00`
* **Duplicate Timestamp Check:** Passed (no duplicates)
* **Gap Check:** Passed (0 missing bars detected by coverage audit)
* **Schema Check:** Passed (Parquet schema version 1)
* **UTC Alignment Check:** Passed (strict ISO8601 UTC)

## Decision
* `REAL_PUBLIC_FETCH_COMPLETED=true`
* `REPLAY_GRADE_COVERAGE_APPROVED=false`
* **NEXT_STEP:** P2-040G narrow backfill validation / manifest integrity review
