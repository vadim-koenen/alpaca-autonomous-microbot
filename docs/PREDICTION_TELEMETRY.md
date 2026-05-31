# P2-012A — Prediction Telemetry and Derivative-Style Market Feature Logging

**Status:** Active instrumentation. No effect on live order decisions. Logger hook remains blocked.

## What Was Added

- `prediction_telemetry.py` — core module with:
  - Pure, deterministic derivative feature calculations (`compute_derivative_features` and helpers for slope, acceleration, volatility, spread, range).
  - Safe append-only writer to `prediction_telemetry/prediction_telemetry.jsonl` (new file, schema-versioned).
  - `log_proposal_candidate` and `log_skipped_proposal` helpers.

- `scripts/coinbase_prediction_status.py` — read-only reporting tool for recent predictions and basic stats.

- `tests/test_prediction_telemetry.py` and `tests/test_coinbase_prediction_status.py`

- `docs/PREDICTION_TELEMETRY.md` (this file)

- Small, non-behavior-changing integration in `strategy_router.py` so every generated proposal is logged as a "candidate" for future evaluation.

No changes were made to:
- Strategy logic, risk decisions, order submission, TP/SL, sizing, symbols, or any live trading path.
- `logs/coinbase_fills.csv` or the production fill logger.
- `ACTIVE_HANDOFF.md`

## Telemetry Schema (v1)

Every row contains (among other fields):
- timestamp, schema_version
- symbol, strategy, regime, side
- confidence, proposed_notional, entry_price, bid, ask, spread_pct
- decision_status ("candidate", "skipped", "placed", ...)
- skip_reason (when applicable)
- prediction_horizons and outcome placeholders (for future labeling)
- features (short_slope, medium_slope, acceleration, volatility, spread_bps, range_position, ...)
- source
- raw_payload (the original proposal/state snapshot)

## Derivative Features

All features are computed from recent price series (or passed bid/ask/current):
- short_slope / medium_slope (linear regression on recent windows)
- acceleration (difference of slopes)
- volatility (std of log returns)
- spread_bps
- range_position (where current price sits in recent min/max)

Helpers gracefully return None on insufficient data.

## Usage

The system now automatically logs proposals from `strategy_router`.

You can also call directly from anywhere (including tests or the dry-run capture seam):

```python
from prediction_telemetry import log_proposal_candidate, log_skipped_proposal, compute_derivative_features

log_proposal_candidate(proposal, regime="trend", source="my_test")
log_skipped_proposal(proposal, reason="spread_too_wide")

features = compute_derivative_features(recent_closes, bid=bid, ask=ask)
```

## Reporting

```bash
python3 scripts/coinbase_prediction_status.py
python3 scripts/coinbase_prediction_status.py --json --limit 100
```

## Safety & Non-Regression

- Telemetry writer is append-only and schema-versioned.
- All existing Coinbase and capture/reconciliation tests continue to pass.
- No production logging paths were modified or enabled.
- The module is deliberately tolerant of missing data.

---

P2-012A complete. Prediction telemetry and derivative feature logging are now active for measurement and future model work. No trading behavior was altered.
