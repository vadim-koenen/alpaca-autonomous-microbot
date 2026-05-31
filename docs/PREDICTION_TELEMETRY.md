# P2-012A — Prediction Telemetry

This document covers the prediction telemetry and derivative-style feature scaffolding added in P2-012A.

## Goals

- Capture every candidate signal/proposal (including skipped ones) for future evaluation.
- Compute a standard set of deterministic derivative-style market features from price series.
- Store the data in a dedicated, append-only file separate from the production fill logger.
- Provide read-only reporting tools.

## Telemetry File

Location (by default):
`logs/prediction_telemetry.jsonl`

This file is **never** written to by the production fill logger and is never read by risk/order logic in this patch.

## Schema (v1)

Key fields:
- timestamp, schema_version
- symbol, product_id, product_type
- strategy, regime, side
- confidence, proposed_notional, reference_price
- bid, ask, spread_bps
- decision_status (candidate / skipped / placed / filled / exited / unknown)
- reason (when skipped)
- horizon_*_outcome placeholders
- features (short_slope, medium_slope, acceleration, volatility, spread_bps, range_position, ...)
- source
- raw_payload (original proposal/state snapshot)

## Feature Helpers

Pure functions in `prediction_telemetry.py`:

- `compute_derivative_features(prices, bid=None, ask=None, current_price=None)`
- Individual helpers: `compute_short_slope`, `compute_medium_slope`, `compute_acceleration`, `compute_volatility`, `compute_spread_bps`, `compute_range_position`

All degrade gracefully to None on insufficient data.

## Usage (Non-Blocking)

```python
from prediction_telemetry import log_proposal_candidate, log_skipped_proposal, compute_derivative_features

log_proposal_candidate(proposal, regime="trend", source="strategy_router")
log_skipped_proposal(proposal, reason="spread_too_wide")

feats = compute_derivative_features(recent_closes, bid=bid, ask=ask)
```

## Status Script

```bash
python3 scripts/coinbase_prediction_status.py
python3 scripts/coinbase_prediction_status.py --json
```

Shows counts by product_type / decision_status and recent rows.

## Safety

- Writing is append-only with schema header on first creation.
- No effect on live order flow or risk decisions.
- All existing Coinbase tests continue to pass.
- No interaction with `logs/coinbase_fills.csv` or `append_coinbase_fill_row`.

## Future Use

This telemetry + feature set is intended to feed future prediction models and performance attribution once the full broker-fact proof for exits (P2-011x series) is complete and the fill logger hook is eventually enabled under strict controls.

---

P2-012A prediction telemetry component complete. No trading behavior or logger writes were changed.
