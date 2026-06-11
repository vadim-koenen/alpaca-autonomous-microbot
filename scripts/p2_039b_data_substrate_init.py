#!/usr/bin/env python3
"""P2-039B Local Market Data Substrate / Parquet + DuckDB Readiness.

Initializes the local directory structure and enforces Parquet schema layouts 
for OHLCV and spread snapshots. Provides basic manifest generation utilities.
"""

import argparse
import datetime
import hashlib
import json
import pathlib
import sys
from typing import Dict, Any

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
    import duckdb
except ImportError:
    print("Missing required dependencies. Run: pip install duckdb pyarrow")
    sys.exit(1)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data" / "market_data"
OHLCV_DIR = DATA_ROOT / "ohlcv"
SPREADS_DIR = DATA_ROOT / "spreads"

# Define strict PyArrow Schemas
OHLCV_SCHEMA = pa.schema([
    ("timestamp", pa.int64()),  # unix epoch ms
    ("open", pa.float64()),
    ("high", pa.float64()),
    ("low", pa.float64()),
    ("close", pa.float64()),
    ("volume", pa.float64())
])

SPREAD_SCHEMA = pa.schema([
    ("timestamp", pa.int64()),  # unix epoch ms
    ("best_bid", pa.float64()),
    ("best_ask", pa.float64()),
    ("bid_size", pa.float64()),
    ("ask_size", pa.float64())
])

def initialize_directories(dry_run: bool = False) -> None:
    """Ensure data directories exist."""
    dirs = [OHLCV_DIR, SPREADS_DIR]
    for d in dirs:
        if dry_run:
            status = "Exists" if d.exists() else "Would create"
            print(f"[DRY-RUN] {status}: {d}")
        else:
            d.mkdir(parents=True, exist_ok=True)
            print(f"[INIT] Ensured directory exists: {d}")

def compute_file_hash(filepath: pathlib.Path) -> str:
    """Compute SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256.update(chunk)
    return sha256.hexdigest()

def generate_manifest(filepath: pathlib.Path, source: str, symbol: str, timeframe: str) -> Dict[str, Any]:
    """Read a Parquet file and generate a compliant manifest."""
    if not filepath.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    table = pq.read_table(filepath)
    if "timestamp" not in table.column_names:
        raise ValueError("Parquet file missing required 'timestamp' column")

    timestamps = table["timestamp"]
    if len(timestamps) == 0:
        earliest = None
        latest = None
    else:
        # Convert unix ms to ISO8601 UTC
        min_ts = min(timestamps).as_py()
        max_ts = max(timestamps).as_py()
        earliest = datetime.datetime.fromtimestamp(min_ts / 1000.0, tz=datetime.timezone.utc).isoformat()
        latest = datetime.datetime.fromtimestamp(max_ts / 1000.0, tz=datetime.timezone.utc).isoformat()

    file_hash = compute_file_hash(filepath)

    manifest = {
        "source": source,
        "symbol": symbol,
        "timeframe": timeframe,
        "row_count": len(table),
        "earliest_timestamp": earliest,
        "latest_timestamp": latest,
        "file_hash": file_hash,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    
    # Save manifest alongside file
    manifest_path = filepath.with_suffix('.manifest.json')
    manifest_path.write_text(json.dumps(manifest, indent=2))
    
    return manifest

def write_synthetic_data(directory: pathlib.Path, schema: pa.Schema, filename: str) -> pathlib.Path:
    """Write an empty or synthetic table using the strict schema to verify readiness."""
    filepath = directory / filename
    
    # Create empty arrays matching the schema
    arrays = []
    for field in schema:
        if field.type == pa.int64():
            arrays.append(pa.array([], type=pa.int64()))
        elif field.type == pa.float64():
            arrays.append(pa.array([], type=pa.float64()))
            
    table = pa.Table.from_arrays(arrays, schema=schema)
    pq.write_table(table, filepath)
    print(f"[WRITE] Created schema-compliant Parquet file: {filepath}")
    return filepath

def main() -> None:
    parser = argparse.ArgumentParser(description="P2-039B Data Substrate Init")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without mutating filesystem")
    args = parser.parse_args()

    print("=== P2-039B Data Substrate Initialization ===")
    initialize_directories(dry_run=args.dry_run)
    
    if not args.dry_run:
        print("\nVerifying DuckDB Integration...")
        conn = duckdb.connect(database=':memory:')
        res = conn.execute("SELECT 1 AS ready").fetchone()
        if res and res[0] == 1:
            print("[DUCKDB] Connection and query successful.")
            
        print("\nSubstrate initialization complete. Schemas are defined in script.")

if __name__ == "__main__":
    main()
