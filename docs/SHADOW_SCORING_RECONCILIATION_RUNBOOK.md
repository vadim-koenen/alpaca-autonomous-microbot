# Shadow Scoring Reconciliation Runbook

## Overview

The `shadow_scoring_reconciliation.py` tool provides a unified advisory report by reconciling results from both the Shadow Learner Evaluator and Shadow Prospective Diagnostics. Its goal is to identify specific "buckets" (Model/Symbol/Horizon combinations) that show potential edge and to maintain a "Reject List" for those that do not.

## Risk Class

**Class 1: Advisory-only.** This tool does not mutate live bot state, place orders, or modify risk parameters.

## Prerequisites

- Access to the `shadow_learner.sqlite3` database.
- Labeled prospective outcomes (run `scripts/shadow_label_outcomes.py` first).

## Usage

### Run a full reconciliation for a specific period
```bash
python3 scripts/shadow_scoring_reconciliation.py --since 2026-05-28
```

### Run for a specific symbol
```bash
python3 scripts/shadow_scoring_reconciliation.py --since 2026-05-28 --symbol BTC/USD
```

### Save the report to a file
```bash
python3 scripts/shadow_scoring_reconciliation.py --since 2026-05-28 --output reports/scoring_reconciliation_2026-05-29.md
```

## Interpreting Results

### Reconciliation Conclusions

- `RECONCILED_NO_EDGE`: No significant evidence of edge found.
- `RECONCILED_WEAK_SIGNAL_TRACK_ONLY`: Some weak evidence exists; continue tracking.
- `RECONCILED_DATA_QUALITY_BLOCKED`: Data quality issues (e.g., missing outcomes) prevent a clear conclusion.
- `RECONCILED_INSUFFICIENT_SAMPLE`: Not enough prospective data yet.
- `RECONCILED_READY_FOR_HUMAN_REVIEW_ONLY`: Strong evidence across both tools; ready for human review of paper-mode eligibility.

### Bucket Watchlist Rules

A bucket is added to the **Watchlist** if:
- Sample size >= 50 and Accuracy Delta > 2% and Brier Delta > 0.005.
- OR Sample size >= 20 and Accuracy Delta > 5% and Brier Delta > 0.01.

A bucket is added to the **Reject List** if:
- Accuracy Delta <= 0 or Brier Delta <= 0 (underperforming or equal to random).

## Troubleshooting

- **No buckets in report**: Ensure you have labeled outcomes and that the random baseline model exists in the database.
- **Data Quality Blocked**: Check for high rates of `missing_data` in the evaluation report.

## Related Tools

- `scripts/shadow_evaluate_predictions.py`
- `scripts/shadow_prospective_diagnostics.py`
- `scripts/shadow_label_outcomes.py`
