import os
import sys
import json
import pytest
from unittest import mock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts')))
from run_no_trade_baseline_replay import run_no_trade_baseline

def test_p2_041b_baseline_produces_zero_metrics():
    report = run_no_trade_baseline("btc_usd_1m_coinbase_public_7day_20260603_20260610", check_local_files=False, output_dir="/tmp")

    assert report["trades"] == 0
    assert report["gross_pnl"] == 0.0
    assert report["fees"] == 0.0
    assert report["net_pnl"] == 0.0

def test_p2_041b_baseline_enforces_offline_guardrails():
    report = run_no_trade_baseline("btc_usd_1m_coinbase_public_7day_20260603_20260610", check_local_files=False, output_dir="/tmp")

    assert report["ml_training_started"] is False
    assert report["live_influence_enabled"] is False

@mock.patch("sys.exit")
def test_p2_041b_baseline_fails_on_unknown_dataset(mock_exit):
    run_no_trade_baseline("unknown_dataset", check_local_files=False, output_dir="/tmp")
    mock_exit.assert_called_with(1)
