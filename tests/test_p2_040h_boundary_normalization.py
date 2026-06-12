import json
import os
import pathlib
import sys
import pandas as pd
import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

from scripts import normalize_public_backfill_windows as normalizer

@pytest.fixture
def dummy_manifests_inclusive(tmp_path):
    # Day 1: 1441 rows
    start_dt1 = pd.to_datetime("2026-06-10T23:00:00Z")
    end_dt1 = pd.to_datetime("2026-06-11T23:00:00Z")
    date_range1 = pd.date_range(start=start_dt1, end=end_dt1, freq='1min')
    
    df1 = pd.DataFrame({
        "timestamp": date_range1.tz_localize(None).astype('datetime64[ms]').astype('int64'),
        "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0, "volume": 10.0
    })
    
    p1 = tmp_path / "day1.parquet"
    df1.to_parquet(p1)
    
    m1 = tmp_path / "day1.manifest.json"
    with open(m1, 'w') as f:
        json.dump({"parquet_file": "day1.parquet", "row_count": 1441}, f)
        
    # Day 2: 1441 rows, overlapping boundary exactly at 2026-06-11T23:00:00Z
    start_dt2 = pd.to_datetime("2026-06-11T23:00:00Z")
    end_dt2 = pd.to_datetime("2026-06-12T23:00:00Z")
    date_range2 = pd.date_range(start=start_dt2, end=end_dt2, freq='1min')
    
    df2 = pd.DataFrame({
        "timestamp": date_range2.tz_localize(None).astype('datetime64[ms]').astype('int64'),
        "open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0, "volume": 10.0
    })
    
    p2 = tmp_path / "day2.parquet"
    df2.to_parquet(p2)
    
    m2 = tmp_path / "day2.manifest.json"
    with open(m2, 'w') as f:
        json.dump({"parquet_file": "day2.parquet", "row_count": 1441}, f)

    return str(m1), str(m2)

def test_single_window_normalization(dummy_manifests_inclusive, tmp_path):
    m1, _ = dummy_manifests_inclusive
    report_out = str(tmp_path / "report.json")
    
    report = normalizer.normalize_and_stitch([m1], report_out)
    
    assert report["raw_inclusive_rows"] == 1441
    assert report["dropped_overlapping_boundaries"] == 0
    assert report["normalized_replay_rows"] == 1440
    assert report["replay_window_policy"] == "END_EXCLUSIVE"

def test_two_adjacent_windows_normalization(dummy_manifests_inclusive, tmp_path):
    m1, m2 = dummy_manifests_inclusive
    report_out = str(tmp_path / "report.json")
    
    report = normalizer.normalize_and_stitch([m1, m2], report_out)
    
    assert report["raw_inclusive_rows"] == 2882
    assert report["dropped_overlapping_boundaries"] == 1
    assert report["normalized_replay_rows"] == 2880
    assert report["replay_window_policy"] == "END_EXCLUSIVE"

def test_duplicate_non_boundary_fails(dummy_manifests_inclusive, tmp_path):
    m1, _ = dummy_manifests_inclusive
    
    # Intentionally corrupt m1 to have a duplicate non-boundary
    p1 = tmp_path / "day1.parquet"
    df = pd.read_parquet(p1)
    df = pd.concat([df.iloc[[5]], df]).reset_index(drop=True)
    df.to_parquet(p1)
    
    report_out = str(tmp_path / "report.json")
    with pytest.raises(SystemExit):
        normalizer.normalize_and_stitch([m1], report_out)

def test_missing_gap_fails(dummy_manifests_inclusive, tmp_path):
    m1, _ = dummy_manifests_inclusive
    
    p1 = tmp_path / "day1.parquet"
    df = pd.read_parquet(p1)
    df = df.drop(500).reset_index(drop=True)
    df.to_parquet(p1)
    
    report_out = str(tmp_path / "report.json")
    with pytest.raises(SystemExit):
        normalizer.normalize_and_stitch([m1], report_out)

def test_schema_drift_fails(dummy_manifests_inclusive, tmp_path):
    m1, m2 = dummy_manifests_inclusive
    
    p2 = tmp_path / "day2.parquet"
    df = pd.read_parquet(p2)
    df["extra_col"] = 1.0
    df.to_parquet(p2)
    
    report_out = str(tmp_path / "report.json")
    with pytest.raises(SystemExit):
        normalizer.normalize_and_stitch([m1, m2], report_out)

def test_does_not_fetch(dummy_manifests_inclusive, tmp_path, monkeypatch):
    m1, _ = dummy_manifests_inclusive
    report_out = str(tmp_path / "report.json")
    
    def mock_fetch(*args, **kwargs):
        raise RuntimeError("Utility should not fetch")
        
    monkeypatch.setattr("urllib.request.urlopen", mock_fetch, raising=False)
    
    report = normalizer.normalize_and_stitch([m1], report_out)
    assert report is not None
