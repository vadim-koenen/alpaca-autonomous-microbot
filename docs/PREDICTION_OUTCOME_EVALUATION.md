# P2-013A — Prediction Outcome Evaluation + Trade Attribution (Read-Only)

This document describes the read-only measurement layer added in P2-013A.

## Purpose

- Evaluate whether the signals captured in `prediction_telemetry.jsonl` (from P2-012x series) had predictive power over 15/30/60/90-minute horizons.
- Compute standard trading metrics on historical price series (local data or injected fixture).
- Attribute realized P&L from the trade journal back to originating prediction rows where possible (best-effort matching by symbol, strategy, time, side).

Everything is strictly read-only and non-blocking. No changes to live strategy, order flow, risk, or any trading parameters.

## Core Components

- `PredictionOutcomeEvaluator` (in `prediction_telemetry.py`):
  - `load_prediction_telemetry_rows`
  - `evaluate_row` / `evaluate_rows` over configurable horizons
  - Computes: future price, pct move, direction hit/miss/neutral, MFE, MAE (endpoint approximation; full series when provider supplies it)
  - `attribute_to_journal`: joins telemetry candidates/placed rows to journal entries and exits
  - `run_evaluation` + `_compute_summary`: hit rates by symbol/regime/strategy, skipped reason counts, candidate→trade conversion, P&L attribution by symbol

- `scripts/coinbase_prediction_outcomes.py`: CLI that runs the evaluator and prints human-readable summaries (or JSON).

- Price data: Uses `data/manual_prices/*.jsonl` when available, or an injectable `PriceSeriesProvider` (for tests/fixtures). No network calls.

## Output Fields (per evaluated row)

- horizon_min
- future_price
- pct_move
- direction_outcome ("hit" / "miss" / "neutral" / "insufficient_data")
- mfe, mae
- symbol, strategy, regime, decision_status

## Attribution

- Matches prediction row → journal entry (BUY/PLACED) by symbol + strategy + time proximity (±10 min) + side
- Locates corresponding EXIT row for the same trade
- Attaches `pnl_usd` when available

## Usage

```bash
python3 scripts/coinbase_prediction_outcomes.py
python3 scripts/coinbase_prediction_outcomes.py --json
python3 scripts/coinbase_prediction_outcomes.py --telemetry logs/prediction_telemetry.jsonl
```

## Safety & Constraints

- 100% read-only on all inputs (telemetry, journal, price fixtures).
- Never calls any order, risk, or fill-logging paths.
- Does not modify any caps, symbols, strategy logic, or runtime behavior.
- All existing P2-012x telemetry, scanning, and risk behavior remains unchanged.
- Tests use only synthetic fixtures or local files — no network.

## Limitations (by design for P2-013A)

- MFE/MAE are endpoint approximations unless a full-bar series provider is injected.
- Attribution is best-effort (no perfect unique trade ID linking yet — that is future work once fill logger facts are proven).
- Horizons are evaluated only when sufficient local price data exists around the proposal timestamp.

This layer exists purely for measurement and learning. It does not influence live decisions.

---

P2-013A read-only outcome evaluator + attribution complete. No trading behavior changed.
