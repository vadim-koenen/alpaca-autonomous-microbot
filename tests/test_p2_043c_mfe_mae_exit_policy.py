"""
Tests for P2-043C: MFE/MAE Exit Redesign.
Verifies the analysis parameter derivation and deterministic exit policy.
"""

from __future__ import annotations

import pytest
from mfe_mae_exit_analysis import (
    PositionAnalysis,
    DerivedExitParameters,
    FeeModelAssumptions,
    derive_parameters_for_group,
)
from exit_policy_mfe_mae import decide_exit


def test_derive_parameters_requires_minimum_samples() -> None:
    analyses = [
        PositionAnalysis("BTC/USD", "momentum", 2.0, -1.0, 30.0),
        PositionAnalysis("BTC/USD", "momentum", 3.0, -0.5, 45.0),
    ]
    # Default min_samples = 5
    params = derive_parameters_for_group(analyses)
    assert params.is_valid is False
    assert params.take_profit_pct == 0.0

    # With min_samples = 2
    params_valid = derive_parameters_for_group(analyses, min_samples=2)
    assert params_valid.is_valid is True


def test_derive_parameters_logic() -> None:
    # 10 samples so percentiles are easy to mentally map
    analyses = []
    for i in range(1, 11):
        # MFE: 1.0, 2.0, ... 10.0
        # MAE: -1.0, -2.0, ... -10.0
        # Time: 10, 20, ... 100
        analyses.append(
            PositionAnalysis("BTC/USD", "momentum", i * 1.0, -i * 1.0, i * 10.0)
        )

    # Note: 
    # TP = 40th percentile of MFE => approx 4.0
    # SL = 20th percentile of MAE => approx -8.0 (but capped at -5.0)
    # Time = 80th percentile of Time => approx 80.0
    
    # We use a zero-fee model so TP is not artificially raised by minimum targets
    fee_model = FeeModelAssumptions(0.0, 0.0, 0.0)
    params = derive_parameters_for_group(analyses, fee_model=fee_model, min_samples=5)
    
    assert params.is_valid is True
    assert params.take_profit_pct == 4.4
    assert params.invalidation_pct == -5.0  # Hit the -5.0% sane cap (instead of -2.2)
    assert params.adaptive_max_hold_minutes == 88.0


def test_tp_respects_net_of_fee_margin() -> None:
    analyses = []
    for i in range(1, 11):
        # MFE is very small (0.1 to 1.0)
        analyses.append(
            PositionAnalysis("BTC/USD", "momentum", i * 0.1, -1.0, 30.0)
        )
        
    fee_model = FeeModelAssumptions(
        entry_fee_pct=0.60,
        exit_fee_pct=0.60,
        spread_slippage_pct=0.10,
    )
    # Total cost = 1.30%. Margin multiplier = 1.5 => minimum target = 1.95%.
    
    params = derive_parameters_for_group(analyses, fee_model=fee_model, min_samples=5)
    
    assert params.is_valid is True
    # 40th percentile of MFE is 0.4%, but TP should be forced up to 1.95% by fee margin
    assert params.take_profit_pct == pytest.approx(1.95)


def test_decide_exit_invalidation() -> None:
    params = DerivedExitParameters(
        take_profit_pct=3.0,
        invalidation_pct=-2.0,
        adaptive_max_hold_minutes=60.0,
        sample_size=10,
        is_valid=True,
    )
    
    pos = {"entry_price": 100.0, "side": "buy"}
    
    # -1.5% -> Hold
    action, _ = decide_exit(pos, 98.5, 30.0, params)
    assert action is None
    
    # -2.5% -> Invalidate
    action, reason = decide_exit(pos, 97.5, 30.0, params)
    assert action == "invalidation"
    assert "invalidation hit" in reason


def test_decide_exit_take_profit() -> None:
    params = DerivedExitParameters(
        take_profit_pct=3.0,
        invalidation_pct=-2.0,
        adaptive_max_hold_minutes=60.0,
        sample_size=10,
        is_valid=True,
    )
    
    pos = {"entry_price": 100.0, "side": "buy"}
    
    # +2.5% -> Hold
    action, _ = decide_exit(pos, 102.5, 30.0, params)
    assert action is None
    
    # +3.5% -> Take profit
    action, reason = decide_exit(pos, 103.5, 30.0, params)
    assert action == "take_profit"
    assert "take-profit hit" in reason


def test_decide_exit_adaptive_timeout() -> None:
    params = DerivedExitParameters(
        take_profit_pct=3.0,
        invalidation_pct=-2.0,
        adaptive_max_hold_minutes=60.0,
        sample_size=10,
        is_valid=True,
    )
    
    pos = {"entry_price": 100.0, "side": "buy"}
    
    # 59 mins -> Hold
    action, _ = decide_exit(pos, 100.0, 59.0, params)
    assert action is None
    
    # 61 mins -> Timeout
    action, reason = decide_exit(pos, 100.0, 61.0, params)
    assert action == "adaptive_timeout"
    assert "adaptive max-hold" in reason


def test_decide_exit_short_position() -> None:
    params = DerivedExitParameters(
        take_profit_pct=3.0,
        invalidation_pct=-2.0,
        adaptive_max_hold_minutes=60.0,
        sample_size=10,
        is_valid=True,
    )
    
    pos = {"entry_price": 100.0, "side": "short"}
    
    # Short: price goes UP -> negative P/L. 102.5 = -2.5% -> Invalidation
    action, reason = decide_exit(pos, 102.5, 30.0, params)
    assert action == "invalidation"
    
    # Short: price goes DOWN -> positive P/L. 96.5 = +3.5% -> Take profit
    action, reason = decide_exit(pos, 96.5, 30.0, params)
    assert action == "take_profit"

