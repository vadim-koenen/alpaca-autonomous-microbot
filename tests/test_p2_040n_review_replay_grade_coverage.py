import pytest
import os
import sys
import json
from unittest.mock import patch, mock_open

try:
    from scripts.p2_040n_review_replay_grade_coverage import review_replay_grade_coverage
except ImportError:
    # Handle path issues if running from different dirs
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    from scripts.p2_040n_review_replay_grade_coverage import review_replay_grade_coverage

@patch("os.path.exists")
@patch("builtins.open", new_callable=mock_open)
@patch("json.load")
@patch("scripts.p2_040n_review_replay_grade_coverage.normalize_and_stitch")
def test_p2_040n_review_happy_path(mock_norm, mock_json_load, mock_file, mock_exists):
    mock_exists.return_value = True
    
    # Mocking json.load sequentially for manifest then report
    mock_manifest = {"row_count": 10081}
    mock_report = {
        "provider": "coinbase_public",
        "symbol": "BTC/USD",
        "timeframe": "1m",
        "coverage": {
            "missing_bars": 0,
            "coverage_percentage": 100.0
        }
    }
    mock_json_load.side_effect = [mock_manifest, mock_report]
    
    mock_norm.return_value = {
        "raw_inclusive_rows": 10081,
        "normalized_replay_rows": 10080,
        "utc_aligned": True,
        "monotonic_timestamps": True,
        "duplicate_timestamps_found": False,
        "gaps_found": False,
        "schema_validated": True,
        "partial_latest_candle_excluded_or_marked": True
    }
    
    result = review_replay_grade_coverage("fake_man", "fake_rep", None)
    
    assert result["RAW_INCLUSIVE_CANDLE_COUNT"] == 10081
    assert result["NORMALIZED_REPLAY_CANDLE_COUNT"] == 10080
    assert result["COVERAGE_AUDIT_PASS"] == True
    assert result["REPLAY_GRADE_COVERAGE_READY_FOR_APPROVAL"] == True
    assert result["REPLAY_GRADE_COVERAGE_APPROVED"] == False
    assert result["ML_BLOCKED_UNTIL_REPLAY_GRADE_COVERAGE"] == True

@patch("os.path.exists")
@patch("builtins.open", new_callable=mock_open)
@patch("json.load")
@patch("scripts.p2_040n_review_replay_grade_coverage.normalize_and_stitch")
def test_p2_040n_review_fails_on_gaps(mock_norm, mock_json_load, mock_file, mock_exists):
    mock_exists.return_value = True
    
    mock_manifest = {"row_count": 10081}
    mock_report = {
        "provider": "coinbase_public",
        "symbol": "BTC/USD",
        "timeframe": "1m",
        "coverage": {
            "missing_bars": 0,
            "coverage_percentage": 100.0
        }
    }
    mock_json_load.side_effect = [mock_manifest, mock_report]
    
    mock_norm.return_value = {
        "raw_inclusive_rows": 10081,
        "normalized_replay_rows": 10080,
        "utc_aligned": True,
        "monotonic_timestamps": True,
        "duplicate_timestamps_found": False,
        "gaps_found": True,  # GAP!
        "schema_validated": True,
        "partial_latest_candle_excluded_or_marked": True
    }
    
    with pytest.raises(SystemExit) as exc_info:
        review_replay_grade_coverage("fake_man", "fake_rep", None)
        
    assert exc_info.value.code == 1
