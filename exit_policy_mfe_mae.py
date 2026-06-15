"""
P2-043C: MFE/MAE Exit Policy
Deterministic policy applying data-driven MFE/MAE parameters to open positions.
"""

from typing import Tuple, Optional, Any
from mfe_mae_exit_analysis import DerivedExitParameters


def decide_exit(
    position: Any,
    current_price: float,
    elapsed_minutes: float,
    params: DerivedExitParameters,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Evaluates whether a position should be exited based on MFE/MAE parameters.

    Args:
        position: The position dictionary from session.open_positions
        current_price: The current quote price
        elapsed_minutes: Time since the entry in minutes
        params: The DerivedExitParameters from the MFE/MAE analysis module

    Returns:
        (action, reason) where action is one of 'take_profit', 'invalidation',
        'adaptive_timeout', or None if hold.
    """
    entry_price = position.get("entry_price", 0.0)
    if entry_price <= 0 or current_price <= 0:
        return None, None

    side = position.get("side", "buy")

    # Calculate unrealized percentage
    if side == "buy":
        unrealized_pct = (current_price - entry_price) / entry_price * 100.0
    else:
        unrealized_pct = (entry_price - current_price) / entry_price * 100.0

    # 1. Invalidation (Stop Loss)
    # Check if adverse excursion exceeds the invalidation threshold (which is negative)
    if unrealized_pct <= params.invalidation_pct:
        reason = (
            f"invalidation hit @ {current_price:.4f} "
            f"(P/L: {unrealized_pct:+.2f}%, threshold: {params.invalidation_pct:+.2f}%)"
        )
        return "invalidation", reason

    # 2. Take Profit
    # Check if favorable excursion exceeds the take-profit threshold (which is positive)
    if unrealized_pct >= params.take_profit_pct:
        reason = (
            f"take-profit hit @ {current_price:.4f} "
            f"(P/L: {unrealized_pct:+.2f}%, threshold: {params.take_profit_pct:+.2f}%)"
        )
        return "take_profit", reason

    # 3. Adaptive Timeout
    # Check if elapsed time exceeds the max-hold time derived from MFE flattening
    if elapsed_minutes >= params.adaptive_max_hold_minutes:
        reason = (
            f"adaptive max-hold {params.adaptive_max_hold_minutes:.1f}min exceeded "
            f"({elapsed_minutes:.1f}min held, P/L: {unrealized_pct:+.2f}%)"
        )
        return "adaptive_timeout", reason

    # Hold
    return None, None


def compare_exit_policy_to_timer_baseline(fixture_path: Any, params: DerivedExitParameters) -> Dict[str, Any]:
    """
    Compares the blind 90-minute timer baseline vs MFE/MAE policy on an offline fixture.
    Returns:
        Dict with 'baseline' and 'redesigned' metrics.
    """
    import sys
    from typing import Dict
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[0]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from scripts.coinbase_offline_backtest_report import build_report

    baseline = build_report(
        fixture_path=Path(fixture_path),
        take_profit_pct=3.0,
        stop_loss_pct=1.5,
        max_hold_minutes=90,
    )

    redesigned = build_report(
        fixture_path=Path(fixture_path),
        take_profit_pct=params.take_profit_pct,
        stop_loss_pct=abs(params.invalidation_pct),
        max_hold_minutes=int(params.adaptive_max_hold_minutes),
    )

    def _parse(res: Dict[str, Any]) -> Dict[str, Any]:
        trades = res.get("total_trades", 0)
        reasons = res.get("exit_reason_breakdown", {})
        gross = float(res.get("gross_pnl_sum", 0))
        fees = float(res.get("fees_sum", 0))
        avg_hold = sum(t.get("hold_minutes", 0) for t in res.get("closed_trades", [])) / max(1, trades)

        return {
            "net_after_fees": res.get("net_pnl_sum"),
            "win_rate": res.get("win_rate"),
            "profit_factor": 0.0, # Not easily computable from aggregate sums
            "timeout_rate": reasons.get("max_hold_time_exceeded", 0) / max(1, trades),
            "take_profit_rate": reasons.get("take_profit", 0) / max(1, trades),
            "invalidation_rate": reasons.get("stop_loss", 0) / max(1, trades),
            "fee_drag_share": fees / gross if gross > 0 else 0.0,
            "average_hold_minutes": avg_hold,
        }

    return {
        "baseline": _parse(baseline),
        "redesigned": _parse(redesigned),
    }
