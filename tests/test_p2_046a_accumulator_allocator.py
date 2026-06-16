"""P2-046A — accumulator/allocator backtest tests (offline, pure stdlib)."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import equities_swing_backtest_gate as gate
import accumulator_allocator as acc


def bars_from_closes(closes, start="2024-01-01"):
    """Deterministic Bar list from a close series (o=h=l=c)."""
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    out = []
    for i, c in enumerate(closes):
        day = (d0 + timedelta(days=i)).isoformat()
        out.append(gate.Bar(date=day, o=c, h=c, l=c, c=c, v=1.0))
    return out


def v_shape(n=300, top=100.0, bottom=40.0):
    """Decline to a trough then recover above start (monotonic V)."""
    half = n // 2
    down = [top + (bottom - top) * (i / half) for i in range(half)]
    up = [bottom + (top * 1.5 - bottom) * (i / (n - half)) for i in range(n - half)]
    return down + up


def oscillate(n=320, base=100.0, amp=0.30, cycles=8):
    """Mean-reverting oscillation around `base` — the canonical case where buying
    more at the troughs (below trend) and less at the peaks lowers the cost basis."""
    return [base * (1 + amp * math.sin(2 * math.pi * cycles * i / n)) for i in range(n)]


# --- pure helpers -------------------------------------------------------------

def test_moving_average_causal_warmup_and_value():
    closes = [float(i) for i in range(1, 11)]  # 1..10
    assert acc.moving_average_causal(closes, 2, 3) is None      # not warmed
    # MA at i=5 over prior 3 closes (indices 2,3,4 -> values 3,4,5) = 4.0
    assert acc.moving_average_causal(closes, 5, 3) == 4.0


def test_moving_average_is_strictly_causal():
    # MA must NOT include the close at index i (no lookahead).
    closes = [10.0] * 5 + [1000.0]  # spike at last
    assert acc.moving_average_causal(closes, 5, 5) == 10.0       # excludes the spike


def test_valuation_multiplier_bands():
    assert acc.valuation_multiplier(1.2) == 0.5    # well above trend
    assert acc.valuation_multiplier(1.0) == 1.0    # near trend
    assert acc.valuation_multiplier(0.85) == 2.0   # below trend
    assert acc.valuation_multiplier(0.5) == 3.0    # deep below trend


def test_common_calendar_intersection():
    a = bars_from_closes([1, 2, 3, 4])
    b = bars_from_closes([5, 6, 7])  # shorter -> 3 common dates
    cal = acc.common_calendar({"A": a, "B": b})
    assert cal == [x.date for x in a[:3]]


def test_max_drawdown():
    assert acc._max_drawdown([1, 2, 3]) == 0.0
    assert acc._max_drawdown([100, 50, 75]) == 0.5  # peak 100 -> trough 50


# --- simulation invariants ----------------------------------------------------

def test_budget_neutral_plain_vs_overlay():
    series = {"X": bars_from_closes(v_shape())}
    plain = acc.simulate(series, {"X": 1.0}, mode="plain", ma_window=20)
    overlay = acc.simulate(series, {"X": 1.0}, mode="overlay", ma_window=20)
    # SAME contributions -> fair test
    assert abs(plain.total_contributed - overlay.total_contributed) < 1e-9


def test_plain_dca_deploys_everything():
    series = {"X": bars_from_closes(v_shape())}
    plain = acc.simulate(series, {"X": 1.0}, mode="plain", ma_window=20, buy_cost_bps=0)
    assert plain.leftover_cash < 1e-6  # plain never banks


def test_overlay_lowers_cost_basis_on_mean_reversion():
    series = {"X": bars_from_closes(oscillate())}
    plain = acc.simulate(series, {"X": 1.0}, mode="plain", ma_window=20)
    overlay = acc.simulate(series, {"X": 1.0}, mode="overlay", ma_window=20)
    # buying more at the troughs -> strictly lower dollar-weighted cost basis
    assert overlay.avg_cost["X"] < plain.avg_cost["X"]


def test_overlay_never_overspends_cash():
    series = {"X": bars_from_closes(v_shape())}
    overlay = acc.simulate(series, {"X": 1.0}, mode="overlay", ma_window=20)
    assert overlay.leftover_cash >= -1e-9
    assert overlay.deployed <= overlay.total_contributed + 1e-9


def test_determinism():
    series = {"X": bars_from_closes(v_shape())}
    r1 = acc.simulate(series, {"X": 1.0}, mode="overlay", ma_window=20)
    r2 = acc.simulate(series, {"X": 1.0}, mode="overlay", ma_window=20)
    assert r1 == r2


# --- evaluate / verdict -------------------------------------------------------

def test_verdict_insufficient_data():
    series = {"X": bars_from_closes(v_shape(n=40))}  # far below MIN_PERIODS*PERIOD_DAYS
    r = acc.evaluate(series, {"X": 1.0}, ma_window=20)
    assert r["verdict"] == "INSUFFICIENT_DATA"
    assert r["authorizes_live"] is False


def test_verdict_overlay_helps_on_mean_reverting_basket():
    series = {"A": bars_from_closes(oscillate(cycles=8)),
              "B": bars_from_closes(oscillate(cycles=6, base=80.0))}
    r = acc.evaluate(series, {"A": 0.5, "B": 0.5}, ma_window=20)
    assert r["verdict"] == "VALUATION_OVERLAY_HELPS"
    assert r["overlay_vs_plain_rel_gain"] >= acc.OVERLAY_HELP_MARGIN
    assert r["authorizes_live"] is False


def test_verdict_no_benefit_on_pure_uptrend():
    # Monotonic uptrend: price always >= trend -> overlay just banks cash & lags.
    up = [100.0 * (1.003 ** i) for i in range(300)]
    series = {"X": bars_from_closes(up)}
    r = acc.evaluate(series, {"X": 1.0}, ma_window=20)
    assert r["verdict"] in ("NO_BENEFIT", "VALUATION_OVERLAY_HELPS")
    # On a pure uptrend the overlay should NOT meaningfully beat plain.
    assert r["overlay_vs_plain_rel_gain"] < acc.OVERLAY_HELP_MARGIN or r["verdict"] == "NO_BENEFIT"


def test_evaluate_schema_and_no_live():
    series = {"X": bars_from_closes(v_shape())}
    r = acc.evaluate(series, {"X": 1.0}, ma_window=20)
    for k in ("schema", "verdict", "results", "weights", "authorizes_live", "explanation"):
        assert k in r
    assert r["authorizes_live"] is False
    assert "plain_dca" in r["results"] and "overlay_dca" in r["results"]


def test_parse_csv_args():
    assert acc._parse_csv_args(["BTC=a.csv", "spy=b.csv"]) == {"BTC": "a.csv", "SPY": "b.csv"}
