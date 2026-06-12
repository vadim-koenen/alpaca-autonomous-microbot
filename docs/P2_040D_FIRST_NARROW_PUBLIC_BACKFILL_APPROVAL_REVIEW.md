# P2-040D First Narrow Public Backfill Approval Review

## Approval Review Packet

This document constitutes the formal approval review packet for the first narrow public OHLCV backfill candidate. It was generated using the P2-040C workflow.

### Commit State
- **Current Main Commit:** 4238bc28e7d224c040b987e491faa8727258e479

### Candidate Backfill Scope
- **Provider:** `coinbase_public`
- **Symbol:** `BTC/USD`
- **Timeframe:** `1m`
- **Range:** `2026-06-04T23:00:00Z` to `2026-06-11T23:00:00Z` (7 days maximum)
- **Expected Total Bars:** 10,080
- **Missing Bars Estimate:** 10,080
- **Output Root:** `/tmp/p2_040d_market_data` (This is explicitly a temporary directory that will be ignored by Git).

### Safety Confirmations
- **Data Fetch Performed:** **FALSE** (This was a plan-only generation).
- **Approval Token Used:** **FALSE** (No token was passed; generation is purely informational).
- **Live Restarted:** **FALSE**
- **Authenticated APIs Used:** **FALSE**
- **Strategy/Risk Changes:** **FALSE**

### Generated Future Commands (Informational Only)
> [!WARNING]
> The following command is **informational only** and was **not executed** during this review generation. It is the command that will be run if and only if REAL_FETCH_APPROVED becomes true.

```bash
python3 scripts/p2_040a_public_backfill_approval_runner.py \
  --provider coinbase_public \
  --symbol BTC/USD \
  --timeframe 1m \
  --start 2026-06-04T23:00:00Z \
  --end 2026-06-11T23:00:00Z \
  --output-root /tmp/p2_040d_market_data \
  --allow-public-fetch \
  --approval-token PUBLIC_BACKFILL_APPROVED
```

### Preconditions for Real Fetch Execution
The following must be verified before the real fetch is permitted:
- [ ] Explicit user authorization with the `PUBLIC_BACKFILL_APPROVED` phrase.
- [ ] Acknowledgment that fetching does not trigger live trading or account access.
- [ ] Understanding that the output will be routed strictly to the temporary `output_root` and must not be staged or committed.

### Risk Considerations
- **Provider Rate Limits:** Coinbase public endpoints are rate-limited. The adapter must respect these limits.
- **Candle Gaps & Timestamp Alignment:** Network failures or exchange downtime may lead to missing candles. The substrate layer must align timestamps properly.
- **Timezone/UTC Handling:** All timestamps must be strict UTC.
- **Duplicate Candles / Schema Consistency:** The writer must upsert or reject duplicate timestamps to maintain schema integrity.
- **Manifest Integrity:** A `.manifest.json` will be written per chunk to track coverage. It must accurately reflect the data actually written.
- **Partial Latest Candle:** The fetch must not capture a partially formed candle if the end time aligns with the current active minute.

### Decision Recommendation
- `APPROVE_REVIEW_ONLY=true`
- `REAL_FETCH_APPROVED=false`
- `USER_APPROVAL_REQUIRED_FOR_REAL_FETCH=true`

### Baseline Reminder
> [!IMPORTANT]
> - **ML remains strictly blocked** until replay-grade historical coverage is established and proven.
> - **No trade remains the baseline behavior**.
> - The bot's verified economic baseline is **`NET_PNL≈-$1.58` across 80 historical trades**.
