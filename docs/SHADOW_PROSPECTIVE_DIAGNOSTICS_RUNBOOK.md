# Shadow Prospective Diagnostics Runbook

## Overview
The Shadow Prospective Diagnostics tool is used to evaluate the performance and calibration of "prospective" shadow predictions. Unlike retrospective predictions (which are backfilled), prospective predictions are generated at or before the time ($T_0$) they would have been made in a live setting, using only data available at that time.

This tool ensures that signals demonstrate a statistical edge and proper calibration before they can be considered for higher-tier validation (like Paper Trading).

## Usage
Run the diagnostics script using one of the following forms:

```bash
# Basic run for a specific date
python3 scripts/shadow_prospective_diagnostics.py --since 2026-05-28

# Filter by symbol
python3 scripts/shadow_prospective_diagnostics.py --since 2026-05-28 --symbol BTC/USD

# Filter by model
python3 scripts/shadow_prospective_diagnostics.py --since 2026-05-28 --model prospective_mean_reversion_v0

# Save output to a report file
python3 scripts/shadow_prospective_diagnostics.py --since 2026-05-28 --output reports/prospective_diagnostics_2026-05-29.md
```

## Interpreting Metrics

### Brier Score Delta
- **Brier Score**: Measures the accuracy of probabilistic predictions. Lower is better (0.0 is perfect).
- **Delta**: We compare the model's Brier score against the `prospective_random_baseline_v0`. A positive delta means the model is more accurate/better calibrated than random guessing.

### Calibration Buckets
We group predictions into confidence buckets:
- `0.40–0.45`: Bearish leaning.
- `exactly 0.50`: Neutral / Low confidence.
- `0.55–0.60` and `> 0.60`: Bullish leaning.

If a model is well-calibrated, the `actual_up_pct` should roughly track the `avg_prediction` value for that bucket.

### T0 Feature Capture Audit
The tool verifies that each prediction in the sample was marked as using only $T_0$ or prior data. Any failures here indicate a data leakage issue where future information might have contaminated the prediction.

## Final Diagnostic Conclusions

- **SIGNAL_DIAGNOSTICS_NO_EDGE**: The model does not perform significantly better than the random baseline.
- **SIGNAL_DIAGNOSTICS_WEAK_CALIBRATION**: There is a slight edge, but the predicted probabilities do not match realized outcomes well.
- **SIGNAL_DIAGNOSTICS_PROMISING_BUCKETS_TRACK_ONLY**: Strong performance in specific buckets or overall, but still requires more prospective tracking.
- **SIGNAL_DIAGNOSTICS_DATA_QUALITY_ISSUE**: Audit failures or inconsistent data found in the sample.
- **SIGNAL_DIAGNOSTICS_INSUFFICIENT_PROSPECTIVE_DATA**: Not enough labeled outcomes to make a statistically significant determination (usually < 20 samples).

## Troubleshooting
- **No data found**: Ensure that `shadow_ingest_logs` or a similar process has run to generate prospective predictions in the `shadow_learner.sqlite3` database.
- **No labeled outcomes**: Market data for the prediction horizons (e.g., 15m, 60m) may not have been ingested yet. Run the shadow price backfill or wait for the next ingest cycle.

---
**ADVISORY ONLY**: This tool is for research and diagnostics. It does not provide authorization for live trading.
