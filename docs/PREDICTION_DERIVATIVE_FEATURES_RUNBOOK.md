# Prediction Derivative Features Runbook (P2-002)

## Overview

The Prediction Derivative Features layer provides an advisory-only scaffold for calculating derived market features from existing shadow learner data. These features (e.g., returns, velocity, volatility) are used to prepare the bot for future offline model training and evaluation without influencing live trading.

## Risk Class

**Class 1.5: Advisory-only.** This implementation does not mutate live bot state, place orders, or modify risk parameters. All calculations are performed on shadow-mode data.

## Features Implemented

- **Returns**: `return_1m`, `return_5m`, `return_15m`, `return_30m`, `return_60m`.
- **Price Velocity**: `price_velocity_5m`, `price_velocity_15m` (change per minute).
- **Price Acceleration**: `price_acceleration_15m` (velocity change per minute).
- **Volatility**: `volatility_15m`, `volatility_60m` (standard deviation of log returns).
- **Range**: `high_low_range_15m` (percentage distance between high and low).
- **Performance**: `recent_win_rate_by_symbol`, `mfe_mae_ratio` (from labeled outcomes).
- **Brier Score**: Calculated per bucket where outcomes are available.

## Usage

### Run the feature coverage report
```bash
python3 scripts/shadow_prediction_feature_report.py --since 2026-05-28
```

### Run for a specific symbol
```bash
python3 scripts/shadow_prediction_feature_report.py --since 2026-05-28 --symbol BTC/USD
```

### Save the report to a file
```bash
python3 scripts/shadow_prediction_feature_report.py --since 2026-05-28 --output reports/prediction_derivative_features_2026-05-29.md
```

## Interpreting the Report

- **Price Point Coverage**: Shows how many raw 1m price points are available per symbol.
- **Derivative Feature Examples**: Provides a snapshot of calculated features for the current time (T0) using available history.
- **Scoring Watch Buckets**: Integrated from P1-006D to show which buckets currently show potential edge.
- **BTC/ETH/SOL Evaluation Readiness**: Indicates if enough exploration data has been collected to perform robust prediction evaluation.

## Troubleshooting

- **ERROR: no_prior_prices**: Ensure `scripts/shadow_backfill_prices.py` or `scripts/shadow_import_prices.py` has been run for the symbol and time range.
- **n/a for Win Rate**: Ensure `scripts/shadow_label_outcomes.py` has been run to process pending predictions into outcomes.

## Related Tools

- `scripts/shadow_scoring_reconciliation.py`
- `scripts/shadow_evaluate_predictions.py`
- `shadow_learner/derivative_features.py`
