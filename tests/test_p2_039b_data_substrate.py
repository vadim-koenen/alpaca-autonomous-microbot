import json
import pathlib
import sys
import pytest

import pyarrow as pa
import duckdb

# Add REPO_ROOT to sys.path so we can import scripts
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

from scripts import p2_039b_data_substrate_init as substrate

def test_dry_run_directory_creation(capsys):
    substrate.initialize_directories(dry_run=True)
    captured = capsys.readouterr()
    assert "[DRY-RUN]" in captured.out
    assert str(substrate.OHLCV_DIR) in captured.out
    assert str(substrate.SPREADS_DIR) in captured.out

def test_schema_validity():
    # OHLCV Schema
    assert substrate.OHLCV_SCHEMA.field("timestamp").type == pa.int64()
    assert substrate.OHLCV_SCHEMA.field("close").type == pa.float64()
    
    # Spread Schema
    assert substrate.SPREAD_SCHEMA.field("timestamp").type == pa.int64()
    assert substrate.SPREAD_SCHEMA.field("best_ask").type == pa.float64()

def test_synthetic_parquet_and_manifest(tmp_path):
    ohlcv_dir = tmp_path / "ohlcv"
    ohlcv_dir.mkdir()
    
    # Write a table with one row
    arrays = [
        pa.array([1718000000000], type=pa.int64()), # timestamp
        pa.array([65000.0], type=pa.float64()),     # open
        pa.array([65100.0], type=pa.float64()),     # high
        pa.array([64900.0], type=pa.float64()),     # low
        pa.array([65050.0], type=pa.float64()),     # close
        pa.array([10.5], type=pa.float64())         # volume
    ]
    table = pa.Table.from_arrays(arrays, schema=substrate.OHLCV_SCHEMA)
    
    import pyarrow.parquet as pq
    filepath = ohlcv_dir / "test_ohlcv.parquet"
    pq.write_table(table, filepath)
    
    # Generate Manifest
    manifest = substrate.generate_manifest(filepath, source="test", symbol="BTC/USD", timeframe="1m")
    
    assert manifest["source"] == "test"
    assert manifest["symbol"] == "BTC/USD"
    assert manifest["row_count"] == 1
    assert "file_hash" in manifest
    assert len(manifest["file_hash"]) == 64 # SHA256 length
    
    # Verify DuckDB can read it
    conn = duckdb.connect(database=':memory:')
    res = conn.execute(f"SELECT COUNT(*) FROM read_parquet('{filepath}')").fetchone()
    assert res[0] == 1
    
    # Test file reading via DuckDB
    row = conn.execute(f"SELECT close FROM read_parquet('{filepath}')").fetchone()
    assert row[0] == 65050.0

def test_empty_manifest(tmp_path):
    ohlcv_dir = tmp_path / "ohlcv"
    ohlcv_dir.mkdir()
    
    filepath = substrate.write_synthetic_data(ohlcv_dir, substrate.OHLCV_SCHEMA, "empty.parquet")
    
    manifest = substrate.generate_manifest(filepath, source="test", symbol="BTC/USD", timeframe="1m")
    
    assert manifest["row_count"] == 0
    assert manifest["earliest_timestamp"] is None
    assert manifest["latest_timestamp"] is None
