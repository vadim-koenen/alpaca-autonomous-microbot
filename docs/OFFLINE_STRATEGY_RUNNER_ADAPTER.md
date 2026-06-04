# Offline Strategy Runner Adapter

## Why This Exists

P2-025U identified that historical OHLCV alone is insufficient for backtesting because the repo lacked an adapter to run existing strategy logic offline. Signal generation is required to create candidate entries for expanded periods.

`scripts/coinbase_offline_strategy_runner_adapter.py` provides this bridge by mocking `MarketData` and bypassing live dependencies to execute `strategy_crypto.py` logic against local bars.

## Analysis of Reusable Logic

The adapter successfully imported and exercised the following from `strategy_crypto.py`:

- **Indicator Enrichment:** `add_indicators` is pure and safely processes DataFrames.
- **Regime Classification:** `classify_regime` is pure and correctly labels market states.
- **Main Strategy Signals:** `_momentum_breakout`, `_mean_reversion`, and `_ema_crossover` were successfully invoked offline using modeled `Quote` and `MarketData` mocks.

## Identified Gaps & Blockers

- **Controlled Exploration:** `_coinbase_exploration` is currently "state-heavy". It requires reading the journal and position state to rotate symbols and respect cooldowns. These are live dependencies that were bypassed in the initial adapter smoke run.
- **Bid/Ask Modelling:** OHLCV data contains only Close prices. The adapter currently models bid/ask using a fixed spread (default 0.10%) which is sufficient for signal generation but lacks real-market noise.

## Readiness Gates

| Gate | Status | Note |
| :--- | :--- | :--- |
| **Strategy Logic Importable** | **TRUE** | No circular or broker-only imports block basic loading. |
| **Offline MarketData Adapter** | **TRUE** | `OfflineMarketDataAdapter` successfully mocks the broker layer. |
| **Historical Signal Ready** | **TRUE** | Pure strategy methods can be invoked offline. |

## Proposed historical Signal Generation Workflow

The adapter enables the following next phase:

1.  **Iterate** over historical bars.
2.  **Mock** a `MarketData` state at each candle.
3.  **Run** the strategy runner adapter to identify signals.
4.  **Emit** a synthetic journal for the historical period.

## Interpretation & Safety

- **No Profitability Claims:** This adapter tests *logic reusability*, not performance.
- **No Threshold Changes:** Production strategy constants remain untouched.
- **Preserved Invariants:** implementation_authorized=false, paper_probe_authorized=false, live_probe_authorized=false, scaling_authorized=false.
