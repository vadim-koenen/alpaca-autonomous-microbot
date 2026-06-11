#!/usr/bin/env python3
"""P2-039C Local OHLCV Backfill Extractor / Manifest Writer.

Deterministic local OHLCV extraction utility that reads local CSV inputs,
normalizes them to the P2-039B 1m schema, and writes Parquet to the local substrate.
Purely local, purely deterministic, zero network dependencies.
"""

import argparse
import datetime
import hashlib
import json
import logging
import pathlib
import sys
from typing import Dict, Any, Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Use the exact schema from P2-039B
OHLCV_SCHEMA = pa.schema([
    ("timestamp", pa.int64()),  # unix epoch ms
    ("open", pa.float64()),
    ("high", pa.float64()),
    ("low", pa.float64()),
    ("close", pa.float64()),
    ("volume", pa.float64())
])

def normalize_symbol(symbol: str) -> str:
    """Normalize symbol for filesystem paths (e.g. BTC/USD -> BTC_USD)."""
    return symbol.replace("/", "_").replace("-", "_").upper()

def infer_timeframe(timestamps: pd.Series) -> str:
    """Infer timeframe string based on median delta in milliseconds."""
    if len(timestamps) < 2:
        return "1m"  # Default fallback
    
    # Calculate median delta in ms
    deltas = timestamps.diff().dropna()
    median_delta_ms = deltas.median()
    
    # 60,000 ms = 1m
    if median_delta_ms == 60000:
        return "1m"
    elif median_delta_ms == 300000:
        return "5m"
    elif median_delta_ms == 3600000:
        return "1h"
    elif median_delta_ms == 86400000:
        return "1d"
    
    return "1m" # fallback

def load_local_ohlcv_csv(path: pathlib.Path, symbol: str, source: str, timeframe: str = "1m") -> pa.Table:
    """Load, normalize, validate and sort a local CSV into a pyarrow Table."""
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    # Read CSV
    df = pd.read_csv(path)
    
    # Map columns flexibly (case-insensitive)
    cols = {c.lower(): c for c in df.columns}
    
    # Identify time column
    time_col = None
    for cand in ['timestamp', 'time', 'datetime', 'date']:
        if cand in cols:
            time_col = cols[cand]
            break
            
    if not time_col:
        raise ValueError("Missing time column (looked for timestamp, time, datetime, date)")

    # Identify OHLCV
    for req in ['open', 'high', 'low', 'close', 'volume']:
        if req not in cols:
            raise ValueError(f"Missing required numeric column: {req}")
            
    # Standardize column names
    df = df.rename(columns={
        time_col: 'timestamp',
        cols['open']: 'open',
        cols['high']: 'high',
        cols['low']: 'low',
        cols['close']: 'close',
        cols['volume']: 'volume'
    })
    
    # Parse timestamp safely to UTC
    # Try parsing as numeric epoch first (s or ms), otherwise datetime parsing
    try:
        # If it's already an int/float epoch, convert to ms
        if pd.api.types.is_numeric_dtype(df['timestamp']):
            # If values are < 3000000000, assume seconds, else ms
            if df['timestamp'].max() < 3000000000:
                df['timestamp'] = df['timestamp'] * 1000
            df['timestamp'] = df['timestamp'].astype(int)
        else:
            # Parse as datetime and convert to unix ms safely
            dt_series = pd.to_datetime(df['timestamp'], utc=True)
            # Universal safe conversion to epoch ms across all Pandas versions
            epoch = pd.Timestamp("1970-01-01", tz="UTC")
            ms_series = (dt_series - epoch) // pd.Timedelta(milliseconds=1)
            df['timestamp'] = ms_series.astype(int)
    except Exception as e:
        raise ValueError(f"Failed to parse timestamp column: {e}")

    # Coerce to floats
    for c in ['open', 'high', 'low', 'close', 'volume']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
        if df[c].isna().any():
            raise ValueError(f"Non-numeric values found in column {c}")

    # Validations
    if (df[['open', 'high', 'low', 'close', 'volume']] < 0).any().any():
        raise ValueError("Negative prices or volume found")
        
    if (df['high'] < df['open']).any() or (df['high'] < df['close']).any() or (df['high'] < df['low']).any():
        raise ValueError("High is less than open, close, or low")
        
    if (df['low'] > df['open']).any() or (df['low'] > df['close']).any() or (df['low'] > df['high']).any():
        raise ValueError("Low is greater than open, close, or high")

    # Sort deterministically and deduplicate
    df = df.sort_values('timestamp')
    df = df.drop_duplicates(subset=['timestamp'], keep='last')
    
    # Select only the required schema columns
    df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
    
    # Convert to pyarrow using exact schema
    table = pa.Table.from_pandas(df, schema=OHLCV_SCHEMA, preserve_index=False)
    
    return table

def validate_ohlcv_schema(table: pa.Table) -> bool:
    """Ensure the table exactly matches P2-039B schema."""
    if table.schema != OHLCV_SCHEMA:
        raise ValueError(f"Table schema does not match strictly expected OHLCV schema.")
    return True

def compute_file_hash(filepath: pathlib.Path) -> str:
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256.update(chunk)
    return sha256.hexdigest()

def summarize_dataset(table: pa.Table) -> Dict[str, Any]:
    """Generate summary boundaries from an in-memory table."""
    row_count = len(table)
    if row_count == 0:
        return {"row_count": 0, "earliest": None, "latest": None}
        
    ts_array = table['timestamp'].to_pylist()
    min_ts = min(ts_array)
    max_ts = max(ts_array)
    
    earliest = datetime.datetime.fromtimestamp(min_ts / 1000.0, tz=datetime.timezone.utc).isoformat()
    latest = datetime.datetime.fromtimestamp(max_ts / 1000.0, tz=datetime.timezone.utc).isoformat()
    
    return {
        "row_count": row_count,
        "earliest": earliest,
        "latest": latest
    }

def generate_or_update_manifest(
    parquet_path: pathlib.Path, 
    symbol: str, 
    source: str, 
    timeframe: str, 
    summary: Dict[str, Any]
) -> Dict[str, Any]:
    """Create or update the JSON manifest alongside the Parquet file."""
    manifest = {
        "dataset_type": "ohlcv",
        "symbol": symbol,
        "timeframe": timeframe,
        "source": source,
        "row_count": summary["row_count"],
        "earliest_timestamp": summary["earliest"],
        "latest_timestamp": summary["latest"],
        "parquet_file": parquet_path.name,
        "sha256": compute_file_hash(parquet_path),
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "schema_version": "1"
    }
    
    manifest_path = parquet_path.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest

def write_ohlcv_parquet(table: pa.Table, output_root: pathlib.Path, symbol: str, timeframe: str, source: str) -> tuple[pathlib.Path, Dict]:
    """Write table to the substrate partition and generate manifest."""
    sym_norm = normalize_symbol(symbol)
    
    # Path: data/market_data/ohlcv/{symbol_normalized}/{timeframe}/
    partition_dir = output_root / sym_norm / timeframe
    partition_dir.mkdir(parents=True, exist_ok=True)
    
    file_name = f"{source}_{sym_norm}_{timeframe}.parquet"
    out_path = partition_dir / file_name
    
    pq.write_table(table, out_path)
    logging.info(f"Wrote Parquet to {out_path}")
    
    summary = summarize_dataset(table)
    manifest = generate_or_update_manifest(out_path, symbol, source, timeframe, summary)
    logging.info(f"Wrote Manifest to {out_path.with_suffix('.manifest.json')}")
    
    return out_path, manifest

def main() -> None:
    parser = argparse.ArgumentParser(description="P2-039C Local OHLCV Backfill Extractor")
    parser.add_argument("--input", required=True, type=str, help="Path to local CSV input")
    parser.add_argument("--symbol", required=True, type=str, help="Symbol name (e.g. BTC/USD)")
    parser.add_argument("--source", required=True, type=str, help="Data source name (e.g. coinbase_historic)")
    parser.add_argument("--output-root", type=str, default=None, help="Root for output (defaults to data/market_data/ohlcv)")
    parser.add_argument("--write", action="store_true", help="Actually write Parquet and Manifest. If omitted, dry-run mode.")
    
    args = parser.parse_args()
    
    in_path = pathlib.Path(args.input)
    if not in_path.exists():
        logging.error(f"Input file not found: {in_path}")
        sys.exit(1)
        
    try:
        logging.info(f"Loading {in_path} ...")
        table = load_local_ohlcv_csv(in_path, args.symbol, args.source)
        validate_ohlcv_schema(table)
    except Exception as e:
        logging.error(f"Validation failed: {e}")
        sys.exit(1)
        
    summary = summarize_dataset(table)
    logging.info(f"Summary: {summary}")
    
    if args.write:
        if args.output_root:
            out_root = pathlib.Path(args.output_root)
        else:
            repo_root = pathlib.Path(__file__).resolve().parents[1]
            out_root = repo_root / "data" / "market_data" / "ohlcv"
            
        write_ohlcv_parquet(table, out_root, args.symbol, "1m", args.source)
    else:
        logging.info("DRY RUN: --write flag not provided. No files written.")

if __name__ == "__main__":
    main()
