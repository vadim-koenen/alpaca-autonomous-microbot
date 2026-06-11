# P2-038C Price-Path Evidence Capture / Replay Readiness Gate

## Purpose
The purpose of the P2-038C gate is to determine whether the repository holds sufficient high-resolution historical price-path data (OHLCV or tick data) to reliably simulate the alternative exit policies formulated in P2-038B. 

## Why P2-038C exists after P2-038B
P2-038B proved that historical entry/exit trade records alone are sufficient to calculate baseline fee economics, but insufficient to honestly simulate path-dependent exits like early timeouts, breakeven-plus-fees, or trailing stops. Because the data was missing, P2-038B safely disabled path-dependent policies. P2-038C was created to definitively assess the availability and quality of path data to gate the next steps of historical backtesting.

## Inputs
- Canonical normalized journal exports (`reports/journals/export_*.json`) from P2-037.
- Local price path logs: `logs/coinbase_price_path.csv` or `data/ohlcv/` directories.

## Readiness Thresholds
To be marked as replay-ready, a trade must meet:
- **Minimum granularity**: 1 minute or better.
- **Minimum coverage ratio**: 95% of the trade duration.
- **Maximum allowed gap**: 300 seconds.
- **Required data fields**: timestamp, symbol, close price.
- **Intra-candle ambiguity rule**: TP and SL in the same candle is treated as ambiguous.
- **Conservative worst-case assumption**: Assume SL hits before TP if order is ambiguous.

## Local-Only Default Behavior
By default, the script strictly searches the local filesystem for evidence. It does not spawn network requests, touch `launchctl`, or invoke external scripts.

## Public OHLCV Feasibility Rules
The gate includes a feasibility section detailing how unauthenticated/public OHLCV data could be fetched if a safe public-data fetcher exists. Any fetch flag (`--fetch`) is strictly opt-in, disabled by default, and must never require API secrets or authenticated broker APIs.

## Replay-Ready vs Not-Ready Interpretation
- **REPLAY_READY=true**: Adequate tick or 1-minute candle data exists for the historical trades.
- **REPLAY_READY=false**: The repository lacks the data needed to perform counterfactual simulations.

## Explicit Warning
**This does not change live trading.**
This script and its tests are purely advisory and read-only. It makes no mutations to live behavior, strategies, broker orders, risk, sizing, or capital allocations.

## Next Recommended Patch
- **If REPLAY_READY=false (Current Expectation)**: P2-038D Public OHLCV backfill or safe passive path capture design.
- **If REPLAY_READY=true**: P2-038D actual replay/counterfactual execution using P2-038B policies.
