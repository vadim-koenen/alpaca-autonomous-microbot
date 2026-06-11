# P2-039D Public OHLCV Backfill Adapter

## Purpose
Provides a controlled, governed adapter for fetching historical public market data (OHLCV) and piping it into the local P2-039C DuckDB/Parquet substrate. 

## Dry-Run Default
> [!IMPORTANT]
> The adapter is completely dry-run by default. If executed normally, it performs pre-flight checks, calculates missing bars/coverage, and declares its manifest intent, but it makes **zero network requests** and writes **no files**.

## Explicit Public Fetch Gate
Actual network data fetching requires passing the explicit `--allow-public-fetch` CLI flag.

## Authentication Constraints
- **NO** authenticated broker APIs.
- **NO** account data access.
- **NO** `.env` secrets are read or required.
- **NO** Coinbase or Alpaca private REST/WebSocket connections.

## Testing & Mocks
Tests rely entirely on a built-in `MockPublicProvider` fixture. Tests run hermetically using Pytest `tmp_path`, verifying normalization and formatting logic without producing unversioned market-data artifacts in the local repository. 

## Integration
This patch is a direct upstream producer for P2-039C. It feeds mocked (or eventually public) DataFrames into the exact same `write_ohlcv_parquet` function defined in `scripts/p2_039c_local_ohlcv_backfill.py`.

## Next Steps
Machine Learning remains blocked. Replay simulation remains blocked. We cannot advance to counterfactual replay simulations until we actually accumulate enough high-fidelity, high-frequency (1m) market data. This patch establishes the safety scaffolding to fetch that data.
