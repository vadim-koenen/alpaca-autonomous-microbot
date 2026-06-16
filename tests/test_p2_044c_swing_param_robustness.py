"""
tests/test_p2_044c_swing_param_robustness.py — P2-044C unit tests.
Pure stdlib + pytest. No broker, no network. Deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import swing_param_robustness as r
import equities_swing_backtest_gate as gate


def test_param_combos_only_target_gt_stop():
    combos = r.param_combos()
    assert len(combos) > 0
    assert all(c.target_atr_mult > c.stop_atr_mult for c in combos)


def test_split_in_out_anchored_no_overlap():
    bars = gate.synthetic_bars(n=100, seed=1)
    is_, oos = r.split_in_out(bars, 0.6)
    assert len(is_) == 60 and len(oos) == 40
    assert is_[-1].date != oos[0].date  # disjoint segments


def test_noise_robustness_is_not_robust():
    # Pure random walk must NOT be declared ROBUST.
    bars = gate.synthetic_bars(n=900, seed=42, drift=0.0)
    v = r.run_robustness(bars, gate.CostModel(), min_trades_oos=20, decision_grade=True)
    assert v["verdict"] in ("FRAGILE", "FALSIFIED")
    assert v["authorizes_live"] is False


def test_verdict_fields_present():
    bars = gate.synthetic_bars(n=600, seed=7)
    v = r.run_robustness(bars, gate.CostModel(), min_trades_oos=5, decision_grade=False)
    for key in ("oos_pass_fraction", "median_oos_net_ev_per_trade_bps",
                "n_param_combos", "verdict", "results"):
        assert key in v
    assert v["n_param_combos"] == len(v["results"])


def test_robust_requires_majority_and_positive_median(monkeypatch):
    # Force every combo to PASS with positive EV -> ROBUST.
    fake = {"verdict": "PASS",
            "metrics": {"net_ev_per_trade_bps": 30.0, "n_trades": 200, "profit_factor": 2.0},
            "fail_reasons": []}
    monkeypatch.setattr(gate, "evaluate", lambda *a, **k: fake)
    bars = gate.synthetic_bars(n=300, seed=2)
    v = r.run_robustness(bars, gate.CostModel(), min_trades_oos=5)
    assert v["oos_pass_fraction"] == 1.0
    assert v["verdict"] == "ROBUST"
    assert v["authorizes_live"] is False  # still never authorizes live directly


def test_falsified_when_no_pass(monkeypatch):
    fake = {"verdict": "FAIL",
            "metrics": {"net_ev_per_trade_bps": -10.0, "n_trades": 200, "profit_factor": 0.5},
            "fail_reasons": ["net_ev_positive"]}
    monkeypatch.setattr(gate, "evaluate", lambda *a, **k: fake)
    bars = gate.synthetic_bars(n=300, seed=2)
    v = r.run_robustness(bars, gate.CostModel(), min_trades_oos=5)
    assert v["verdict"] == "FALSIFIED"


def test_main_writes_outputs(tmp_path: Path):
    rc = r.main(["--out-dir", str(tmp_path)])
    assert rc == 0
    jp = tmp_path / "p2_044c_swing_param_robustness.json"
    assert jp.exists()
    loaded = json.loads(jp.read_text())
    assert loaded["schema"] == "p2_044c_swing_param_robustness/v1"
    assert loaded["decision_grade"] is False
