"""P2-046B — accumulator/allocator decision-engine tests (offline, pure stdlib)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import allocator_engine as eng
from allocator_engine import Order, Portfolio, BUY, SELL


PRICES = {"BTC": 100.0, "SPY": 50.0, "GLD": 20.0}
WEIGHTS = {"BTC": 0.5, "SPY": 0.3, "GLD": 0.2}


def test_normalize_weights():
    w = eng.normalize_weights({"A": 1, "B": 3})
    assert abs(w["A"] - 0.25) < 1e-9 and abs(w["B"] - 0.75) < 1e-9


def test_normalize_weights_rejects_nonpositive():
    try:
        eng.normalize_weights({"A": 0, "B": 0})
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_portfolio_value_and_weights():
    p = Portfolio(holdings={"BTC": 1.0, "SPY": 2.0}, cash=10.0)
    prices = {"BTC": 100.0, "SPY": 50.0}
    assert p.value(prices) == 100.0 + 100.0 + 10.0
    cw = eng.current_weights(p, prices)
    assert abs(cw["BTC"] - 0.5) < 1e-9 and abs(cw["SPY"] - 0.5) < 1e-9


def test_empty_portfolio_dca_splits_by_weight():
    p = Portfolio()
    orders = eng.plan_period(p, PRICES, WEIGHTS, contribution=100.0)
    buys = {o.symbol: o.dollars for o in orders if o.side == BUY}
    # empty portfolio: every asset is underweight in equal proportion -> split by weight
    assert abs(buys["BTC"] - 50.0) < 1e-6
    assert abs(buys["SPY"] - 30.0) < 1e-6
    assert abs(buys["GLD"] - 20.0) < 1e-6
    assert all(o.side == BUY for o in orders)


def test_contribution_funded_rebalance_targets_underweight():
    # BTC hugely overweight; new money should go to SPY/GLD, NOT to BTC, and NO sell.
    p = Portfolio(holdings={"BTC": 10.0, "SPY": 0.0, "GLD": 0.0})  # $1000 all BTC
    orders = eng.plan_period(p, PRICES, WEIGHTS, contribution=100.0, allow_sell=False)
    by = {o.symbol: o for o in orders}
    assert "BTC" not in by or by["BTC"].dollars < 1e-9   # no BTC buy
    assert all(o.side == BUY for o in orders)              # nothing sold
    assert by["SPY"].dollars > 0 and by["GLD"].dollars > 0
    assert by["SPY"].reason == "rebalance_buy"


def test_no_sell_unless_allowed():
    p = Portfolio(holdings={"BTC": 100.0})  # wildly overweight BTC
    orders = eng.plan_period(p, PRICES, WEIGHTS, contribution=10.0, allow_sell=False)
    assert all(o.side == BUY for o in orders)


def test_sell_trims_overweight_beyond_band():
    p = Portfolio(holdings={"BTC": 100.0})  # $10000 all BTC, target 50%
    orders = eng.plan_period(p, PRICES, WEIGHTS, contribution=0.0, allow_sell=True, band=0.05)
    sells = [o for o in orders if o.side == SELL]
    assert sells and sells[0].symbol == "BTC"


def test_within_band_no_sell():
    # perfectly on target -> no sells even with allow_sell
    p = Portfolio(holdings={"BTC": 5.0, "SPY": 6.0, "GLD": 10.0})  # 500/300/200 = exact weights
    orders = eng.plan_period(p, PRICES, WEIGHTS, contribution=0.0, allow_sell=True, band=0.05)
    assert not [o for o in orders if o.side == SELL]


def test_apply_orders_conserves_value_minus_costs():
    p = Portfolio(cash=100.0)
    orders = eng.plan_period(p, PRICES, WEIGHTS, contribution=100.0)
    p2 = eng.apply_orders(p, orders, PRICES, cost_bps=0.0)
    # zero cost: post-trade value equals pre-trade value
    assert abs(p2.value(PRICES) - 100.0) < 1e-6
    assert abs(p2.cash) < 1e-6  # fully deployed


def test_apply_orders_costs_reduce_value():
    p = Portfolio(cash=100.0)
    orders = eng.plan_period(p, PRICES, WEIGHTS, contribution=100.0)
    p2 = eng.apply_orders(p, orders, PRICES, cost_bps=50.0)
    assert p2.value(PRICES) < 100.0  # cost haircut


def test_apply_orders_never_oversells():
    p = Portfolio(holdings={"BTC": 1.0})
    big_sell = [Order("BTC", SELL, dollars=99999.0, est_units=999.0)]
    p2 = eng.apply_orders(p, big_sell, {"BTC": 100.0}, cost_bps=0.0)
    assert p2.holdings["BTC"] >= -1e-9  # cannot go negative


def test_valuation_tilt_is_capital_neutral():
    p = Portfolio()
    tilt = {"BTC": 2.0, "SPY": 1.0, "GLD": 0.5}  # overweight cheap BTC
    orders = eng.plan_period(p, PRICES, WEIGHTS, contribution=100.0, valuation_tilt=tilt)
    total = sum(o.dollars for o in orders if o.side == BUY)
    assert abs(total - 100.0) < 1e-6  # still deploys exactly the contribution


def test_determinism():
    p = Portfolio(holdings={"BTC": 3.0, "SPY": 1.0}, cash=5.0)
    a = eng.plan_period(p, PRICES, WEIGHTS, contribution=40.0, allow_sell=True, band=0.1)
    b = eng.plan_period(p, PRICES, WEIGHTS, contribution=40.0, allow_sell=True, band=0.1)
    assert a == b


def test_summarize_plan():
    orders = [Order("BTC", BUY, 50.0, 0.5), Order("SPY", SELL, 10.0, 0.2)]
    s = eng.summarize_plan(orders)
    assert s["n_orders"] == 2 and s["buy_dollars"] == 50.0 and s["sell_dollars"] == 10.0
