# P2-025Y OHLCV Coverage Expansion Rerun

P2-025Y increased local offline OHLCV coverage and reran synthetic cycle
generation plus filter validation. This is an offline truth/diagnostic report
only. It does not implement filters, tune exits, change live strategy, alter
risk/config/runtime state, authorize paper/live probes, or authorize scaling.

## Safety Scope

Allowed network use was limited to unauthenticated public Coinbase candle
fetching through `scripts/coinbase_public_ohlcv_fetch.py`.

Preserved restrictions:

```text
trade_permission=none
implementation_authorized=false
paper_probe_authorized=false
live_probe_authorized=false
scaling_authorized=false
risk_increase=not_approved
no --live-read-only
no broker/trading endpoints
no .env/secrets reads
no orders/cancels/closes/modifications
no restart or launchctl
no live config/risk/symbol/threshold/runtime changes
data/offline_ohlcv/ remains untracked local working data
```

## New Offline Data Fetched

Fetched public 5-minute candles for:

```text
ADA/USD  2026-05-01 to 2026-05-25  rows=6834
ALGO/USD 2026-05-01 to 2026-05-25  rows=6214
BTC/USD  2026-05-01 to 2026-05-25  rows=6835
ETH/USD  2026-05-01 to 2026-05-25  rows=6834
SOL/USD  2026-05-01 to 2026-05-25  rows=6834
```

Generated local files:

```text
data/offline_ohlcv/coinbase/ADA-USD_5m_2026-05-01_2026-05-25.csv
data/offline_ohlcv/coinbase/ALGO-USD_5m_2026-05-01_2026-05-25.csv
data/offline_ohlcv/coinbase/BTC-USD_5m_2026-05-01_2026-05-25.csv
data/offline_ohlcv/coinbase/ETH-USD_5m_2026-05-01_2026-05-25.csv
data/offline_ohlcv/coinbase/SOL-USD_5m_2026-05-01_2026-05-25.csv
```

These files are not tracked by git.

## Data Quality Notes

Corrected validation found no malformed rows and no duplicate timestamps in the
new fetched files.

Gap counts:

```text
ADA/USD  gap_count=2
ALGO/USD gap_count=539
BTC/USD  gap_count=2
ETH/USD  gap_count=2
SOL/USD  gap_count=2
```

ALGO has many small missing-bar gaps in the early window and should be treated
as the main data-quality caveat. The other symbols share a large public-feed gap
around 2026-05-08 plus one smaller 10-minute gap.

## Before And After

Before expansion, P2-025X had:

```text
bars_scanned=9782
synthetic_cycles_count=32
baseline_gross=-0.05962834
baseline_win_rate=0.4375
validated_filters=[]
provisional_positive_filters=[]
sample_size_status=provisional
implementation_authorized=false
paper_probe_authorized=false
live_probe_authorized=false
scaling_authorized=false
```

After expansion:

```text
bars_scanned=43333
date_range=2026-05-01T00:00:00+00:00 to 2026-06-04T02:00:00+00:00
signal_candidates_count=91
synthetic_cycles_count=91
baseline_gross=0.16536982
baseline_avg_gross=0.00181725
baseline_median_gross=0.00049554
baseline_win_rate=0.505495
winner_count=46
loser_count=43
sample_size_status=preferred
```

Per-symbol post-expansion summary:

```text
ADA/USD  cycles=7  gross_total=0.00079251   win_rate=0.428571
ALGO/USD cycles=54 gross_total=0.20727475   win_rate=0.518519
BTC/USD  cycles=6  gross_total=0.01789970   win_rate=0.666667
ETH/USD  cycles=8  gross_total=-0.04571145  win_rate=0.25
SOL/USD  cycles=16 gross_total=-0.01488569  win_rate=0.5625
```

Per-exit-reason post-expansion summary:

```text
timeout       cycles=48 gross_total=0.15783428   win_rate=0.583333
stop-loss     cycles=25 gross_total=-0.56473020  win_rate=0.0
take-profit   cycles=18 gross_total=0.57226574   win_rate=1.0
```

## Filter Validation Result

Validated diagnostic scenarios:

```text
baseline_all_synthetic_cycles
exclude_stop_loss
exclude_strategy_mean_reversion
exclude_symbol_ETH/USD
exclude_symbol_ADA/USD
exclude_symbol_BTC/USD
exclude_symbol_SOL/USD
dynamic_exclude_strategy_mean_reversion
dynamic_exclude_exit_reason_stop_loss
```

Best scenario by gross delta:

```text
scenario=exclude_stop_loss
sample_size=66
synthetic_gross_total=0.73010002
avg_gross=0.01106212
median_gross=0.00803462
win_rate=0.696970
gross_delta_vs_baseline=0.56473020
validation_status=validated
```

Provisional-positive exploratory scenario:

```text
scenario=exclude_ALGO_and_stop_loss
sample_size=31
synthetic_gross_total=0.08846366
avg_gross=0.00285367
median_gross=0.00300440
win_rate=0.580645
validation_status=provisional_positive
failed_gate=sample_size < 50 preferred
```

Rejected scenarios:

```text
exclude_symbol_ALGO/USD
dynamic_exclude_strategy_momentum_breakout
dynamic_exclude_exit_reason_take_profit
dynamic_exclude_exit_reason_timeout
```

## Interpretation

The larger sample changes the picture materially. The baseline synthetic sample
is now gross-positive and meets the preferred cycle-count gate, while stop-loss
exclusion is the strongest validated diagnostic by gross delta.

This still does not authorize implementation. The result is gross-only,
synthetic, and based on public candle bars without real bid/ask, spread,
slippage, queue position, Coinbase fees, live order behavior, or broker-backed
fills. It is a useful offline filter-research signal, not a trading approval.

ALGO is now the largest contributor to positive gross (`+0.20727475`) but also
has the largest public-data gap count. Excluding ALGO is rejected because it
turns total gross negative. ETH exclusion is validated as a diagnostic and
improves the sample, but symbol-level conclusions remain secondary to the
stronger stop-loss/exit-reason finding.

SOL remains excluded from live bot inventory and trading because the user's SOL
is externally staked. Synthetic SOL diagnostics do not change that live
inventory truth.

## Leakage Guards

Post-expansion reports preserve:

```text
no_future_bars_for_signal=true
exit_after_entry_only=true
no_journal_exit_leakage=true
```

## Next Recommended Patch

Use P2-025Z for a no-live-change offline report that explains the validated
stop-loss exclusion result against current live-exit semantics. The report
should determine whether stop-loss losers are true avoidable entry-quality
failures, exit-policy artifacts, or unavoidable adverse moves.

Do not implement a live stop-loss filter, tune exits, run paper/live probes,
restart, change config, or scale until that explanation survives additional
offline scrutiny.
