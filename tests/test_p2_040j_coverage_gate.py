import json
import os
import pathlib
import sys
import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

from scripts import check_replay_grade_coverage_gate

def test_p2_040j_gate_passes_for_valid_state():
    try:
        check_replay_grade_coverage_gate.main()
    except SystemExit:
        pytest.fail("Gate script exited with error")
        
    report_path = '/tmp/p2_040j_coverage_gate_report.json'
    assert os.path.exists(report_path)
    
    with open(report_path, 'r') as f:
        report = json.load(f)
        
    assert report["coverage_gate_defined"] is True
    assert report["prior_narrow_fetch_validated"] is True
    assert report["normalized_replay_smoke_test_pass"] is True
    assert report["multiday_fetch_ready_for_user_approval"] is True
    assert report["multiday_fetch_approved"] is False
    assert report["public_fetch_performed"] is False
    assert report["replay_grade_coverage_approved"] is True
    assert report["ml_blocked_until_replay_grade_coverage"] is False
    assert report["candidate_provider"] == "coinbase_public"
    assert report["candidate_symbol"] == "BTC/USD"
    assert report["candidate_timeframe"] == "1m"
    assert report["candidate_range_max_days"] <= 7
