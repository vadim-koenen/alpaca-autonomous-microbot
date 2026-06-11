# P2-039C Local OHLCV Backfill Extractor

## Purpose
This patch provides the missing functional bridge between existing local raw OHLCV datasets (e.g. CSV dumps from initial exploration phases) and the newly formalized P2-039B Parquet + DuckDB Substrate. 

It is a purely deterministic extraction utility designed to read, normalize, validate, deduplicate, and convert CSV OHLCV data into ultra-fast Parquet files with cryptographic manifests.

## Local-Only / Network-Free
> [!IMPORTANT]
> This script contains absolutely **zero network dependencies**. It does not fetch data from Coinbase, Alpaca, or any public API. It operates entirely offline on local files to preserve strict evidence boundaries.

## Position in the Roadmap
- **P2-039A** identified that all candidate assets currently have insufficient local OHLCV data to pass the fee hurdle simulation.
- **P2-039B** defined the local schema and storage paths (`data/market_data/ohlcv`) using Parquet and DuckDB.
- **P2-039C (This Patch)** implements the deterministic extraction engine to populate that substrate.

## Why this does NOT make `REPLAY_READY=true`
P2-039C provides the *tooling* to build the dataset, but it does not magically conjure the data itself. The bot still currently lacks the required ≥90 days of 1m OHLCV data and high-frequency bid/ask spread snapshots required to honesty simulate edge. The `REPLAY_READY` gate will remain `false` until the substrate is physically populated.

## Safety Declarations
- **No** live restarts.
- **No** broker order mutations.
- **No** authenticated API usage.
- **No** changes to live strategies or risk/capital configurations.

## Next Expected Patch
The logical next step is a controlled, unauthenticated public historical backfill adapter that fetches the missing data and securely feeds it into this P2-039C extractor, OR the design of the live spread snapshot capture system.
