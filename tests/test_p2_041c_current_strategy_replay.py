import os
import sys
import json
import pytest
from unittest import mock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts')))
from run_current_strategy_replay_offline import run_current_strategy_replay

def test_p2_041c_strategy_replay_stub_metrics():
    report = run_current_strategy_replay("btc_usd_1m_coinbase_public_7day_20260603_20260610", output_dir="/tmp")

    assert report["trades"] == 0
    assert report["gross_pnl"] == 0.0
    assert report["fees"] == 0.0
    assert report["net_pnl"] == 0.0
    assert "STUBBED:" in report["notes"][0]

def test_p2_041c_strategy_replay_enforces_offline_guardrails():
    report = run_current_strategy_replay("btc_usd_1m_coinbase_public_7day_20260603_20260610", output_dir="/tmp")

    assert report["ml_training_started"] is False
    assert report["live_influence_enabled"] is False

@mock.patch("sys.exit")
def test_p2_041c_strategy_replay_fails_on_unknown_dataset(mock_exit):
    run_current_strategy_replay("unknown_dataset", output_dir="/tmp")
    mock_exit.assert_called_with(1)
