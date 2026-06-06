# P2-029 Redesigned Entry Independent Holdout Validation

`scripts/coinbase_redesigned_entry_independent_holdout_validation.py` tests the
fixed `session_avoid_06_17_utc` candidate using offline synthetic cycles only.
It does not change live strategy logic, filters, thresholds, exits, config,
risk, runtime, probes, scaling, launchd, or the price-path logger.

## Why P2-029 Exists

P2-028 found one `validation_ready` redesigned-entry candidate:

```text
candidate=session_avoid_06_17_utc
gross_delta_vs_baseline=0.55992776
win_rate=0.533333
sample_size=90
```

`validation_ready` meant ready for independent holdout validation only. It was
not implementation approval.

P2-029 freezes the approved candidate definition to exact UTC entry hours
`[6, 17]`. It does not search for replacement hours on the holdout data.

## Definition Caveat

P2-028's harness used the same candidate name for a broader rule that excluded
the complete `06-11` and `12-17` session buckets. P2-029 follows the approved
exact-hour contract:

```text
excluded_utc_hours=[6,17]
threshold_reoptimized=false
pre_entry_only=true
leakage_risk=false
```

The P2-028 prior metrics are preserved for context, but they are not directly
comparable to the narrower exact-hour rule.

## Data

```text
bars_scanned=84627
synthetic_cycles_count=205
symbols=ADA/USD, ALGO/USD, BTC/USD, ETH/USD, SOL/USD
strategies=mean_reversion, momentum_breakout
```

`data/offline_ohlcv/` remains untracked local working data.

## Full Sample

```text
sample_size_before=205
sample_size_after=180
trades_removed=25
trade_removal_rate=0.121951
gross_before=-0.05366106
gross_after=-0.00525014
gross_delta=0.04841092
avg_gross_after=-0.00002917
median_gross_after=-0.00465740
win_rate_after=0.427778
timeout_rate_before=0.439024
timeout_rate_after=0.444444
stop_loss_rate_before=0.360976
stop_loss_rate_after=0.355556
passes_gate=false
```

Gross improves, but the retained sample remains negative on average and at the
median, wins below 50%, and has a slightly worse timeout rate.

## Chronological Holdout

```text
sample_size_before=61
sample_size_after=48
trades_removed=13
gross_before=-0.06639457
gross_after=-0.01401087
gross_delta=0.05238370
avg_gross_after=-0.00029189
median_gross_after=-0.00180332
win_rate_after=0.458333
timeout_rate_before=0.524590
timeout_rate_after=0.541667
stop_loss_rate_before=0.311475
stop_loss_rate_after=0.291667
passes_gate=false
```

The chronological holdout repeats the same failure pattern: improved gross is
not enough because the retained trades remain economically negative and
timeout concentration worsens.

## Recent Window

```text
window_start_utc=2026-05-04T17:10:00+00:00
window_end_utc=2026-06-02T17:10:00+00:00
sample_size_before=82
sample_size_after=67
gross_delta=0.02635429
avg_gross_after=0.00213422
median_gross_after=0.00245783
win_rate_after=0.507463
timeout_rate_before=0.524390
timeout_rate_after=0.537313
stop_loss_rate_before=0.268293
stop_loss_rate_after=0.253731
passes_gate=false
```

The recent slice is the strongest result, but it still fails because timeout
rate worsens. This slice was part of the overall data corpus and is not a
newly acquired pristine unseen sample.

## Rolling And Group Stability

All four rolling folds fail the complete gate:

```text
fold_1 gross_delta=0.06211697 win_rate_after=0.444444
fold_2 gross_delta=-0.01242649 win_rate_after=0.306122
fold_3 gross_delta=-0.06974177 win_rate_after=0.531915
fold_4 gross_delta=0.06846221 win_rate_after=0.435897
```

Positive-effect stability:

```text
rolling_folds=1/4
symbols=1/5
strategies=0/2
symbol_strategies=2/8
sessions=1/4
```

The rule is not stable across folds, symbols, strategies, pairs, or sessions.

## Timeout And Stop-Loss Diagnostics

Stop-loss rate improves slightly in all three headline slices:

```text
full_sample_reduction=0.005420
chronological_holdout_reduction=0.019808
recent_window_reduction=0.014562
```

Timeout rate worsens in all three:

```text
full_sample_reduction=-0.005420
chronological_holdout_reduction=-0.017077
recent_window_reduction=-0.012923
```

This does not justify stop-loss exclusion or exit tuning. Both remain
unauthorized.

## Sensitivity

Predefined sensitivity rows do not re-optimize the candidate:

```text
hour_06_only gross_delta=-0.02090578 passes=false
hour_17_only gross_delta=0.06931670 passes=false
adjacent_plus_minus_one gross_delta=-0.05857598 passes=false
broad_06_through_17_context gross_delta=0.55992776 passes=false
```

Only `[6,17]` is the selected candidate. Other rows are diagnostics and cannot
replace it.

## Verdict

```text
verdict=falsified
independently_validated=false
falsified=true
likely_overfit=true
implementation_proposal_authorized=false
implementation_authorized=false
paper_probe_authorized=false
live_probe_authorized=false
scaling_authorized=false
```

The exact-hour candidate does not survive independent holdout validation. No
live or paper implementation proposal is authorized.

## Recommended P2-030

P2-030 should remain offline. It should reconcile the candidate-definition
mismatch, then return to entry redesign with a fixed pre-entry contract and a
genuinely untouched validation sample. It must not implement the broad P2-028
session exclusion, exact-hour exclusion, stop-loss exclusion, exit tuning,
paper/live probes, or scaling.

