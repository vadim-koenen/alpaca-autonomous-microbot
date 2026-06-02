"""
Pure helpers for Coinbase controlled fee-aware pilot sizing.

No broker imports, no environment reads, no orders, and no state/log writes.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, Iterable, Optional


MONEY_QUANT = Decimal("0.0001")
RATE_QUANT = Decimal("0.000001")
DEFAULT_PILOT_NOTIONAL_USD = Decimal("5.00")
DEFAULT_ALLOWED_SYMBOLS = ("BTC/USD", "ETH/USD")
DEFAULT_SPREAD_SLIPPAGE_BUFFER_RATE = Decimal("0.0010")


def decimal_or_none(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.startswith("<REDACTED") or text.endswith("_PRESENT>"):
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def fmt_money(value: Decimal) -> str:
    return str(value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP))


def fmt_rate(value: Decimal) -> str:
    return str(value.quantize(RATE_QUANT, rounding=ROUND_HALF_UP))


def _positive_decimal(value: Any, *, default: Decimal) -> Decimal:
    amount = decimal_or_none(value)
    if amount is None or amount <= 0:
        return default
    return amount


def calculate_fee_drag_metrics(
    *,
    entry_value: Any,
    entry_fee: Any,
    exit_value: Any,
    exit_fee: Any,
    spread_slippage_buffer_rate: Any = DEFAULT_SPREAD_SLIPPAGE_BUFFER_RATE,
) -> Dict[str, Any]:
    entry = decimal_or_none(entry_value)
    entry_fee_amount = decimal_or_none(entry_fee)
    exit_ = decimal_or_none(exit_value)
    exit_fee_amount = decimal_or_none(exit_fee)
    buffer_rate = _positive_decimal(
        spread_slippage_buffer_rate,
        default=DEFAULT_SPREAD_SLIPPAGE_BUFFER_RATE,
    )

    missing = []
    if entry is None or entry <= 0:
        missing.append("entry_value")
    if entry_fee_amount is None:
        missing.append("entry_fee")
    if exit_ is None or exit_ <= 0:
        missing.append("exit_value")
    if exit_fee_amount is None:
        missing.append("exit_fee")

    if missing:
        return {
            "verdict": "BLOCKED",
            "blockers": [f"missing_or_non_numeric:{field}" for field in missing],
            "scale_allowed": False,
            "scaling_allowed": False,
            "risk_increase": "not_approved",
        }

    gross = exit_ - entry
    total_fees = entry_fee_amount + exit_fee_amount
    net = gross - total_fees
    entry_fee_rate = entry_fee_amount / entry
    exit_fee_rate = exit_fee_amount / exit_
    observed_round_trip_fee_rate = entry_fee_rate + exit_fee_rate
    gross_pnl_rate = gross / entry
    total_fee_rate = total_fees / entry
    net_pnl_rate = net / entry
    minimum_required_gross_move_rate = observed_round_trip_fee_rate + buffer_rate
    break_even_exit_value = entry + total_fees
    micro_trade_fee_drag_detected = total_fees > gross

    return {
        "verdict": "FEE_DRAG_CONFIRMED" if micro_trade_fee_drag_detected else "OK",
        "entry_value": fmt_money(entry),
        "exit_value": fmt_money(exit_),
        "entry_fee": fmt_money(entry_fee_amount),
        "exit_fee": fmt_money(exit_fee_amount),
        "gross_pnl": fmt_money(gross),
        "total_fees": fmt_money(total_fees),
        "net_pnl": fmt_money(net),
        "observed_entry_fee_rate": fmt_rate(entry_fee_rate),
        "observed_exit_fee_rate": fmt_rate(exit_fee_rate),
        "observed_round_trip_fee_rate": fmt_rate(observed_round_trip_fee_rate),
        "gross_pnl_rate": fmt_rate(gross_pnl_rate),
        "total_fee_rate": fmt_rate(total_fee_rate),
        "fee_rate": fmt_rate(observed_round_trip_fee_rate),
        "net_pnl_rate": fmt_rate(net_pnl_rate),
        "spread_slippage_buffer_rate": fmt_rate(buffer_rate),
        "minimum_required_gross_move_rate": fmt_rate(minimum_required_gross_move_rate),
        "required_break_even_exit_value": fmt_money(break_even_exit_value),
        "break_even_exit_value": fmt_money(break_even_exit_value),
        "micro_trade_fee_drag_detected": micro_trade_fee_drag_detected,
        "scale_allowed": False,
        "scaling_allowed": False,
        "risk_increase": "not_approved",
        "recommendation": (
            "do_not_continue_1usd_micro_trades"
            if micro_trade_fee_drag_detected
            else "continue_measured_fee_aware_pilot_only"
        ),
        "required_action": "do_not_scale; require fee-aware entry threshold",
        "_entry_value_decimal": entry,
        "_exit_value_decimal": exit_,
        "_entry_fee_decimal": entry_fee_amount,
        "_exit_fee_decimal": exit_fee_amount,
        "_minimum_required_gross_move_rate_decimal": minimum_required_gross_move_rate,
    }


def public_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in metrics.items() if not key.startswith("_")}


def evaluate_pilot_candidate(
    *,
    symbol: str,
    expected_gross_move_rate: Any,
    buying_power: Any = None,
    buying_power_buffer: Any = Decimal("0.85"),
    pilot_trade_notional_usd: Any = DEFAULT_PILOT_NOTIONAL_USD,
    max_trade_notional_usd: Any = DEFAULT_PILOT_NOTIONAL_USD,
    min_trade_notional_usd: Any = Decimal("0.50"),
    allowed_symbols: Iterable[str] = DEFAULT_ALLOWED_SYMBOLS,
    enabled: bool = False,
    fee_drag_guard_enabled: bool = True,
    minimum_expected_move_after_fee_buffer: bool = True,
    metrics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    allowed_set = set(allowed_symbols or DEFAULT_ALLOWED_SYMBOLS)
    expected_rate = decimal_or_none(expected_gross_move_rate)
    pilot_notional = _positive_decimal(pilot_trade_notional_usd, default=DEFAULT_PILOT_NOTIONAL_USD)
    max_trade = _positive_decimal(max_trade_notional_usd, default=DEFAULT_PILOT_NOTIONAL_USD)
    min_trade = _positive_decimal(min_trade_notional_usd, default=Decimal("0.50"))
    bp = decimal_or_none(buying_power)
    bp_buffer = _positive_decimal(buying_power_buffer, default=Decimal("0.85"))
    hard_cap = min(pilot_notional, max_trade, DEFAULT_PILOT_NOTIONAL_USD)

    result: Dict[str, Any] = {
        "enabled": bool(enabled),
        "symbol": symbol,
        "allowed_symbols": sorted(allowed_set),
        "pilot_trade_notional_usd": fmt_money(pilot_notional),
        "max_trade_notional_usd": fmt_money(max_trade),
        "hard_cap_notional_usd": fmt_money(hard_cap),
        "notional_usd": fmt_money(hard_cap),
        "scale_allowed": False,
        "scaling_allowed": False,
        "risk_increase": "not_approved",
        "micro_trade_1usd_disabled": True,
    }

    if not enabled:
        result.update({"allowed": False, "reason": "controlled_fee_aware_pilot_disabled"})
        return result
    if symbol == "SOL/USD":
        result.update({"allowed": False, "reason": "sol_external_staked_inventory_excluded"})
        return result
    if symbol not in allowed_set:
        result.update({"allowed": False, "reason": "symbol_not_in_controlled_fee_aware_pilot"})
        return result
    if hard_cap > DEFAULT_PILOT_NOTIONAL_USD:
        result.update({"allowed": False, "reason": "pilot_hard_cap_exceeded"})
        return result
    if hard_cap < min_trade:
        result.update({"allowed": False, "reason": "pilot_notional_below_minimum"})
        return result
    if bp is not None and bp > 0:
        safe_bp = bp * bp_buffer
        result["safe_buying_power_usd"] = fmt_money(safe_bp)
        if safe_bp < hard_cap:
            result.update({"allowed": False, "reason": "safe_buying_power_below_5usd_pilot"})
            return result

    if fee_drag_guard_enabled and minimum_expected_move_after_fee_buffer:
        if not metrics or metrics.get("verdict") == "BLOCKED":
            result.update({"allowed": False, "reason": "fee_drag_metrics_unavailable"})
            return result
        required_rate = metrics.get("_minimum_required_gross_move_rate_decimal")
        if required_rate is None:
            required_rate = decimal_or_none(metrics.get("minimum_required_gross_move_rate"))
        if expected_rate is None or required_rate is None:
            result.update({"allowed": False, "reason": "fee_drag_expected_edge_missing"})
            return result
        result["expected_gross_move_rate"] = fmt_rate(expected_rate)
        result["minimum_required_gross_move_rate"] = fmt_rate(required_rate)
        if expected_rate <= required_rate:
            result.update({"allowed": False, "reason": "fee_drag_expected_edge_too_small"})
            return result

    result.update({"allowed": True, "reason": "ok"})
    return result


def measured_cycle_metrics_from_config(config: Dict[str, Any]) -> Dict[str, Any]:
    observed = config.get("fee_drag_observed_cycle") or {}
    return calculate_fee_drag_metrics(
        entry_value=observed.get("entry_value", "1.0000"),
        entry_fee=observed.get("entry_fee", "0.0060"),
        exit_value=observed.get("exit_value", "1.0025"),
        exit_fee=observed.get("exit_fee", "0.0120"),
        spread_slippage_buffer_rate=config.get(
            "fee_drag_spread_slippage_buffer_rate",
            DEFAULT_SPREAD_SLIPPAGE_BUFFER_RATE,
        ),
    )
