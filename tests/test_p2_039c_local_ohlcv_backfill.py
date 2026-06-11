import json
import pathlib
import sys
import pytest
import pandas as pd
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

from scripts import p2_039c_local_ohlcv_backfill as backfill

def test_normalize_symbol():
    assert backfill.normalize_symbol("BTC/USD") == "BTC_USD"
    assert backfill.normalize_symbol("ETH-USD") == "ETH_USD"
    assert backfill.normalize_symbol("sol/usd") == "SOL_USD"

def test_infer_timeframe():
    ts1 = pd.Series([1000, 61000, 121000])  # deltas are 60,000 ms
    assert backfill.infer_timeframe(ts1) == "1m"
    
    ts2 = pd.Series([1000, 301000, 601000]) # deltas are 300,000 ms
    assert backfill.infer_timeframe(ts2) == "5m"

def test_load_and_validate_csv(tmp_path):
    csv_file = tmp_path / "valid.csv"
    df = pd.DataFrame({
        "time": ["2026-06-01T00:00:00Z", "2026-06-01T00:01:00Z"],
        "open": [100.0, 101.0],
        "high": [105.0, 106.0],
        "low": [95.0, 96.0],
        "close": [102.0, 103.0],
        "volume": [10.5, 20.0]
    })
    df.to_csv(csv_file, index=False)
    
    table = backfill.load_local_ohlcv_csv(csv_file, "BTC/USD", "test_source")
    assert len(table) == 2
    assert table.column_names == ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    
    # 2026-06-01T00:00:00Z is 1780272000000 ms
    timestamps = table["timestamp"].to_pylist()
    assert timestamps[0] == 1780272000000
    
    assert backfill.validate_ohlcv_schema(table)

def test_reject_missing_columns(tmp_path):
    csv_file = tmp_path / "missing.csv"
    df = pd.DataFrame({
        "time": ["2026-06-01T00:00:00Z"],
        "open": [100.0],
        "high": [105.0]
        # missing low, close, volume
    })
    df.to_csv(csv_file, index=False)
    
    with pytest.raises(ValueError, match="Missing required numeric column: low"):
        backfill.load_local_ohlcv_csv(csv_file, "BTC/USD", "test_source")

def test_reject_invalid_ohlcv(tmp_path):
    csv_file = tmp_path / "invalid.csv"
    # Negative volume
    df = pd.DataFrame({
        "time": ["2026-06-01T00:00:00Z"],
        "open": [100.0],
        "high": [105.0],
        "low": [95.0],
        "close": [102.0],
        "volume": [-10.5]
    })
    df.to_csv(csv_file, index=False)
    
    with pytest.raises(ValueError, match="Negative prices or volume found"):
        backfill.load_local_ohlcv_csv(csv_file, "BTC/USD", "test_source")

def test_deduplicate_timestamps(tmp_path):
    csv_file = tmp_path / "dupes.csv"
    df = pd.DataFrame({
        "time": ["2026-06-01T00:00:00Z", "2026-06-01T00:00:00Z"],
        "open": [100.0, 101.0], # second one should be kept (keep=last)
        "high": [105.0, 106.0],
        "low": [95.0, 96.0],
        "close": [102.0, 103.0],
        "volume": [10.5, 20.0]
    })
    df.to_csv(csv_file, index=False)
    
    table = backfill.load_local_ohlcv_csv(csv_file, "BTC/USD", "test_source")
    assert len(table) == 1
    assert table["open"][0].as_py() == 101.0

def test_write_and_duckdb_read(tmp_path):
    csv_file = tmp_path / "valid.csv"
    df = pd.DataFrame({
        "time": ["2026-06-01T00:00:00Z"],
        "open": [100.0],
        "high": [105.0],
        "low": [95.0],
        "close": [102.0],
        "volume": [10.5]
    })
    df.to_csv(csv_file, index=False)
    
    table = backfill.load_local_ohlcv_csv(csv_file, "BTC/USD", "test_source")
    
    out_root = tmp_path / "data"
    parquet_path, manifest = backfill.write_ohlcv_parquet(table, out_root, "BTC/USD", "1m", "test_source")
    
    assert parquet_path.exists()
    assert parquet_path.name == "test_source_BTC_USD_1m.parquet"
    
    # Read via duckdb
    conn = duckdb.connect(database=':memory:')
    res = conn.execute(f"SELECT close FROM read_parquet('{parquet_path}')").fetchone()
    assert res[0] == 102.0
    
    # Manifest validation
    assert manifest["dataset_type"] == "ohlcv"
    assert manifest["symbol"] == "BTC/USD"
    assert manifest["timeframe"] == "1m"
    assert manifest["source"] == "test_source"
    assert manifest["row_count"] == 1
    assert manifest["sha256"]
    
    manifest_file = parquet_path.with_suffix(".manifest.json")
    assert manifest_file.exists()
    loaded_manifest = json.loads(manifest_file.read_text())
    assert loaded_manifest == manifest
