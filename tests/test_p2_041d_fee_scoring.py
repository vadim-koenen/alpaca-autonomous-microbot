import os
import sys
import json
import pytest
import tempfile

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts')))
from score_replay_after_fees import score_replay

@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d

def write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f)

def test_p2_041d_no_trade_baseline_score(temp_dir):
    base = os.path.join(temp_dir, "base.json")
    write_json(base, {"trades": 0, "gross_pnl": 0, "fees": 0, "net_pnl": 0})

    score = score_replay(base, base, output_dir=temp_dir)
    # 0 > 0 is False, so beats=False for the exact baseline vs baseline
    assert score["beats_no_trade_after_fees"] is False
    assert score["net_pnl"] == 0

def test_p2_041d_blocked_replay_fails_closed(temp_dir):
    base = os.path.join(temp_dir, "base.json")
    write_json(base, {"trades": 0, "gross_pnl": 0, "fees": 0, "net_pnl": 0})

    cand = os.path.join(temp_dir, "cand.json")
    write_json(cand, {
        "trades": 0, "gross_pnl": 0, "fees": 0, "net_pnl": 0,
        "notes": ["STUBBED: Replay blocked"]
    })

    score = score_replay(base, cand, output_dir=temp_dir)
    assert score["beats_no_trade_after_fees"] is False

def test_p2_041d_missing_report_fails_closed(temp_dir):
    base = os.path.join(temp_dir, "base.json")
    write_json(base, {"trades": 0, "gross_pnl": 0, "fees": 0, "net_pnl": 0})

    score = score_replay(base, "nonexistent.json", output_dir=temp_dir)
    assert score["beats_no_trade_after_fees"] is False

def test_p2_041d_malformed_report_fails_closed(temp_dir):
    base = os.path.join(temp_dir, "base.json")
    write_json(base, {"trades": 0, "gross_pnl": 0, "fees": 0, "net_pnl": 0})

    cand = os.path.join(temp_dir, "cand.json")
    with open(cand, "w") as f:
        f.write("{ bad json }")

    score = score_replay(base, cand, output_dir=temp_dir)
    assert score["beats_no_trade_after_fees"] is False

def test_p2_041d_missing_fees_fails_closed(temp_dir):
    base = os.path.join(temp_dir, "base.json")
    write_json(base, {"trades": 0, "gross_pnl": 0, "fees": 0, "net_pnl": 0})

    cand = os.path.join(temp_dir, "cand.json")
    write_json(cand, {"trades": 1, "gross_pnl": 5, "fees": 0, "net_pnl": 5}) # No fees for 1 trade

    score = score_replay(base, cand, output_dir=temp_dir)
    assert score["beats_no_trade_after_fees"] is False

def test_p2_041d_positive_gross_negative_net_fails(temp_dir):
    base = os.path.join(temp_dir, "base.json")
    write_json(base, {"trades": 0, "gross_pnl": 0, "fees": 0, "net_pnl": 0})

    cand = os.path.join(temp_dir, "cand.json")
    write_json(cand, {"trades": 1, "gross_pnl": 5, "fees": 6, "net_pnl": -1})

    score = score_replay(base, cand, output_dir=temp_dir)
    assert score["beats_no_trade_after_fees"] is False

def test_p2_041d_beats_no_trade_true_when_net_positive(temp_dir):
    base = os.path.join(temp_dir, "base.json")
    write_json(base, {"trades": 0, "gross_pnl": 0, "fees": 0, "net_pnl": 0})

    cand = os.path.join(temp_dir, "cand.json")
    write_json(cand, {"trades": 1, "gross_pnl": 10, "fees": 2, "net_pnl": 8})

    score = score_replay(base, cand, output_dir=temp_dir)
    assert score["beats_no_trade_after_fees"] is True
