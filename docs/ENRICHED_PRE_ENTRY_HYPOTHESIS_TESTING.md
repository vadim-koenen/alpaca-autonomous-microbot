# P2-026B Enriched Pre-Entry Hypothesis Testing

`scripts/coinbase_enriched_pre_entry_hypothesis_report.py` evaluates
offline-only, analysis-only pre-entry hypotheses against the P2-026A enriched
synthetic cycles.

This does not implement live filters, stop-loss exclusion, exit tuning,
maker/post-only behavior, paper/live probes, restart, scaling, or live
config/risk/runtime changes.

## Why This Exists

P2-025Z showed that direct `exclude_stop_loss` is post-outcome leakage: a
stop-loss result is known only after entry. P2-026A then added richer
pre-entry-only features to the synthetic cycle generator.

P2-026B uses those fields to test whether any leak-free pre-entry condition can
explain stop-loss-prone trades while preserving enough sample size and gross
quality to justify more offline review.

## Source Summary

Current expanded synthetic source:

```text
bars_scanned=43333
synthetic_cycles_count=91
baseline_gross=0.16536982
baseline_win_rate=0.505495
baseline_stop_loss_count=25
baseline_stop_loss_rate=0.274725
```

Leakage guards:

```text
no_future_bars_for_signal=true
exit_after_entry_only=true
no_journal_exit_leakage=true
pre_entry_features_use_only_past_bars=true
no_exit_reason_in_pre_entry_features=true
no_future_path_in_pre_entry_features=true
```

## Hypothesis Families

The report tests:

- single-field exclusions across symbol, strategy, regime, confidence,
  momentum, volatility, ATR, liquidity, volume-ratio, hour, day, and session
  buckets
- numeric thresholds across volatility, ATR, recent return, volume ratio, and
  range percentiles
- combination hypotheses such as symbol/strategy plus volatility, momentum,
  ATR, or liquidity buckets
- focused ALGO/USD momentum-breakout hypotheses
- strategy-level hypotheses for momentum-breakout high volatility, adverse
  momentum, and low liquidity
- leakage controls that prove `exit_reason` is rejected as a filter input

Stop-loss outcome is used only as an evaluation target.

## Current Findings

Current smoke result:

```text
hypotheses_evaluated=172
validated_candidates=1
provisional_candidates=8
diagnostic_only_candidates=20
likely_overfit_count=69
rejected_candidates_count=38
```

Best strict-gate candidate:

```text
hypothesis_name=exclude_pre_entry_return_3_above_p80_0.011338
status=validated_candidate
sample_size_after=73
trades_removed=18
stop_loss_removed=9
percent_stop_loss_removed=0.360000
gross_after=0.24400517
gross_delta=0.07863535
avg_gross_after=0.00334254
median_gross_after=0.00300440
win_rate_after=0.534247
stop_loss_rate_after=0.219178
```

Top diagnostic gross-delta rows remain useful but not sufficient by themselves:

```text
exclude_pre_entry_hour_utc_bucket_12-17 gross_delta=0.12932986 status=diagnostic_only
exclude_pre_entry_session_bucket_12-17 gross_delta=0.12932986 status=diagnostic_only
exclude_pre_entry_day_of_week_utc_Sat gross_delta=0.11448840 status=diagnostic_only
```

The deliberate leakage-control row:

```text
reject_exit_reason_stop_loss_as_input
leakage_risk=true
pre_entry_only=false
status=rejected
```

## Limitations

- Synthetic cycles are offline candidates, not live fills.
- Multiple testing can overfit a 91-cycle sample.
- OHLCV lacks order-book spread, depth, queue-position, and fee-aware liquidity
  fields.
- ALGO/USD still has the local data-quality caveat from the expanded OHLCV
  rerun.
- A validated offline hypothesis is not predictive live evidence by itself.

## Verdict

```text
any_validated_candidate_found=true
any_provisional_candidate_found=true
implementation_authorized=false
paper_probe_authorized=false
live_probe_authorized=false
scaling_authorized=false
```

Next recommended action: test stability of the validated/provisional/diagnostic
pre-entry hypotheses on a larger or independently sliced offline sample. Do not
implement live filters, tune exits, run probes, restart, or scale from this
report alone.
