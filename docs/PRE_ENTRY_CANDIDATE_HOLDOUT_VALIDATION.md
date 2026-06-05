# P2-026C Pre-Entry Candidate Holdout Validation

`scripts/coinbase_pre_entry_candidate_holdout_validation.py` validates the
fixed P2-026B candidate across offline holdout, folds, symbols, strategies, and
threshold sensitivity.

This is diagnostic-only. It does not implement a live filter, stop-loss
exclusion, exit tuning, paper/live probes, restart, scaling, or live
config/risk/runtime changes.

## Why This Exists

P2-026B found the first strict-gate offline candidate:

```text
rule_name=exclude_pre_entry_return_3_above_p80_0.011338
input_field=pre_entry_return_3
operator=>
threshold=0.011338
action=exclude_trade
```

That candidate was selected from 172 tested hypotheses on the same 91-cycle
synthetic sample. P2-026C tests whether the fixed rule survives out-of-sample
style checks without re-optimizing the threshold.

## Source Summary

```text
bars_scanned=43333
synthetic_cycles_count=91
baseline_gross=0.16536982
baseline_win_rate=0.505495
baseline_stop_loss_count=25
```

Leakage guards remain true:

```text
no_future_bars_for_signal=true
exit_after_entry_only=true
no_journal_exit_leakage=true
pre_entry_features_use_only_past_bars=true
no_exit_reason_in_pre_entry_features=true
no_future_path_in_pre_entry_features=true
```

## Full Sample

The full sample reproduces P2-026B:

```text
sample_size_before=91
sample_size_after=73
trades_removed=18
percent_trades_removed=0.197802
gross_before=0.16536982
gross_after=0.24400517
gross_delta=0.07863535
win_rate_after=0.534247
stop_loss_rate_before=0.274725
stop_loss_rate_after=0.219178
passes_gate=true
```

## Chronological Holdout

The fixed threshold does not pass the final 30% holdout gate:

```text
sample_size_before=27
sample_size_after=17
trades_removed=10
percent_trades_removed=0.370370
gross_before=-0.07412437
gross_after=-0.00071057
gross_delta=0.07341380
avg_gross_after=-0.00004180
median_gross_after=0E-8
win_rate_after=0.470588
stop_loss_rate_before=0.407407
stop_loss_rate_after=0.294118
passes_gate=false
failed_gates=sample_size_after < 20, avg_gross_after <= 0, win_rate_after < 0.50, sample_size_after < 30 preferred, data_quality_warning
```

The rule improves gross in the holdout, but the remaining holdout sample is too
small and still not net positive on average.

## Rolling Folds

```text
fold_1 gross_delta=0E-8 passes_gate=false
fold_2 gross_delta=-0.02834367 passes_gate=false
fold_3 gross_delta=0.03356522 passes_gate=false
fold_4 gross_delta=0.07341380 passes_gate=false
```

Two folds have positive gross deltas, but no fold passes the full gate. Later
folds are too small after filtering, and fold 4 removes more than 40% of trades.

## Symbol And Strategy Stability

Symbol results:

```text
ADA/USD gross_delta=0.00792707 passes_gate=false
ALGO/USD gross_delta=0.04859246 passes_gate=true data_quality_warning=true
BTC/USD gross_delta=0E-8 passes_gate=false
ETH/USD gross_delta=0E-8 passes_gate=false
SOL/USD gross_delta=0.02211582 passes_gate=false
```

Strategy results:

```text
mean_reversion gross_delta=0E-8 passes_gate=false
momentum_breakout gross_delta=0.07863535 passes_gate=true
```

The candidate does not depend entirely on ALGO/USD, but the positive strategy
evidence is concentrated in `momentum_breakout`.

## Threshold Sensitivity

```text
0.006000 gross_delta=-0.13256894 passes_gate=false
0.008000 gross_delta=-0.20194124 passes_gate=false
0.010000 gross_delta=-0.10946439 passes_gate=false
0.011338 gross_delta=0.07863535 passes_gate=true
0.012000 gross_delta=0.09994376 passes_gate=true
0.014000 gross_delta=0.05819975 passes_gate=true data_quality_warning=true
0.016000 gross_delta=0.06736843 passes_gate=true data_quality_warning=true
```

The effect is not only present at the exact selected threshold, but lower
thresholds fail badly. This reduces exact-threshold concern while preserving a
broader regime-selection concern.

## Percentile Sensitivity

Percentile sensitivity recomputes full-sample thresholds, so it is diagnostic
only and not holdout-safe:

```text
p70 threshold=0.010148 gross_delta=-0.16347677 passes_gate=false
p75 threshold=0.010595 gross_delta=-0.04498615 passes_gate=false
p80 threshold=0.011338 gross_delta=0.07863535 passes_gate=true
p85 threshold=0.013057 gross_delta=0.04715637 passes_gate=true
p90 threshold=0.013664 gross_delta=0.05819975 passes_gate=true
```

## Verdict

```text
verdict=unstable_or_overfit
holdout_validated=false
provisionally_stable=false
likely_overfit=true
implementation_proposal_authorized=false
implementation_authorized=false
paper_probe_authorized=false
live_probe_authorized=false
scaling_authorized=false
```

P2-026C does not authorize a live filter proposal. The next useful work is a
larger or independent offline stability pass before any implementation proposal.
