# Claude Handoff: Prediction Derivative Features (2026-05-29)

## Executive Summary
I have implemented **P2-002: Prediction + Derivative Feature Layer**. This implementation provides an advisory-only scaffold for calculating derived market features (returns, velocity, volatility, etc.) from existing shadow learner data. This layer is designed for future model training and evaluation and has **NO LIVE TRADING INFLUENCE**.

## Features Implemented
- **Returns**: Multi-window returns (1m, 5m, 15m, 30m, 60m).
- **Dynamics**: Price velocity (5m, 15m) and price acceleration (15m).
- **Risk/Vol**: Volatility (15m, 60m) and high-low range (15m).
- **Performance**: Recent win rates and MFE/MAE ratios by symbol from labeled outcomes.
- **Scoring**: Integrated P1-006D scoring watch buckets into the feature report.

## Files Changed
- `shadow_learner/derivative_features.py`: Pure mathematical logic for feature calculations.
- `shadow_learner/prediction_features.py`: Data orchestration and assembly of feature vectors.
- `scripts/shadow_prediction_feature_report.py`: CLI reporting tool for feature coverage and examples.
- `docs/PREDICTION_DERIVATIVE_FEATURES_RUNBOOK.md`: Usage and interpretation guide.
- `tests/test_prediction_derivative_features.py`: Unit tests for derivative calculations.

## Validation Results
- **Compile**: `py_compile` confirmed all new modules and scripts are syntactically correct.
- **Reporting**: `shadow_prediction_feature_report.py` successfully calculated features for BTC/USD, ETH/USD, and SOL/USD using the latest available price history.
- **Readiness**: BTC, ETH, and SOL are flagged as **READY** for prediction evaluation (enough points and samples collected).

## Important Warnings
- **Advisory Only**: No live trading behavior or risk parameters were modified.
- **Data Gaps**: Spread trend calculation is currently a placeholder requiring a deeper join with feature snapshots.
- **T0 Selection**: The report uses the latest available price point as T0 for example calculations to ensure coverage.

## Next Commands for Claude/User

### 1. Feature Coverage Check
```bash
python3 scripts/shadow_prediction_feature_report.py --since 2026-05-28
```

### 2. Run Derivative Tests
```bash
python3 -m pytest tests/test_prediction_derivative_features.py -q
```

### 3. Generate Evaluation Report (P1-006D)
```bash
python3 scripts/shadow_scoring_reconciliation.py --since 2026-05-28
```

## Safety Gates
- **.env**: Not touched.
- **Core Modules**: No changes to `broker_*`, `order_manager`, `risk_manager`, or `main.py`.
- **Live Trading**: No changes to strategy or execution logic.

## Next Recommended Patch
**P2-003: Derivative Feature Persistence**. The next logical step is to persist these calculated features back into the `shadow_feature_snapshots` table (in `features_json`) during ingestion, allowing for easier historical analysis and training.
