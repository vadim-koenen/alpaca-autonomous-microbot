# P2-040C Narrow Public Backfill Plan Report Workflow

## Purpose

Defines the workflow for generating an auditable, narrow, plan-only public OHLCV backfill report prior to actual data fetch. The workflow strictly separates the planning phase (read-only, no network access) from the execution phase.

## Workflow

The plan report is generated using the P2-040B planner script. This guarantees that:
1. No real public fetch is performed.
2. No implicit execution flags are set.
3. The exact commands required to fetch the data are provided cleanly as `future_commands` inside a JSON report.
4. Future commands require separate manual approval and execution using the `PUBLIC_BACKFILL_APPROVED` token.

### Generation Command

To generate a narrow public backfill plan for a 7-day period of BTC/USD 1m bars:

```bash
python3 scripts/p2_040b_public_backfill_coverage_plan.py \
  --provider coinbase_public \
  --symbols BTC/USD \
  --timeframe 1m \
  --days 7 \
  --end 2026-06-11T23:00:00Z \
  --output-root /tmp/p2_040c_market_data \
  --report-json /tmp/p2_040c_plan_report.json
```

### Output Example

The resulting JSON report (`/tmp/p2_040c_plan_report.json`) will structurally mirror:

```json
{
  "plan_only": true,
  "public_fetch_performed": false,
  "provider": "coinbase_public",
  "symbols": ["BTC/USD"],
  "expected_bars_total": 10080,
  "coverage_gap_summary": 10080,
  "future_approval_required": true,
  "approval_token_required": true,
  "approval_token_value": "PUBLIC_BACKFILL_APPROVED",
  "ml_blocked_until_replay_grade_coverage": true,
  "economic_baseline": "NET_PNL≈-$1.58 across 80 historical trades",
  "future_commands": [
    "python3 scripts/p2_040a_public_backfill_approval_runner.py \\\n  --provider coinbase_public \\\n  --symbol BTC/USD \\\n  --timeframe 1m \\\n  --start 2026-06-04T23:00:00Z \\\n  --end 2026-06-11T23:00:00Z \\\n  --output-root /tmp/p2_040c_market_data \\\n  --allow-public-fetch \\\n  --approval-token PUBLIC_BACKFILL_APPROVED"
  ]
}
```

## Governance Constraints

- **No live trading interference:** Live restart, STOP_TRADING, launchctl, and risk/config modifications are strictly forbidden.
- **Data safety:** No actual market data (Parquet, DuckDB) is generated during this step. Output is purely informational.
- **ML Blocked:** Machine Learning and online prediction remain blocked until replay-grade historical coverage is proven.
