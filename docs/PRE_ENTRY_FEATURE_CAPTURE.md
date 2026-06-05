# P2-026A Pre-Entry Feature Capture

`scripts/coinbase_historical_signal_generator.py` now enriches each synthetic
cycle with pre-entry-only features so future offline diagnostics can test
implementable hypotheses without using post-entry outcomes.

This is offline diagnostic infrastructure only. It does not authorize live
filters, stop-loss exclusion, exit tuning, paper/live probes, restart, scaling,
or any live config/risk/runtime change.

## Why This Exists

P2-025Z proved that direct `exclude_stop_loss` is post-outcome leakage:
`stop-loss hit` is known only after entry. The result explained a loss cluster,
but it could not be used as a live pre-entry filter.

P2-026A adds richer features that are known at or before the entry candle, so
P2-026B can test whether any leak-free pre-entry bucket explains the stop-loss
cluster.

## Captured Fields

Each synthetic cycle now includes:

```text
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
order_book_spread_available=false
bid_ask_depth_available=false
order_book_features_missing_reason=OHLCV-only dataset
```

## Leakage Guards

The generator computes these fields from `bars[:entry_index + 1]` only.

Report-level guards:

```text
pre_entry_features_use_only_past_bars=true
no_exit_reason_in_pre_entry_features=true
no_future_path_in_pre_entry_features=true
```

The fields do not use exit price, exit reason, hold duration, future path, or
journal outcomes.

## Current Smoke Result

Expanded local OHLCV smoke remains:

```text
bars_scanned=43333
synthetic_cycles_count=91
baseline_gross=0.16536982
baseline_win_rate=0.505495
stop_loss_count=25
stop_loss_gross_total=-0.56473020
non_stop_loss_gross_total=0.73010002
```

The best enriched diagnostics were still not implementation candidates:

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
```

No enriched pre-entry candidate passed the strict gate.

## Still Unavailable From OHLCV

```text
order_book_spread
bid_ask_depth
maker_taker_fee_estimate
order_book_liquidity_bucket
queue_position
real fill quality
```

## Verdict

```text
any_enriched_pre_entry_candidate_found=false
best_enriched_pre_entry_candidate=null
implementation_authorized=false
paper_probe_authorized=false
live_probe_authorized=false
scaling_authorized=false
```

Next recommended action: P2-026B should use the enriched fields for offline
hypothesis testing only. Do not implement stop-loss exclusion, tune exits, run
paper/live probes, restart, or scale.
