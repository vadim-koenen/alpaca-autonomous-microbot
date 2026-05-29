# Shadow Learner Advisory Evaluation Runbook

## Purpose

Evaluate advisory shadow learner directional predictions against labeled
outcomes. This is an analysis/reporting workflow only.

It does not authorize live trading, model promotion, strategy changes, risk cap
changes, symbol expansion, or sizing changes.

## Scope

The evaluator reads only advisory shadow tables:

```text
shadow_predictions
shadow_outcomes
shadow_feature_snapshots
shadow_price_points
shadow_news_items
shadow_news_signal_links
```

News context is shown only as context. It is not causal proof.

## Commands

Run from the project root:

```bash
python3 scripts/shadow_evaluate_predictions.py --since 2026-05-28
python3 scripts/shadow_evaluate_predictions.py --since 2026-05-28 --broker coinbase
python3 scripts/shadow_evaluate_predictions.py --since 2026-05-28 --symbol BTC/USD
python3 scripts/shadow_evaluate_predictions.py --since 2026-05-28 --model retrospective_momentum_v0
```

Optional markdown export:

```bash
python3 scripts/shadow_evaluate_predictions.py \
  --since 2026-05-28 \
  --output reports/shadow_eval_2026-05-28.md
```

## Required Interpretation

Treat retrospective results as hypothesis generation only.

Required warnings:

- Retrospective predictions are advisory backfilled predictions, not live-proven
  signals.
- No model output is used for orders, risk approvals, position sizing, or symbol
  selection.
- This report does not authorize scaling.
- Missing-data outcomes remain present and can bias comparisons.
- Equity snapshots remain mostly non-directional/no-price/no-bar.
- Crypto-only labeled samples may not generalize across assets or regimes.
- If random baseline performs similarly, report no evidence of edge.

## Evidence Statuses

The report may emit:

```text
NO_EVIDENCE_OF_EDGE
WEAK_SIGNAL_REQUIRES_MORE_DATA
PROMISING_RETROSPECTIVE_SIGNAL_NOT_LIVE_APPROVED
INSUFFICIENT_DATA_AFTER_FILTERS
DATA_QUALITY_FAILURE
```

It must never emit or imply live approval.

## Promotion Gate

Promotion remains closed unless all are true:

- Prospective, not retrospective-only, results exist.
- Signal beats random baseline materially.
- Enough samples exist across multiple days/regimes.
- Paper-mode validation confirms behavior.
- Human approval is given.
- Rollback plan exists.
- Risk caps remain unchanged unless separately approved.

## Hard No-Go Items

Do not run:

```text
launchctl
restart scripts
live mode manually
broker order commands
authenticated broker account/order APIs
```

Do not edit `.env`, risk caps, strategy logic, Coinbase `dead_chop`, live
symbols, frequency, exposure caps, or notional sizing as part of evaluation.
