# P2-028 Redesigned Entry Validation Harness

`scripts/coinbase_redesigned_entry_validation_harness.py` evaluates offline
redesigned-entry concepts against existing synthetic cycles and pre-entry
features. It does not change live strategy logic, live filters, stop-loss
exclusion, exit tuning, paper/live probes, restart, scaling, or live
config/risk/runtime state.

## Why This Exists

P2-026D falsified the prior P2-026B candidate:

```text
exclude_pre_entry_return_3_above_p80_0.011338
```

P2-027 then showed the project should pivot from filter mining to strategy and
signal-quality redesign:

```text
bars_scanned=84627
synthetic_cycles_count=205
gross_total=-0.05366106
median_gross=-0.00465279
win_rate=0.424390
timeout_rate=0.439024
stop_loss_gross=-1.65123301
worst_pair=ALGO/USD|momentum_breakout
```

P2-028 creates the first offline harness for testing redesigned-entry concepts.
It ranks candidates by deterministic full-sample diagnostics while preserving a
hard separation between "worth holdout validation" and "safe to implement."

## Baseline

```text
sample_size=205
gross_total=-0.05366106
avg_gross=-0.00026176
median_gross=-0.00465279
win_rate=0.424390
timeout_rate=0.439024
stop_loss_rate=0.360976
stop_loss_gross=-1.65123301
```

## Candidate Families

P2-028 evaluates these offline candidate families:

```text
momentum_confirmation_redesign
mean_reversion_redesign
symbol_strategy_retirement_gating_diagnostics
regime_specific_entry_gating
volatility_aware_entry_gating
liquidity_aware_entry_gating
session_time_of_day_entry_gating
confidence_threshold_diagnostics
timeout_risk_reduction_diagnostics
stop_loss_risk_reduction_diagnostics
```

All candidates use only pre-entry or at-entry fields. Post-outcome fields such
as exit reason, exit price, realized P/L, and hold duration are not valid inputs.

## Status Logic

Candidate status is deterministic:

```text
rejected = sample too small, material gross degradation, weak win rate, or leakage risk
diagnostic_only = useful for understanding contribution but not actionable
promising_needs_holdout = full-sample improvement without enough stability proof
validation_ready = strict full-sample and stability gates pass
```

`validation_ready` means ready for independent holdout validation. It does not
authorize live implementation, paper probes, live probes, scaling, threshold
changes, or exit tuning.

## Current Result

```text
candidate_count=12
validation_ready_count=1
promising_needs_holdout_count=0
diagnostic_only_count=2
rejected_count=9
```

The only current `validation_ready` row is:

```text
candidate_name=session_avoid_06_17_utc
family=session_time_of_day_entry_gating
sample_size=90
trades_removed=115
gross_total=0.50626670
avg_gross=0.00562519
median_gross=0.00401496
win_rate=0.533333
timeout_rate=0.422222
stop_loss_rate=0.288889
gross_delta_vs_baseline=0.55992776
required_next_validation=independent_holdout_validation_required_before_any_implementation_proposal
```

This candidate exists because P2-027 identified 06-11 and 12-17 UTC as weak
session clusters. It must be validated independently before any implementation
proposal.

## Rejected And Diagnostic Rows

Rejected rows mostly improved gross but failed the win-rate gate:

```text
momentum_confirmation_keep_positive_3_and_6_bar rejected win_rate weak
momentum_confirmation_keep_positive_12_bar rejected win_rate weak
volatility_avoid_mid_high_bucket rejected win_rate weak
liquidity_avoid_elevated_volume_bucket rejected win_rate weak
confidence_keep_085_or_higher rejected win_rate weak
stop_loss_risk_avoid_high_volatility_bucket rejected win_rate weak
timeout_risk_avoid_timeout_heavy_sessions rejected gross worsens materially, win_rate weak
```

Diagnostic-only rows:

```text
diagnostic_retire_mean_reversion
diagnostic_retire_algo_momentum_pair
```

Those rows estimate contribution only. They are not live gating proposals.

## Reduction Diagnostics

Best timeout-rate reduction:

```text
confidence_keep_085_or_higher timeout_rate_delta_vs_baseline=0.019134 status=rejected
session_avoid_06_17_utc timeout_rate_delta_vs_baseline=0.016802 status=validation_ready
```

Best stop-loss-rate reduction:

```text
diagnostic_retire_algo_momentum_pair stop_loss_rate_delta_vs_baseline=0.108229 status=diagnostic_only
session_avoid_06_17_utc stop_loss_rate_delta_vs_baseline=0.072087 status=validation_ready
```

## Recommended P2-029

P2-029 should run independent holdout validation for redesigned-entry candidates,
starting with `session_avoid_06_17_utc`, using:

```text
independent April window
chronological folds
symbol and symbol_strategy breakdowns
gross, median, and win-rate gates
timeout and stop-loss reduction checks
gross-to-net realism after stable gross edge exists
```

P2-029 must not implement a live filter or strategy change. It should decide
whether `session_avoid_06_17_utc` survives holdout or is another overfit.

## Authorization Status

```text
implementation_proposal_authorized=false
implementation_authorized=false
paper_probe_authorized=false
live_probe_authorized=false
scaling_authorized=false
```

No filters were implemented. No stop-loss exclusion was implemented. No
strategy thresholds, live strategy, config, risk, runtime, price-path logger,
LaunchAgent, or launchd state changed.
