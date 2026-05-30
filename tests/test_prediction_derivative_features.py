import math
import pytest
from shadow_learner.derivative_features import (
    calculate_return_pct,
    calculate_velocity,
    calculate_acceleration,
    calculate_volatility,
    calculate_high_low_range_pct,
)

def test_calculate_return_pct():
    assert calculate_return_pct(100.0, 101.0) == 1.0
    assert calculate_return_pct(100.0, 99.0) == -1.0
    assert calculate_return_pct(0, 100.0) is None
    assert calculate_return_pct(None, 100.0) is None

def test_calculate_velocity():
    prices = [100.0, 102.0, 104.0]
    # (104 - 100) / 100 * 100 = 4.0% return
    # 4.0 / 2 minutes = 2.0 velocity
    assert calculate_velocity(prices, 2.0) == 2.0
    assert calculate_velocity([100.0], 1.0) is None
    assert calculate_velocity(prices, 0) is None

def test_calculate_acceleration():
    # v_start = 1.0, v_end = 2.0, window = 2.0
    # (2.0 - 1.0) / 2.0 = 0.5
    assert calculate_acceleration(1.0, 2.0, 2.0) == 0.5
    assert calculate_acceleration(None, 1.0, 1.0) is None

def test_calculate_volatility():
    prices = [100.0, 101.0, 100.0, 101.0]
    # log returns: log(1.01), log(100/101), log(1.01)
    # roughly 0.00995, -0.00995, 0.00995
    vol = calculate_volatility(prices)
    assert vol > 0
    assert calculate_volatility([100.0, 101.0]) is None

def test_calculate_high_low_range_pct():
    highs = [105.0, 110.0, 108.0]
    lows = [100.0, 102.0, 95.0]
    # (110 - 95) / 100 * 100 = 15.0%
    assert calculate_high_low_range_pct(highs, lows, 100.0) == 15.0
    assert calculate_high_low_range_pct([], [], 100.0) is None
