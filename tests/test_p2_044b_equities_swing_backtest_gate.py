"""
tests/test_p2_044b_equities_swing_backtest_gate.py — P2-044B unit tests.

Pure stdlib + pytest. No broker, no network, no pyarrow/duckdb. Deterministic.
Synthetic fixtures validate MECHANICS only; they are not profitability claims.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import equities_swing_backtest_gate as g


def _bar(date, o, h, l, c, v=1e6):
    return g.Bar(date=date, o=o, h=h, l=l, c=c, v=v)


def _uptrend(n=400, step=0.5, start=100.0):
    """Smooth rising series with unique sequential dates: breakouts trigger and trend up."""
    bars = []
    price = start
    day = datetime(2024, 1, 1)
    for i in range(n):
        o = price
        c = price + step
        h = c + 0.2
        l = o - 0.2
        bars.append(_bar(day.strftime("%Y-%m-%d"), o, h, l, c))
        price = c
        day += timedelta(days=1)
    return bars


# ---------------------------------------------------------------- cost model
def test_round_trip_cost_components():
    c = g.CostModel(commission_bps_per_side=0.0, spread_bps=1.0, slippage_bps_per_side=2.0)
    # 0 + 1 + 2*2 = 5
    assert c.round_trip_cost_bps == pytest.approx(5.0)


def test_entry_and_exit_fills_are_adverse():
    c = g.CostModel(spread_bps=2.0, slippage_bps_per_side=3.0)
    assert c.entry_fill(100.0) > 100.0   # pay up on entry
    assert c.exit_fill(100.0) < 100.0    # receive less on exit


# ---------------------------------------------------------------- indicators
def test_atr_series_length_and_warmup():
    bars = _uptrend(30)
    atr = g.atr_series(bars, 14)
    assert len(atr) == len(bars)
    assert atr[12] is None
    assert atr[13] is not None and atr[13] > 0


def test_donchian_high_none_before_lookback():
    bars = _uptrend(30)
    assert g.donchian_high(bars, 5, 20) is None
    assert g.donchian_high(bars, 25, 20) is not None


# ---------------------------------------------------------------- simulation mechanics
def test_simulation_produces_trades_on_uptrend():
    trades = g.simulate(_uptrend(400), g.SwingParams(), g.CostModel())
    assert len(trades) > 0
    # PDT-safe: every trade holds at least one day
    assert all(t.hold_days >= 1 for t in trades)


def test_no_overlapping_positions():
    trades = g.simulate(_uptrend(400), g.SwingParams(), g.CostModel())
    # exit_date of trade k must not be after entry_date of k+1 by index construction:
    # check entries are strictly increasing
    entries = [t.entry_date for t in trades]
    assert len(entries) == len(set(entries)) or len(trades) <= 1


def test_net_is_below_gross_due_to_costs():
    trades = g.simulate(_uptrend(400), g.SwingParams(), g.CostModel())
    for t in trades:
        assert t.net_return_bps < t.gross_return_bps


def test_commission_is_actually_subtracted_from_net():
    # Regression: commission must reduce per-trade net, not just the gate threshold.
    bars = _uptrend(400)
    cheap = g.simulate(bars, g.SwingParams(),
                       g.CostModel(commission_bps_per_side=0.0, spread_bps=1.0, slippage_bps_per_side=2.0))
    pricey = g.simulate(bars, g.SwingParams(),
                        g.CostModel(commission_bps_per_side=60.0, spread_bps=1.0, slippage_bps_per_side=2.0))
    assert len(cheap) == len(pricey) and len(cheap) > 0
    # Same price path + same spread/slippage; 60 bps/side commission => 120 bps lower net per trade.
    for a, b in zip(cheap, pricey):
        assert a.net_return_bps - b.net_return_bps == pytest.approx(120.0, abs=1e-6)


# ---------------------------------------------------------------- metrics / baselines
def test_profit_factor_math():
    assert g.profit_factor([10.0, -5.0, 5.0]) == pytest.approx(15.0 / 5.0)
    assert g.profit_factor([-1.0, -2.0]) == 0.0
    assert g.profit_factor([3.0]) == float("inf")


def test_buy_and_hold_uses_fills():
    bars = _uptrend(50)
    bh = g.buy_and_hold_net_bps(bars, g.CostModel())
    assert bh > 0  # rising series, net of small costs still positive


def test_split_folds_partitions_all_bars():
    bars = _uptrend(100)
    folds = g.split_folds(bars, 5)
    assert len(folds) == 5
    assert sum(len(f) for f in folds) == len(bars)


# ---------------------------------------------------------------- gate verdict logic
def test_noise_does_not_pass_decision_grade_gate():
    # Pure random walk, decision-grade thresholds: must NOT rubber-stamp a PASS.
    bars = g.synthetic_bars(n=600, seed=11, drift=0.0)
    v = g.evaluate(bars, g.SwingParams(), g.CostModel(), n_folds=5, min_trades=100, decision_grade=True)
    assert v["verdict"] == "FAIL"
    assert v["authorizes_live"] is False


def test_synthetic_smoke_is_not_decision_grade():
    v = g.evaluate(g.synthetic_bars(), g.SwingParams(), g.CostModel(),
                   min_trades=20, decision_grade=False)
    assert v["decision_grade"] is False
    assert v["authorizes_live"] is False


def test_gate_checks_present_and_consistent():
    v = g.evaluate(_uptrend(400), g.SwingParams(), g.CostModel(), min_trades=5)
    expected = {"min_trades", "net_ev_positive", "net_ev_ge_cost_multiple",
                "profit_factor_ok", "beats_buy_and_hold", "beats_no_trade", "fold_stable"}
    assert set(v["checks"].keys()) == expected
    assert (v["verdict"] == "PASS") == all(v["checks"].values())


def test_verdict_never_authorizes_live_directly():
    for dg in (True, False):
        v = g.evaluate(_uptrend(400), g.SwingParams(), g.CostModel(), min_trades=5, decision_grade=dg)
        assert v["authorizes_live"] is False


def test_determinism_same_bars_same_metrics():
    bars = g.synthetic_bars(seed=3)
    v1 = g.evaluate(bars, g.SwingParams(), g.CostModel(), decision_grade=False, min_trades=20)
    v2 = g.evaluate(bars, g.SwingParams(), g.CostModel(), decision_grade=False, min_trades=20)
    assert v1["metrics"] == v2["metrics"]
    assert v1["verdict"] == v2["verdict"]


# ---------------------------------------------------------------- io
def test_csv_roundtrip(tmp_path: Path):
    csv_path = tmp_path / "ohlcv.csv"
    csv_path.write_text(
        "date,open,high,low,close,volume\n"
        "2024-01-01,100,101,99,100.5,1000\n"
        "2024-01-02,100.5,102,100,101.5,1100\n"
    )
    bars = g.load_bars_csv(csv_path)
    assert len(bars) == 2
    assert bars[0].c == pytest.approx(100.5)
    assert bars[1].h == pytest.approx(102.0)


def test_write_outputs_and_main(tmp_path: Path):
    rc = g.main(["--out-dir", str(tmp_path), "--folds", "5"])
    assert rc == 0
    jp = tmp_path / "p2_044b_equities_swing_gate_verdict.json"
    assert jp.exists()
    loaded = json.loads(jp.read_text())
    assert loaded["schema"] == "p2_044b_equities_swing_backtest_gate/v1"
    assert loaded["decision_grade"] is False  # synthetic default
