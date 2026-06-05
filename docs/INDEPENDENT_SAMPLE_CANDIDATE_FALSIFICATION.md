# P2-026D Independent-Sample Candidate Falsification

`scripts/coinbase_independent_sample_candidate_falsification_report.py`
applies the fixed P2-026B/P2-026C candidate to an expanded offline sample and
an independent April 2026 OHLCV window without re-optimizing the threshold.

This is diagnostic-only. It does not implement a live filter, stop-loss
exclusion, exit tuning, paper/live probes, restart, scaling, or live
config/risk/runtime changes.

## Candidate Tested

```text
rule_name=exclude_pre_entry_return_3_above_p80_0.011338
input_field=pre_entry_return_3
operator=>
threshold=0.011338
action=exclude_trade
pre_entry_only=true
leakage_risk=false
```

The threshold remains fixed from P2-026B. P2-026D does not search for a better
threshold on the independent sample.

## Independent Data Added

Local untracked public OHLCV files were fetched for April 2026:

```text
ADA/USD 2026-04-01..2026-04-30 5m rows=8353 gaps=0 malformed=0
ALGO/USD 2026-04-01..2026-04-30 5m rows=7882 gaps=408 malformed=0
BTC/USD 2026-04-01..2026-04-30 5m rows=8353 gaps=0 malformed=0
ETH/USD 2026-04-01..2026-04-30 5m rows=8353 gaps=0 malformed=0
SOL/USD 2026-04-01..2026-04-30 5m rows=8353 gaps=0 malformed=0
```

`data/offline_ohlcv/` remains untracked local working data. ALGO/USD has a gap
caveat and should not be treated as clean continuous coverage.

## Expanded Synthetic Sample

```text
bars_scanned=84627
synthetic_cycles_count=205
baseline_gross=-0.05366106
baseline_win_rate=0.424390
baseline_stop_loss_count=74
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

## Expanded Full Sample Result

```text
sample_size_before=205
sample_size_after=146
trades_removed=59
percent_trades_removed=0.287805
gross_before=-0.05366106
gross_after=0.14410258
gross_delta=0.19776364
avg_gross_after=0.00098700
median_gross_after=-0.00137274
win_rate_after=0.452055
stop_loss_rate_before=0.360976
stop_loss_rate_after=0.287671
passes_gate=false
failed_gates=median_gross_after < 0, win_rate_after < 0.50
```

The rule improves gross on the expanded sample, but it still leaves negative
median gross and a sub-50% win rate.

## Independent April Window

```text
sample_size_before=114
sample_size_after=73
trades_removed=41
percent_trades_removed=0.359649
gross_before=-0.21903088
gross_after=-0.09990259
gross_delta=0.11912829
avg_gross_after=-0.00136853
median_gross_after=-0.00542005
win_rate_after=0.369863
stop_loss_rate_before=0.429825
stop_loss_rate_after=0.356164
passes_gate=false
failed_gates=avg_gross_after <= 0, median_gross_after < 0, win_rate_after < 0.50
```

The independent April window falsifies the candidate as an implementation
candidate. Gross improves, but the remaining trades are still economically
negative on average, negative at the median, and win well below 50%.

## Chronological Holdout

```text
sample_size_before=61
sample_size_after=43
trades_removed=18
percent_trades_removed=0.295082
gross_before=-0.06639457
gross_after=0.01224078
gross_delta=0.07863535
avg_gross_after=0.00028467
median_gross_after=-0.00146479
win_rate_after=0.465116
stop_loss_rate_before=0.311475
stop_loss_rate_after=0.232558
passes_gate=false
failed_gates=median_gross_after < 0, win_rate_after < 0.50
```

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

P2-026D falsifies the P2-026B candidate for implementation. It can remain useful
as diagnostic evidence that high short-term pre-entry returns are suspicious in
this sample, but it is not stable enough to become a live or paper filter.

## Next Step

Do not implement this filter. The next highest-ROI work is offline strategy
redesign or broader independent-sample falsification before any implementation
proposal, paper probe, live probe, restart, or scaling.
