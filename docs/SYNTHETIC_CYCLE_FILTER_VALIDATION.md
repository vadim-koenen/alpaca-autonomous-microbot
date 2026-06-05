# P2-025X Synthetic Cycle Filter Validation

`scripts/coinbase_synthetic_cycle_filter_validation.py` validates candidate
selectivity filters against the P2-025W synthetic cycle set. It is an
offline-only diagnostic. It does not implement live filters, change strategy
thresholds, tune exits, alter risk/config/runtime state, place orders, or
authorize paper/live probes.

## Why This Exists

P2-025W unlocked synthetic historical cycles generated from local OHLCV through
the offline strategy adapter. P2-025X uses that cycle set to test whether the
candidate filters from P2-025S/P2-025T survive a broader generated sample.

This is still not profit-ready evidence. Synthetic cycles are analysis
artifacts, not broker-backed trades or live implementation approval.

## Source Generator Summary

Current P2-025W source generator result:

```text
symbols_scanned=ADA/USD, ALGO/USD, BTC/USD, ETH/USD, SOL/USD
bars_scanned=9782
synthetic_cycles_count=32
baseline_gross=-0.05962834
baseline_win_rate=0.4375
```

Leakage guards:

```text
no_future_bars_for_signal=true
exit_after_entry_only=true
no_journal_exit_leakage=true
```

## Validation Gates

A filter is fully validated only if all strict gates pass:

```text
sample_size >= 50
synthetic_gross_total > 0
avg_gross > 0
median_gross >= 0
win_rate >= 0.45
gains are not dominated by one winner
worst-5 losses do not hide broad negative edge
no forward-looking leakage
no journal-exit leakage
no live strategy/config changes
```

If sample size is 30-49, a scenario can only be labeled
`provisional_positive`, and only if all economic and concentration gates pass.
If sample size is below 30, it is weak and cannot validate a filter.

## Current Scenario Results

| Scenario | N | Gross | Win Rate | Status | Why |
| --- | ---: | ---: | ---: | --- | --- |
| `baseline_all_synthetic_cycles` | 32 | -0.05962834 | 0.4375 | rejected | Gross, average, median, and win-rate gates fail; sample is below 50. |
| `exclude_stop_loss` | 20 | +0.22750788 | 0.7000 | rejected | Positive economics, but sample is below the 30-cycle minimum. |
| `exclude_strategy_mean_reversion` | 28 | -0.05903710 | 0.4286 | rejected | Gross remains negative and sample is below 30. |
| `exclude_symbol_ETH/USD` | 28 | -0.04587091 | 0.4643 | rejected | Gross remains negative and sample is below 30. |
| `exclude_symbol_ADA/USD` | 32 | -0.05962834 | 0.4375 | rejected | No improvement; gross remains negative. |
| `exclude_symbol_ALGO/USD` | 9 | +0.01172133 | 0.5556 | rejected | Positive but tiny weak sample with concentration warning. |
| `exclude_symbol_BTC/USD` | 30 | -0.06419019 | 0.4333 | rejected | Gross and win rate get worse. |
| `exclude_symbol_SOL/USD` | 29 | -0.08054525 | 0.3793 | rejected | Gross and win rate get worse; sample is below 30. |
| `dynamic_exclude_exit_reason_stop_loss` | 20 | +0.22750788 | 0.7000 | rejected | Same as stop-loss exclusion; below the 30-cycle minimum. |

No exploratory combination reached the minimum meaningful 30-cycle sample size
on the current generated dataset, so combinations are not presented as
actionable.

## Verdict

```text
validated_filters=[]
provisional_positive_filters=[]
any_filter_validated=false
any_filter_provisionally_positive=false
implementation_authorized=false
paper_probe_authorized=false
live_probe_authorized=false
scaling_authorized=false
```

## Interpretation

ALGO exclusion improves gross from `-0.05962834` to `+0.01172133`, but it leaves
only 9 cycles and triggers concentration risk. It is rejected.

ETH exclusion improves gross from `-0.05962834` to `-0.04587091`, but remains
negative and leaves only 28 cycles. It is rejected.

Stop-loss exclusion is the strongest rejected filter by gross delta
(`+0.28713622`), but leaves only 20 cycles. It is not validated and not
provisional-positive because it fails the 30-cycle minimum.

Symbol selectivity does not create a validated or provisional-positive edge in
the current sample.

## Next Data Needed

The current synthetic sample is still small at 32 cycles. The next safe step is
to expand offline synthetic sample size before any live implementation proposal.

Recommended next action:

```text
Increase local OHLCV coverage and rerun synthetic-cycle generation plus P2-025X validation.
```

Do not implement filters yet. Do not tune exits. Do not run paper/live probes.
Do not restart. Do not scale.

## Preserved Safety

```text
trade_permission=none
implementation_authorized=false
paper_probe_authorized=false
live_probe_authorized=false
scaling_authorized=false
scaling_allowed=false
risk_increase=not_approved
```
