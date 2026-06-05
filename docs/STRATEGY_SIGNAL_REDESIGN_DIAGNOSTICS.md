# P2-027 Strategy Signal Redesign Diagnostics

`scripts/coinbase_strategy_signal_redesign_diagnostics.py` is an offline
diagnostic report for pivoting from filter mining to strategy/signal redesign.
It does not implement live strategy logic, filters, stop-loss exclusion, exit
tuning, paper/live probes, restart, scaling, or live config/risk/runtime
changes.

## Why This Exists

P2-026D independently falsified the P2-026B candidate:

```text
exclude_pre_entry_return_3_above_p80_0.011338
```

P2-026D result:

```text
verdict=falsified
full_sample_passes_gate=false
independent_window_passes_gate=false
chronological_holdout_passes_gate=false
implementation_proposal_authorized=false
implementation_authorized=false
paper_probe_authorized=false
live_probe_authorized=false
scaling_authorized=false
```

That means the project should stop trying to implement or slightly re-mine that
filter. The next useful work is explaining why the existing strategy entries
are weak and designing offline validation for better entry logic.

## Current Baseline

```text
bars_scanned=84627
synthetic_cycles_count=205
gross_total=-0.05366106
avg_gross=-0.00026176
median_gross=-0.00465279
win_rate=0.424390
winners=87
losers=115
```

The baseline is not stable enough for paper/live probes or scaling. It is
gross-negative, median-negative, and wins less than half the time before fees.

## Exit Reason Summary

```text
timeout cycles=90 gross_total=0.19508569 win_rate=0.511111 timeout_rate=0.439024
stop_loss cycles=74 gross_total=-1.65123301 win_rate=0.000000 stop_loss_rate=0.360976
take_profit cycles=41 gross_total=1.40248626 win_rate=1.000000
```

Stop-loss cycles are the largest loss cluster. Timeout exits are frequent enough
to require root-cause analysis before any live exit tuning.

## Leading Weakness Clusters

Worst symbols:

```text
ALGO/USD cycles=114 gross_total=-0.10131626 win_rate=0.403509 stop_loss_rate=0.447368
ETH/USD cycles=19 gross_total=-0.06064945 win_rate=0.315789 stop_loss_rate=0.368421
```

Worst strategies:

```text
mean_reversion cycles=9 gross_total=-0.04745437 win_rate=0.444444 timeout_rate=0.666667
momentum_breakout cycles=196 gross_total=-0.00620669 win_rate=0.423469 stop_loss_rate=0.362245
```

Worst symbol/strategy pairs:

```text
ALGO/USD|momentum_breakout cycles=114 gross_total=-0.10131626 win_rate=0.403509 stop_loss_rate=0.447368
ETH/USD|mean_reversion cycles=4 gross_total=-0.04853258 win_rate=0.250000 stop_loss_rate=0.750000
ETH/USD|momentum_breakout cycles=15 gross_total=-0.01211687 win_rate=0.333333 timeout_rate=0.600000
```

Largest loss clusters:

```text
exit_reason_summary:stop_loss gross_total=-1.65123301 cycles=74
session_bucket_performance:12-17 gross_total=-0.28392201 cycles=74
session_bucket_performance:06-11 gross_total=-0.27600575 cycles=41
symbol_strategy_performance:ALGO/USD|momentum_breakout gross_total=-0.10131626 cycles=114
volatility_bucket_performance:0.5%-1% gross_total=-0.08866286 cycles=19
liquidity_bucket_performance:elevated_1.1x_1.5x gross_total=-0.07918262 cycles=25
```

These are diagnostic clusters, not live filters. The ALGO/USD April coverage
still has a gap caveat from the local OHLCV expansion.

## Redesign Roadmap

P2-027 ranks redesign directions rather than selecting a live implementation
winner:

```text
1 retire_or_redesign_weak_strategy_modules
2 symbol_strategy_gating_based_on_independent_evidence
3 momentum_breakout_redesign_or_retirement
4 timeout_exit_root_cause_analysis
5 entry_confirmation_redesign_pre_entry_only
6 regime_specific_gating_or_signal_design
7 volatility_liquidity_session_diagnostics_only
8 gross_to_net_fee_slippage_realism_after_stable_gross_edge
```

The strongest immediate message is not "add a filter"; it is "redesign and test
entry logic offline." The existing momentum-breakout path dominates entries but
is not producing stable gross edge. Mean reversion is smaller but also weak in
this expanded sample.

## Recommended P2-028 Target

P2-028 should build an offline redesigned-entry validation harness. It should
compare the current baseline with redesigned signal variants across:

```text
independent windows
chronological folds
symbol_strategy breakdowns
timeout root-cause labels
stop-loss concentration
gross/median/win-rate gates
```

P2-028 must not:

```text
implement the falsified P2-026B filter
change live strategy thresholds
tune live exits
run paper or live probes
scale
```

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
