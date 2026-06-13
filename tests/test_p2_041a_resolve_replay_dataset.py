import os
import sys
import json
import pytest
import subprocess
from unittest import mock

# Ensure scripts directory is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts')))

from resolve_replay_dataset import get_replay_datasets, OFFLINE_REPLAY_DATASETS

def test_p2_041a_dataset_descriptor_exists_and_valid():
    assert "btc_usd_1m_coinbase_public_7day_20260603_20260610" in OFFLINE_REPLAY_DATASETS
    ds = OFFLINE_REPLAY_DATASETS["btc_usd_1m_coinbase_public_7day_20260603_20260610"]
    
    # Check core fields
    assert ds["provider"] == "coinbase_public"
    assert ds["symbol"] == "BTC/USD"
    assert ds["timeframe"] == "1m"
    assert ds["normalized_replay_candle_count"] == 10080
    assert "manifest_path_hint" in ds

def test_p2_041a_guardrails_enforced():
    ds = OFFLINE_REPLAY_DATASETS["btc_usd_1m_coinbase_public_7day_20260603_20260610"]
    
    assert ds["replay_grade_coverage_approved"] is True
    assert ds["offline_replay_only"] is True
    assert ds["ml_training_approved"] is False
    assert ds["ml_live_influence_approved"] is False
    assert ds["live_influence_approved"] is False
    assert ds["generated_data_committed"] is False

@mock.patch("os.path.exists")
def test_p2_041a_resolver_lists_dataset(mock_exists):
    # Test without checking local files
    datasets = get_replay_datasets(check_local_files=False)
    assert "btc_usd_1m_coinbase_public_7day_20260603_20260610" in datasets
    assert "local_data_found" not in datasets["btc_usd_1m_coinbase_public_7day_20260603_20260610"]

@mock.patch("os.path.exists")
def test_p2_041a_resolver_checks_local_files_found(mock_exists):
    mock_exists.return_value = True
    datasets = get_replay_datasets(check_local_files=True)
    assert datasets["btc_usd_1m_coinbase_public_7day_20260603_20260610"]["local_data_found"] is True

@mock.patch("os.path.exists")
def test_p2_041a_resolver_checks_local_files_missing(mock_exists):
    mock_exists.return_value = False
    datasets = get_replay_datasets(check_local_files=True)
    assert datasets["btc_usd_1m_coinbase_public_7day_20260603_20260610"]["local_data_found"] is False

@mock.patch("os.path.exists")
def test_p2_041a_resolver_strict_mode_fails_when_missing(mock_exists):
    mock_exists.return_value = False
    with pytest.raises(SystemExit) as excinfo:
        get_replay_datasets(check_local_files=True, strict=True)
    assert excinfo.value.code == 1

def test_p2_041a_cli_execution():
    # Test CLI execution without checking local files
    script_path = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'resolve_replay_dataset.py')
    result = subprocess.run([sys.executable, script_path], capture_output=True, text=True)
    assert result.returncode == 0
    
    parsed = json.loads(result.stdout)
    assert "btc_usd_1m_coinbase_public_7day_20260603_20260610" in parsed
