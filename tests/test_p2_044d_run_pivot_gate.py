"""
tests/test_p2_044d_run_pivot_gate.py — P2-044D orchestrator tests.
Pure stdlib + pytest. No broker, no network. Deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_pivot_gate as orch
import equities_swing_backtest_gate as gate
import swing_param_robustness as rob


def test_synthetic_is_no_go():
    bars = gate.synthetic_bars(n=900, seed=5)
    d = orch.run_decision(bars, gate.CostModel(), decision_grade=False,
                          min_trades_gate=20, min_trades_oos=5)
    assert d["verdict"] == "NO_GO"
    assert d["authorizes_live"] is False


def test_go_to_paper_requires_decision_grade(monkeypatch):
    # Force ROBUST + PASS but decision_grade False -> still NO_GO.
    monkeypatch.setattr(rob, "run_robustness",
                        lambda *a, **k: {"verdict": "ROBUST", "oos_pass_fraction": 0.8,
                                         "median_oos_net_ev_per_trade_bps": 20.0})
    monkeypatch.setattr(gate, "evaluate",
                        lambda *a, **k: {"verdict": "PASS",
                                         "metrics": {"n_trades": 200, "net_ev_per_trade_bps": 25.0,
                                                     "profit_factor": 1.8},
                                         "fail_reasons": []})
    bars = gate.synthetic_bars(n=300, seed=1)
    d = orch.run_decision(bars, gate.CostModel(), decision_grade=False)
    assert d["verdict"] == "NO_GO"


def test_go_to_paper_when_robust_and_pass_and_real(monkeypatch):
    monkeypatch.setattr(rob, "run_robustness",
                        lambda *a, **k: {"verdict": "ROBUST", "oos_pass_fraction": 0.8,
                                         "median_oos_net_ev_per_trade_bps": 20.0})
    monkeypatch.setattr(gate, "evaluate",
                        lambda *a, **k: {"verdict": "PASS",
                                         "metrics": {"n_trades": 200, "net_ev_per_trade_bps": 25.0,
                                                     "profit_factor": 1.8},
                                         "fail_reasons": []})
    bars = gate.synthetic_bars(n=300, seed=1)
    d = orch.run_decision(bars, gate.CostModel(), decision_grade=True)
    assert d["verdict"] == "GO_TO_PAPER"
    assert d["authorizes_live"] is False  # GO_TO_PAPER is never live


def test_fragile_robustness_blocks_go(monkeypatch):
    monkeypatch.setattr(rob, "run_robustness",
                        lambda *a, **k: {"verdict": "FRAGILE", "oos_pass_fraction": 0.3,
                                         "median_oos_net_ev_per_trade_bps": 5.0})
    monkeypatch.setattr(gate, "evaluate",
                        lambda *a, **k: {"verdict": "PASS",
                                         "metrics": {"n_trades": 200, "net_ev_per_trade_bps": 25.0,
                                                     "profit_factor": 1.8},
                                         "fail_reasons": []})
    bars = gate.synthetic_bars(n=300, seed=1)
    d = orch.run_decision(bars, gate.CostModel(), decision_grade=True)
    assert d["verdict"] == "NO_GO"
    assert any("robustness" in r for r in d["reasons"])


def test_main_writes_outputs(tmp_path: Path):
    rc = orch.main(["--out-dir", str(tmp_path)])
    assert rc == 0
    jp = tmp_path / "p2_044d_pivot_gate_decision.json"
    assert jp.exists()
    loaded = json.loads(jp.read_text())
    assert loaded["schema"] == "p2_044d_pivot_gate_decision/v1"
    assert loaded["authorizes_live"] is False
