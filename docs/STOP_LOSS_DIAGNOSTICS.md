# P2-025Z Stop-Loss Diagnostics

`scripts/coinbase_stop_loss_diagnostics_report.py` explains the P2-025Y
`exclude_stop_loss` result and checks whether the stop-loss cycles have
identifiable pre-entry features that could support a future implementable
filter.

This is an offline-only diagnostic. It does not implement filters, change live
strategy logic, tune exits, modify risk/config/runtime state, authorize
paper/live probes, or authorize scaling.

## Why This Exists

P2-025Y found that removing stop-loss outcomes from the synthetic cycle set
improved gross from `0.16536982` to `0.73010002`.

That is promising but dangerous: `stop-loss hit` is an exit outcome known only
after entry. It cannot be used directly as a live pre-entry filter without
future-path leakage.

P2-025Z separates:

- post-outcome diagnostics, useful for explaining the sample
- pre-entry hypotheses, potentially implementable only if they use information
  available before entry

## Source Summary

Current expanded synthetic source:

```text
bars_scanned=43333
synthetic_cycles_count=91
baseline_gross=0.16536982
baseline_win_rate=0.505495
```

Leakage guards:

```text
no_future_bars_for_signal=true
exit_after_entry_only=true
no_journal_exit_leakage=true
```

## Stop-Loss Summary

```text
stop_loss_count=25
non_stop_loss_count=66
stop_loss_gross_total=-0.56473020
non_stop_loss_gross_total=0.73010002
stop_loss_avg_gross=-0.02258921
stop_loss_median_gross=-0.02205796
```

Stop-loss symbols:

```text
ALGO/USD
ETH/USD
SOL/USD
```

Stop-loss strategies:

```text
mean_reversion
momentum_breakout
```

## Concentration Findings

By symbol:

```text
ALGO/USD stop_loss_count=19/54 stop_loss_rate=0.351852 gross=-0.43436161 total_gross=0.20727475
ETH/USD  stop_loss_count=3/8   stop_loss_rate=0.375000 gross=-0.06889499 total_gross=-0.04571145
SOL/USD  stop_loss_count=3/16  stop_loss_rate=0.187500 gross=-0.06147360 total_gross=-0.01488569
ADA/USD  stop_loss_count=0/7
BTC/USD  stop_loss_count=0/6
```

By strategy:

```text
momentum_breakout stop_loss_count=23/83 stop_loss_rate=0.277108 gross=-0.52183851
mean_reversion    stop_loss_count=2/8   stop_loss_rate=0.250000 gross=-0.04289169
```

By symbol and strategy:

```text
ALGO/USD|momentum_breakout stop_loss_count=19/54 stop_loss_rate=0.351852 gross=-0.43436161
ETH/USD|mean_reversion    stop_loss_count=2/3   stop_loss_rate=0.666667 gross=-0.04289169
ETH/USD|momentum_breakout stop_loss_count=1/5   stop_loss_rate=0.200000 gross=-0.02600330
SOL/USD|momentum_breakout stop_loss_count=3/16  stop_loss_rate=0.187500 gross=-0.06147360
```

By time bucket:

```text
12-17 UTC stop_loss_count=11/34 stop_loss_rate=0.323529 total_gross=-0.12932986
06-11 UTC stop_loss_count=6/18  stop_loss_rate=0.333333 total_gross=-0.05156798
00-05 UTC stop_loss_count=5/25  stop_loss_rate=0.200000 total_gross=0.26225772
18-23 UTC stop_loss_count=3/14  stop_loss_rate=0.214286 total_gross=0.08400994
```

By day bucket:

```text
Sat stop_loss_count=6/11 stop_loss_rate=0.545455 total_gross=-0.11448840
Sun stop_loss_count=4/12 stop_loss_rate=0.333333 total_gross=-0.04594804
Mon stop_loss_count=4/13 stop_loss_rate=0.307692 total_gross=0.01073661
```

## Pre-Entry Feature Availability

Available in current P2-026A synthetic cycles:

```text
symbol
strategy
regime
confidence
entry_spread_pct
entry_time
notional
entry_basis
source_ohlcv_file
pre_entry_return_1
pre_entry_return_3
pre_entry_return_6
pre_entry_return_12
pre_entry_volatility_6
pre_entry_volatility_12
pre_entry_atr_14
pre_entry_range_pct_1
pre_entry_range_pct_3
pre_entry_volume
pre_entry_volume_sma_12
pre_entry_volume_ratio_12
pre_entry_liquidity_bucket
pre_entry_volatility_bucket
pre_entry_momentum_bucket
pre_entry_atr_bucket
pre_entry_hour_utc
pre_entry_day_of_week_utc
pre_entry_session_bucket
pre_entry_regime
pre_entry_confidence
pre_entry_symbol_strategy_key
```

Still unavailable from OHLCV-only data:

```text
order_book_spread
bid_ask_depth
maker_taker_fee_estimate
order_book_liquidity_bucket
```

Current enriched fields are enough for exploratory offline diagnostics, but not
enough for live filter implementation.

## Pre-Entry Hypothesis Results

The direct `exclude_stop_loss` diagnostic:

```text
sample_size_remaining=66
stop_loss_cycles_removed=25
gross_after_filter=0.73010002
gross_delta_vs_baseline=0.56473020
pre_entry_implementable=false
leakage_risk=true
implementation_candidate=false
```

Top pre-entry hypotheses:

```text
avoid_entry_hour_bucket_12-17
sample_size_remaining=57
stop_loss_cycles_removed=11
percent_stop_loss_removed=0.440000
gross_after_filter=0.29469968
gross_delta_vs_baseline=0.12932986
implementation_candidate=false

avoid_entry_day_bucket_Sat
sample_size_remaining=80
stop_loss_cycles_removed=6
percent_stop_loss_removed=0.240000
gross_after_filter=0.27985822
gross_delta_vs_baseline=0.11448840
implementation_candidate=false

avoid_entry_hour_bucket_06-11
sample_size_remaining=73
stop_loss_cycles_removed=6
percent_stop_loss_removed=0.240000
gross_after_filter=0.21693780
gross_delta_vs_baseline=0.05156798
implementation_candidate=false

avoid_symbol_ETH/USD
sample_size_remaining=83
stop_loss_cycles_removed=3
percent_stop_loss_removed=0.120000
gross_after_filter=0.21108127
gross_delta_vs_baseline=0.04571145
implementation_candidate=false
```

No pre-entry rule removed at least half of stop-loss cycles while keeping at
least 50 cycles. No pre-entry rule removed at least half of stop-loss cycles
while keeping at least 30 cycles.

P2-026A enriched pre-entry hypothesis highlights:

```text
avoid_pre_entry_hour_utc_bucket_12-17
sample_size_remaining=57
stop_loss_cycles_removed=11
percent_stop_loss_removed=0.440000
gross_after_filter=0.29469968
implementation_candidate=false

avoid_pre_entry_session_bucket_12-17
sample_size_remaining=57
stop_loss_cycles_removed=11
percent_stop_loss_removed=0.440000
gross_after_filter=0.29469968
implementation_candidate=false

avoid_pre_entry_day_of_week_utc_Sat
sample_size_remaining=80
stop_loss_cycles_removed=6
percent_stop_loss_removed=0.240000
gross_after_filter=0.27985822
implementation_candidate=false

avoid_pre_entry_volatility_12_bucket_0.5%-1%
sample_size_remaining=85
stop_loss_cycles_removed=4
percent_stop_loss_removed=0.160000
gross_after_filter=0.27204217
implementation_candidate=false
```

No enriched pre-entry hypothesis passed the strict implementation-candidate
gate.

## Interpretation

The stop-loss result is real as an offline post-outcome diagnostic, but not yet
implementable as a live pre-entry filter.

Current evidence does not prove lower pre-entry confidence caused stop losses:
stop-loss cycles had slightly higher average confidence than non-stop-loss
cycles in this synthetic sample. Current modeled spread is `0` for every cycle,
so spread does not explain the cluster. Volatility and recent momentum are not
available in the current cycle schema.

Most likely current explanation:

```text
post_entry_path_and_normal_strategy_risk_or_exit_policy
```

This may include avoidable bad entries, exit-policy artifacts, or synthetic
close-scan modeling artifacts, but P2-025Z cannot separate those cleanly without
richer pre-entry and post-entry path diagnostics.

## Verdict

```text
stop_loss_exclusion_implementable_as_is=false
any_pre_entry_candidate_found=false
best_pre_entry_candidate=null
any_enriched_pre_entry_candidate_found=false
best_enriched_pre_entry_candidate=null
candidate_requires_more_data=true
implementation_authorized=false
paper_probe_authorized=false
live_probe_authorized=false
scaling_authorized=false
```

## Next Step

Add richer pre-entry feature capture to synthetic cycles and rerun diagnostics
before any implementation proposal.

Do not implement stop-loss exclusion yet. Do not tune exits. Do not run
paper/live probes. Do not restart. Do not scale.
