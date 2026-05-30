"""Advisory-only derivative market feature calculations for shadow learning.

These functions compute derived features from raw price observations,
snapshots, and outcomes. They are for advisory and offline research only.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

from .outcome_labeler import PriceObservation


def calculate_return_pct(start_price: float, end_price: float) -> float | None:
    if not start_price or start_price <= 0:
        return None
    return ((end_price - start_price) / start_price) * 100.0


def calculate_velocity(prices: Sequence[float], window_minutes: float) -> float | None:
    """Return change per minute over the window."""
    if len(prices) < 2 or window_minutes <= 0:
        return None
    ret = calculate_return_pct(prices[0], prices[-1])
    if ret is None:
        return None
    return ret / window_minutes


def calculate_acceleration(
    v_start: float | None, v_end: float | None, window_minutes: float
) -> float | None:
    """Velocity change per minute."""
    if v_start is None or v_end is None or window_minutes <= 0:
        return None
    return (v_end - v_start) / window_minutes


def calculate_volatility(prices: Sequence[float]) -> float | None:
    """Standard deviation of log returns."""
    if len(prices) < 3:
        return None
    returns = []
    for i in range(1, len(prices)):
        if prices[i] > 0 and prices[i - 1] > 0:
            returns.append(math.log(prices[i] / prices[i - 1]))
    if not returns:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    return math.sqrt(variance)


def calculate_high_low_range_pct(highs: Sequence[float], lows: Sequence[float], anchor_price: float) -> float | None:
    if not highs or not lows or anchor_price <= 0:
        return None
    max_h = max(highs)
    min_l = min(lows)
    return ((max_h - min_l) / anchor_price) * 100.0


def calculate_spread_trend(spreads: Sequence[float]) -> float | None:
    """Simple linear trend or change in spreads."""
    if len(spreads) < 2:
        return None
    return spreads[-1] - spreads[0]


def calculate_mfe_mae_ratio(mfe: float | None, mae: float | None) -> float | None:
    if mfe is None or mae is None or mae == 0:
        return None
    # mae is usually negative in outcomes, but we want a ratio of magnitudes
    return abs(mfe) / abs(mae)


def calculate_win_rate(outcomes: Iterable[float]) -> float | None:
    count = 0
    wins = 0
    for ret in outcomes:
        count += 1
        if ret > 0:
            wins += 1
    return wins / count if count > 0 else None


def calculate_brier_score(predictions: Iterable[float], actuals: Iterable[int]) -> float | None:
    # actuals should be 0 or 1
    sum_sq_err = 0.0
    count = 0
    for p, a in zip(predictions, actuals):
        sum_sq_err += (p - a) ** 2
        count += 1
    return sum_sq_err / count if count > 0 else None
