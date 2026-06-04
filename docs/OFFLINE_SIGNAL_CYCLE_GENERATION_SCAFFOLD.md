# Offline Signal/Cycle Generation Scaffold

## Why This Exists

P2-025T demonstrated that evaluating selectivity filters on the current 50-cycle journal window is insufficient for high-confidence validation. Expanding the backtest requires generating historical candidate trades (signals) for periods where no journal data exists.

`scripts/coinbase_offline_signal_cycle_generation_scaffold.py` provides a formal gap analysis and proposed architecture for reconstructing strategy signals from historical OHLCV data.

## Required Signal Inputs

To reproduce historical entry/exit cycles, the following inputs must be modeled or reconstructed offline:

| Input | Status | Source / Gap |
| :--- | :--- | :--- |
| **Candles** | Available | Local OHLCV files |
| **Indicators** | Partial | `market_data.add_indicators` needs offline-safe integration |
| **Regime Detection** | Partial | `strategy_crypto.classify_regime` needs integration |
| **Bid/Ask Spread** | **Missing** | Not in OHLCV; needs modelling (e.g., close + spread model) |
| **Confidence Scoring**| Partial | Reconstruction from indicators required |
| **Position State** | **Missing** | Simulation of `max_open_positions` and cooldowns required |
| **Trade Caps** | **Missing** | Simulation of daily trade limits required |

## Proposed Architecture

1.  **OHLCV Loader:** Detects and loads historical candle files.
2.  **Indicator Reconstruction:** Applies strategy-identical indicators to historical bars.
3.  **Signal Generator:** Runs `strategy_crypto` logic over historical data to identify candidate entries.
4.  **Entry Simulator:** Applies bid/ask modeling and slippage to candidate entries.
5.  **Predictive Exit Simulator:** Replays the price path from entry to identify TP/SL/Timeout exits.
6.  **Cycle Journal Generator:** Produces schema-compliant cycle records for validation reporting.
7.  **Filter Validation:** Evaluates selectivity filters against the expanded synthetic dataset.

## Readiness Gates

| Gate | Status | Note |
| :--- | :--- | :--- |
| **Signal Generation Ready** | **FALSE** | Strategy runner adapter not yet implemented. |
| **Cycle Generation Ready** | **FALSE** | Simulation loop not yet implemented. |
| **Historical Backtest Ready**| **FALSE** | Expanded dataset generation not yet possible. |

## Next Implementation Options

The highest-ROI next step is to implement an **Offline Strategy Runner** adapter that can process `pandas` DataFrames using existing `strategy_crypto.py` logic, without requiring a live `MarketData` object.

## Preserved Invariants

- **Implementation Authorized:** False
- **Paper/Live Probes Authorized:** False
- **Scaling Authorized:** False
- **No Live Strategy Changes:** This scaffold does not modify the production trading logic.
- **No Data Mutation:** Offline OHLCV remains read-only.
