# P2-039B Local Market Data Substrate / Parquet + DuckDB Readiness

## Purpose
The purpose of P2-039B is to implement the local storage architecture required to ingest, validate, and query high-resolution price-path (OHLCV) and bid/ask spread snapshots. This forms the foundation for future counterfactual backtests (P2-038D) and predictive model training.

## Architecture
The bot uses a **local-only Parquet + DuckDB** substrate. 
Parquet provides extreme columnar compression and fast read performance. DuckDB provides analytical SQL querying capabilities directly against those Parquet files without requiring a running database server. `pyarrow` is used as the high-performance serialization layer.

## Directory Layout
Data is stored locally under:
- `data/market_data/ohlcv/`
- `data/market_data/spreads/`

## Schemas

### 1m OHLCV
- `timestamp` (INT64, unix epoch milliseconds): Primary time index.
- `open` (DOUBLE)
- `high` (DOUBLE)
- `low` (DOUBLE)
- `close` (DOUBLE)
- `volume` (DOUBLE)

### Bid/Ask Spread Snapshots
- `timestamp` (INT64, unix epoch milliseconds): Snapshot time.
- `best_bid` (DOUBLE)
- `best_ask` (DOUBLE)
- `bid_size` (DOUBLE)
- `ask_size` (DOUBLE)

### Dataset Manifest
Stored as `manifest.json` per partition to maintain provenance.
- `source`: (e.g., "coinbase_public_api")
- `symbol`: (e.g., "BTC/USD")
- `timeframe`: (e.g., "1m")
- `row_count`: Number of rows in the dataset
- `earliest_timestamp`: ISO8601 string
- `latest_timestamp`: ISO8601 string
- `file_hash`: SHA256 hash of the Parquet file for auditability

## Backfill Plan
To reach the required ≥90d minimum for research assets, a future patch will fetch historical OHLCV data using public, unauthenticated exchange endpoints, writing strictly to this local substrate.

## Spread Reality Note
> **CRITICAL**: Spread data cannot be reconstructed retrospectively from public OHLCV APIs. Future passive capture must actively log live bid/ask snapshots alongside OHLCV to build honest slippage profiles.

## Safety & Governance
This patch is entirely architectural and read-only regarding broker interactions.
- **No** live collector launch.
- **No** authenticated broker APIs.
- **No** strategy, risk, or capital changes.
- **No** launchctl modification.
