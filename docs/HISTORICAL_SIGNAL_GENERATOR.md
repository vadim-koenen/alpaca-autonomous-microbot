# P2-025W/P2-026A Historical Signal Generator

`scripts/coinbase_historical_signal_generator.py` is an offline-only diagnostic
that converts local OHLCV bars into synthetic cycle records by reusing the
P2-025V offline strategy runner adapter.

It does not authorize live trading, paper probes, scaling, live config changes,
maker/post-only execution, exit tuning, or strategy-threshold changes.

## Purpose

P2-025V proved that selected `strategy_crypto.py` logic can be invoked from an
offline adapter. P2-025W applies that adapter across local historical bars and
emits synthetic cycle records so the next review patch can validate filters on a
larger generated sample.

The generated records are synthetic analysis artifacts, not broker-backed trade
facts. They must not be treated as realized P/L or as approval to trade.

## Inputs

Default input directory:

```bash
data/offline_ohlcv/coinbase
```

Supported fixture formats are the same local CSV/JSON OHLCV formats consumed by
`coinbase_offline_backtest.load_bars_from_fixture`.

`data/offline_ohlcv/` remains untracked local working data and must not be
committed.

## Adapter Path

The generator reuses:

- `OfflineMarketDataAdapter`
- `_model_quote_from_bar`
- `classify_regime`
- `CryptoStrategy._momentum_breakout`
- `CryptoStrategy._mean_reversion`
- `CryptoStrategy._ema_crossover`
- `add_indicators`

Live dependencies are bypassed or mocked:

- market-data broker fetches
- `strategy_crypto.get_cfg`
- position and journal state
- risk-manager order approval
- broker order placement

## Leakage Guards

Every synthetic cycle includes leakage metadata:

- `no_future_bars_for_signal=true`
- `exit_after_entry_only=true`
- `no_journal_exit_leakage=true`
- `pre_entry_features_use_only_past_bars=true`
- `no_exit_reason_in_pre_entry_features=true`
- `no_future_path_in_pre_entry_features=true`

Signals are generated from bars available at the signal timestamp. Exit
simulation scans only bars after entry.

P2-026A adds pre-entry feature capture. These fields are computed from bars up
to and including the entry candle only:

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
```

Order-book fields remain unavailable in OHLCV-only data:

```text
order_book_spread_available=false
bid_ask_depth_available=false
order_book_features_missing_reason=OHLCV-only dataset
```

## Output

The report includes:

- `schema_version`
- `report_class=historical_signal_generator`
- `data_dir`
- `symbols_scanned`
- `bars_scanned`
- `date_range`
- `signal_candidates_count`
- `synthetic_cycles_count`
- `per_symbol_summary`
- `per_strategy_summary`
- `per_exit_reason_summary`
- `gross_summary`
- `pre_entry_feature_schema`
- `generated_cycle_sample`
- `leakage_guards`
- `readiness`
- `limitations`
- `verdict`
- `next_step_recommendation`

Synthetic cycle records include:

- `synthetic`
- `symbol`
- `strategy`
- `entry_time`
- `exit_time`
- `entry_price`
- `exit_price`
- `qty`
- `notional`
- `gross_pnl`
- `fees_paid`
- `pnl_usd`
- `pnl_pct`
- `confidence`
- `regime`
- `exit_reason`
- `hold_duration_minutes`
- `entry_spread_pct`
- `source_ohlcv_file`
- P2-026A pre-entry fields listed above

The script does not write cycle JSONL by default. Use `--output` only for an
explicit offline artifact:

```bash
python3 scripts/coinbase_historical_signal_generator.py --output /tmp/p2_025w_synthetic_cycles.jsonl --json
```

## Smoke Result

Current expanded local OHLCV smoke produced:

```text
symbols_scanned=['ADA/USD', 'ALGO/USD', 'BTC/USD', 'ETH/USD', 'SOL/USD']
bars_scanned=43333
signal_candidates_count=91
synthetic_cycles_count=91
gross_total=0.16536982
win_rate=0.505495
historical_signal_generator_ready=true
synthetic_cycle_journal_ready=true
expanded_filter_validation_ready=true
implementation_authorized=false
paper_probe_authorized=false
live_probe_authorized=false
scaling_authorized=false
pre_entry_features_use_only_past_bars=true
no_exit_reason_in_pre_entry_features=true
no_future_path_in_pre_entry_features=true
```

The next recommended action is expanded offline filter validation using the
generated synthetic cycles.

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
