"""Pure P2-042A policy helpers for bounded live research.

This module is intentionally disconnected from runtime execution. It does not
read environment variables, load credentials, call brokers, place orders, or
mutate strategy, risk, sizing, capital, journal, or runtime state.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional


LIVE_RESEARCH_APPROVAL_PHRASE_PATTERN = (
    r"^LIVE_RESEARCH_APPROVED for Coinbase high-volatility evidence collection "
    r"with max loss budget \$(?P<amount>\d+(?:\.\d{1,2})?)$"
)
_APPROVAL_RE = re.compile(LIVE_RESEARCH_APPROVAL_PHRASE_PATTERN)

DEFAULT_LIVE_RESEARCH_POLICY = {
    "LIVE_RESEARCH_FOR_DATA": False,
    "LIVE_TRADING_FOR_PROFIT": False,
    "LIVE_RESEARCH_APPROVAL_REQUIRED": True,
    "LIVE_RESEARCH_APPROVAL_TEXT": "",
    "LIVE_RESEARCH_BUDGET_USD": None,
    "MAX_DAILY_RESEARCH_LOSS_USD": None,
    "MAX_WEEKLY_RESEARCH_LOSS_USD": None,
    "MAX_SINGLE_TRADE_NOTIONAL_USD": None,
    "MAX_RESEARCH_TRADES_PER_DAY": None,
    "ALLOWED_RESEARCH_SYMBOLS": [],
    "RESEARCH_MODE_EXPIRES_AT": "",
    "RESEARCH_KILL_SWITCH_ON_BUDGET_BREACH": True,
    "RESEARCH_KILL_SWITCH_ON_BROKER_ERROR": True,
    "RESEARCH_KILL_SWITCH_ON_MISSING_JOURNAL": True,
    "RESEARCH_KILL_SWITCH_ON_MISSING_FEE_CAPTURE": True,
    "RESEARCH_KILL_SWITCH_ON_MISSING_FILL_CAPTURE": True,
    "RESEARCH_KILL_SWITCH_ON_MISSING_MFE_MAE_CAPTURE": True,
    "ML_LIVE_INFLUENCE_ENABLED": False,
    "ONLINE_LEARNING_ENABLED": False,
}

_POSITIVE_MONEY_FIELDS = (
    "LIVE_RESEARCH_BUDGET_USD",
    "MAX_DAILY_RESEARCH_LOSS_USD",
    "MAX_WEEKLY_RESEARCH_LOSS_USD",
    "MAX_SINGLE_TRADE_NOTIONAL_USD",
)
_REQUIRED_KILL_SWITCHES = (
    "RESEARCH_KILL_SWITCH_ON_BUDGET_BREACH",
    "RESEARCH_KILL_SWITCH_ON_BROKER_ERROR",
    "RESEARCH_KILL_SWITCH_ON_MISSING_JOURNAL",
    "RESEARCH_KILL_SWITCH_ON_MISSING_FEE_CAPTURE",
    "RESEARCH_KILL_SWITCH_ON_MISSING_FILL_CAPTURE",
    "RESEARCH_KILL_SWITCH_ON_MISSING_MFE_MAE_CAPTURE",
)


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    return default


def _decimal_or_none(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _positive_decimal(value: Any) -> Optional[Decimal]:
    parsed = _decimal_or_none(value)
    return parsed if parsed is not None and parsed > 0 else None


def _positive_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite() or parsed <= 0 or parsed != parsed.to_integral_value():
        return None
    return int(parsed)


def _normalize_symbols(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for item in value:
        symbol = str(item or "").strip().upper().replace("-", "/")
        if symbol and symbol not in result:
            result.append(symbol)
    return result


def _parse_expiry(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def resolve_live_research_policy(config: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Return a normalized, fail-safe policy mapping without side effects."""
    source = config if isinstance(config, Mapping) else {}
    policy = dict(DEFAULT_LIVE_RESEARCH_POLICY)
    policy.update({key: source[key] for key in policy if key in source})

    for field in (
        "LIVE_RESEARCH_FOR_DATA",
        "LIVE_TRADING_FOR_PROFIT",
        "LIVE_RESEARCH_APPROVAL_REQUIRED",
        *_REQUIRED_KILL_SWITCHES,
        "ML_LIVE_INFLUENCE_ENABLED",
        "ONLINE_LEARNING_ENABLED",
    ):
        policy[field] = _as_bool(policy.get(field), DEFAULT_LIVE_RESEARCH_POLICY[field])

    policy["LIVE_RESEARCH_APPROVAL_TEXT"] = str(
        policy.get("LIVE_RESEARCH_APPROVAL_TEXT") or ""
    ).strip()
    policy["ALLOWED_RESEARCH_SYMBOLS"] = _normalize_symbols(
        policy.get("ALLOWED_RESEARCH_SYMBOLS")
    )
    policy["RESEARCH_MODE_EXPIRES_AT"] = str(
        policy.get("RESEARCH_MODE_EXPIRES_AT") or ""
    ).strip()
    return policy


def validate_live_research_approval(approval_text: Any, budget_usd: Any) -> bool:
    """Require the exact approval phrase and a budget amount that matches it."""
    match = _APPROVAL_RE.fullmatch(str(approval_text or "").strip())
    budget = _positive_decimal(budget_usd)
    if match is None or budget is None:
        return False
    phrase_budget = _positive_decimal(match.group("amount"))
    return phrase_budget is not None and phrase_budget == budget


def live_research_fail_closed_reasons(
    config: Optional[Mapping[str, Any]] = None,
    *,
    now: Optional[datetime] = None,
    research_budget_loss_usd: Any = 0,
    daily_research_loss_usd: Any = 0,
    weekly_research_loss_usd: Any = 0,
    broker_error: bool = False,
    journal_capture_available: bool = False,
    fee_capture_available: bool = False,
    fill_capture_available: bool = False,
    mfe_mae_capture_available: bool = False,
) -> list[str]:
    """Return every reason the live-research policy gate must remain closed."""
    policy = resolve_live_research_policy(config)
    reasons: list[str] = []

    if not policy["LIVE_RESEARCH_FOR_DATA"]:
        reasons.append("live_research_for_data_disabled")

    if policy["LIVE_TRADING_FOR_PROFIT"]:
        reasons.append("live_trading_for_profit_must_remain_disabled")
    if policy["ML_LIVE_INFLUENCE_ENABLED"]:
        reasons.append("ml_live_influence_must_remain_disabled")
    if policy["ONLINE_LEARNING_ENABLED"]:
        reasons.append("online_learning_must_remain_disabled")

    if not policy["LIVE_RESEARCH_FOR_DATA"]:
        return reasons

    if not policy["LIVE_RESEARCH_APPROVAL_REQUIRED"]:
        reasons.append("live_research_approval_required_must_be_true")
    if not validate_live_research_approval(
        policy["LIVE_RESEARCH_APPROVAL_TEXT"],
        policy["LIVE_RESEARCH_BUDGET_USD"],
    ):
        reasons.append("live_research_approval_missing_or_invalid")

    for field in _POSITIVE_MONEY_FIELDS:
        if _positive_decimal(policy.get(field)) is None:
            reasons.append(f"{field.lower()}_required")

    max_trades = _positive_int(policy.get("MAX_RESEARCH_TRADES_PER_DAY"))
    if max_trades is None:
        reasons.append("max_research_trades_per_day_required")

    if not policy["ALLOWED_RESEARCH_SYMBOLS"]:
        reasons.append("allowed_research_symbols_required")

    expiry = _parse_expiry(policy["RESEARCH_MODE_EXPIRES_AT"])
    if not policy["RESEARCH_MODE_EXPIRES_AT"]:
        reasons.append("research_mode_expiry_required")
    elif expiry is None:
        reasons.append("research_mode_expiry_invalid_or_timezone_missing")
    else:
        now_utc = now or datetime.now(timezone.utc)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
        if expiry <= now_utc.astimezone(timezone.utc):
            reasons.append("research_mode_expired")

    for field in _REQUIRED_KILL_SWITCHES:
        if not policy[field]:
            reasons.append(f"{field.lower()}_must_be_true")

    budget = _positive_decimal(policy.get("LIVE_RESEARCH_BUDGET_USD"))
    daily_cap = _positive_decimal(policy.get("MAX_DAILY_RESEARCH_LOSS_USD"))
    weekly_cap = _positive_decimal(policy.get("MAX_WEEKLY_RESEARCH_LOSS_USD"))
    budget_loss = _decimal_or_none(research_budget_loss_usd)
    daily_loss = _decimal_or_none(daily_research_loss_usd)
    weekly_loss = _decimal_or_none(weekly_research_loss_usd)

    if (
        policy["RESEARCH_KILL_SWITCH_ON_BUDGET_BREACH"]
        and budget is not None
        and budget_loss is not None
        and budget_loss >= budget
    ):
        reasons.append("research_budget_breached")
    if (
        policy["RESEARCH_KILL_SWITCH_ON_BUDGET_BREACH"]
        and daily_cap is not None
        and daily_loss is not None
        and daily_loss >= daily_cap
    ):
        reasons.append("daily_research_loss_cap_breached")
    if (
        policy["RESEARCH_KILL_SWITCH_ON_BUDGET_BREACH"]
        and weekly_cap is not None
        and weekly_loss is not None
        and weekly_loss >= weekly_cap
    ):
        reasons.append("weekly_research_loss_cap_breached")

    if policy["RESEARCH_KILL_SWITCH_ON_BROKER_ERROR"] and broker_error:
        reasons.append("broker_error_kill_switch")
    if policy["RESEARCH_KILL_SWITCH_ON_MISSING_JOURNAL"] and not journal_capture_available:
        reasons.append("missing_journal_capture")
    if policy["RESEARCH_KILL_SWITCH_ON_MISSING_FEE_CAPTURE"] and not fee_capture_available:
        reasons.append("missing_fee_capture")
    if policy["RESEARCH_KILL_SWITCH_ON_MISSING_FILL_CAPTURE"] and not fill_capture_available:
        reasons.append("missing_fill_capture")
    if (
        policy["RESEARCH_KILL_SWITCH_ON_MISSING_MFE_MAE_CAPTURE"]
        and not mfe_mae_capture_available
    ):
        reasons.append("missing_mfe_mae_capture")

    return list(dict.fromkeys(reasons))


def live_research_mode_allowed(
    config: Optional[Mapping[str, Any]] = None,
    **state: Any,
) -> bool:
    """Return policy eligibility only; this does not authorize order placement."""
    return not live_research_fail_closed_reasons(config, **state)


def evaluate_live_research_policy(
    config: Optional[Mapping[str, Any]] = None,
    **state: Any,
) -> dict[str, Any]:
    """Return an auditable policy report with execution kept explicitly off."""
    policy = resolve_live_research_policy(config)
    reasons = live_research_fail_closed_reasons(policy, **state)
    return {
        "live_research_policy_allowed": not reasons,
        "fail_closed_reasons": reasons,
        "policy": policy,
        "mode_separation": {
            "live_research_for_data": policy["LIVE_RESEARCH_FOR_DATA"],
            "live_trading_for_profit": False,
            "research_does_not_prove_profitability": True,
        },
        "execution": {
            "actual_order_placement_integrated": False,
            "actual_order_placement_enabled": False,
            "authenticated_broker_api_used": False,
            "broker_order_mutation": False,
        },
        "learning": {
            "ml_live_influence_enabled": False,
            "online_learning_started": False,
        },
        "change_authority": {
            "strategy_changes_approved": False,
            "risk_cap_changes_approved": False,
            "sizing_changes_approved": False,
            "capital_or_notional_increase_approved": False,
        },
    }
