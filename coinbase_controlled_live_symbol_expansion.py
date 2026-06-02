"""
Pure helpers for P2-024D controlled Coinbase live spot symbol expansion.

The helpers are intentionally offline and side-effect free. They do not import
broker clients, read environment variables, place orders, or mutate state/logs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, Optional


EXPANDED_LIVE_SYMBOLS = (
    "BTC/USD",
    "ETH/USD",
    "ADA/USD",
    "AVAX/USD",
    "DOGE/USD",
    "LINK/USD",
    "LTC/USD",
)
EXCLUDED_SYMBOLS = ("SOL/USD",)
FORBIDDEN_PRODUCT_TOKENS = (
    "PERP",
    "PERPETUAL",
    "FUTURE",
    "FUT",
    "OPTION",
    "PREDICTION",
    "MARKET-CONTRACT",
)


def normalize_symbol(symbol: Any) -> str:
    text = str(symbol or "").strip().upper().replace("-", "/")
    aliases = {
        "BTC": "BTC/USD",
        "ETH": "ETH/USD",
        "ADA": "ADA/USD",
        "AVAX": "AVAX/USD",
        "DOGE": "DOGE/USD",
        "LINK": "LINK/USD",
        "LTC": "LTC/USD",
        "SOL": "SOL/USD",
    }
    return aliases.get(text, text)


def _decimal_or_none(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def _list_symbols(values: Any, default: Iterable[str]) -> list[str]:
    if not isinstance(values, list) or not values:
        return [normalize_symbol(item) for item in default]
    result = []
    for item in values:
        symbol = normalize_symbol(item)
        if symbol and symbol not in result:
            result.append(symbol)
    return result


def policy_from_crypto_config(crypto: Dict[str, Any]) -> Dict[str, Any]:
    section = crypto.get("controlled_live_symbol_expansion")
    section = section if isinstance(section, dict) else {}
    enabled = bool(section.get("enabled", False))
    live_symbols = _list_symbols(
        section.get("live_symbols") if enabled else crypto.get("fee_aware_pilot_symbols"),
        EXPANDED_LIVE_SYMBOLS if enabled else ("BTC/USD", "ETH/USD"),
    )
    excluded_symbols = _list_symbols(
        section.get("excluded_symbols") if enabled else crypto.get("fee_aware_pilot_excluded_symbols"),
        EXCLUDED_SYMBOLS,
    )
    return {
        "enabled": enabled,
        "live_symbols": live_symbols,
        "expanded_live_symbols": live_symbols,
        "excluded_symbols": excluded_symbols,
        "shared_caps": bool(section.get("shared_caps", True)),
        "require_quote_health": bool(section.get("require_quote_health", True)),
        "require_fee_drag_clearance": bool(section.get("require_fee_drag_clearance", True)),
        "no_derivatives": bool(section.get("no_derivatives", True)),
        "block_prediction_products": bool(section.get("block_prediction_products", True)),
        "max_trade_notional_usd": crypto.get("max_trade_notional_usd", 10.00),
        "absolute_hard_trade_cap_usd": crypto.get("absolute_hard_trade_cap_usd", 10.00),
        "max_total_crypto_exposure_usd": crypto.get("max_total_crypto_exposure_usd", 10.00),
        "max_spread_pct": crypto.get("max_spread_pct", 0.20),
        "max_spread_pct_per_symbol": crypto.get("max_spread_pct_per_symbol") or {},
    }


def resolve_live_symbols_from_crypto_config(crypto: Dict[str, Any]) -> list[str]:
    policy = policy_from_crypto_config(crypto)
    if policy["enabled"]:
        return [
            symbol for symbol in policy["live_symbols"]
            if symbol not in set(policy["excluded_symbols"])
            and not product_is_forbidden(symbol, policy)
        ]
    return _list_symbols(crypto.get("live_symbols") or crypto.get("symbols"), ("BTC/USD", "ETH/USD"))


def product_is_forbidden(symbol: str, policy: Dict[str, Any]) -> bool:
    text = str(symbol or "").upper().replace("/", "-")
    if policy.get("no_derivatives", True) or policy.get("block_prediction_products", True):
        return any(token in text for token in FORBIDDEN_PRODUCT_TOKENS)
    return False


def _quote_from_payload(symbol: str, quote_payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(quote_payload, dict):
        return {}
    quotes = quote_payload.get("quotes")
    if isinstance(quotes, dict):
        return quotes.get(symbol) or quotes.get(symbol.replace("/", "-")) or {}
    return quote_payload.get(symbol) if isinstance(quote_payload.get(symbol), dict) else {}


def quote_for_symbol(symbol: str, quote_payload: Dict[str, Any]) -> Dict[str, Any]:
    return _quote_from_payload(normalize_symbol(symbol), quote_payload)


def _timestamp_is_fresh(value: Any, max_age_seconds: Any, now: Optional[datetime]) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.lower() in {"fresh", "current"}:
        return True
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        now_dt = now or datetime.now(timezone.utc)
        max_age = float(max_age_seconds or 90)
        return (now_dt - parsed).total_seconds() <= max_age
    except Exception:
        return False


def evaluate_symbol_eligibility(
    *,
    symbol: str,
    policy: Dict[str, Any],
    quote: Optional[Dict[str, Any]] = None,
    regime: str = "unknown",
    allowed_strategies: Optional[list[str]] = None,
    expected_gross_move_rate: Any = None,
    required_gross_move_rate: Any = None,
    open_positions: int = 0,
    max_open_positions: int = 1,
    daily_trade_count: int = 0,
    max_trades_per_day: int = 3,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    symbol_norm = normalize_symbol(symbol)
    reasons: list[str] = []
    live_set = set(policy.get("live_symbols") or EXPANDED_LIVE_SYMBOLS)
    excluded_set = set(policy.get("excluded_symbols") or EXCLUDED_SYMBOLS)

    if product_is_forbidden(symbol_norm, policy):
        reasons.append("symbol_not_in_live_basket")
    if symbol_norm not in live_set:
        reasons.append("symbol_not_in_live_basket")
    if symbol_norm in excluded_set:
        reasons.append("symbol_excluded_external_inventory")

    quote = quote if isinstance(quote, dict) else {}
    bid = _decimal_or_none(quote.get("bid"))
    ask = _decimal_or_none(quote.get("ask"))
    fresh_flag = quote.get("fresh")
    stale_flag = quote.get("stale")
    if policy.get("require_quote_health", True):
        timestamp_ok = _timestamp_is_fresh(
            quote.get("timestamp") or quote.get("timestamp_utc"),
            quote.get("max_age_seconds") or quote.get("stale_data_seconds") or 90,
            now,
        )
        if (
            not quote
            or bid is None
            or ask is None
            or bid <= 0
            or ask <= 0
            or ask <= bid
            or fresh_flag is False
            or stale_flag is True
            or not timestamp_ok
        ):
            reasons.append("invalid_or_stale_quote")

    spread_pct = None
    threshold_raw = None
    if bid is not None and ask is not None and bid > 0 and ask > bid:
        mid = (bid + ask) / Decimal("2")
        spread_pct = ((ask - bid) / mid) * Decimal("100")
        per_symbol = policy.get("max_spread_pct_per_symbol") or {}
        threshold_raw = quote.get("max_spread_pct") or per_symbol.get(symbol_norm) or policy.get("max_spread_pct", 0.20)
        threshold = _decimal_or_none(threshold_raw)
        if threshold is not None and spread_pct > threshold:
            reasons.append("spread_too_wide")

    strategies = allowed_strategies if isinstance(allowed_strategies, list) else []
    if not strategies:
        reasons.append("regime_disallows_strategy")

    if policy.get("require_fee_drag_clearance", True):
        expected = _decimal_or_none(expected_gross_move_rate)
        required = _decimal_or_none(required_gross_move_rate)
        if expected is None or required is None or expected <= required:
            reasons.append("fee_drag_expected_edge_too_small")

    if int(open_positions or 0) >= int(max_open_positions or 1):
        reasons.append("max_open_positions_reached")
    if int(daily_trade_count or 0) >= int(max_trades_per_day or 3):
        reasons.append("max_trades_per_day_reached")

    deduped_reasons = []
    for reason in reasons:
        if reason not in deduped_reasons:
            deduped_reasons.append(reason)

    allowed = not deduped_reasons
    if allowed:
        verdict = "candidate"
    elif deduped_reasons == ["regime_disallows_strategy"]:
        verdict = "sit_out"
    elif "regime_disallows_strategy" in deduped_reasons and not any(
        reason for reason in deduped_reasons
        if reason not in {"regime_disallows_strategy", "fee_drag_expected_edge_too_small"}
    ):
        verdict = "sit_out"
    else:
        verdict = "blocked"

    return {
        "symbol": symbol_norm,
        "allowed": allowed,
        "opportunity_verdict": verdict,
        "skip_reasons": deduped_reasons,
        "local_regime": str(regime or "unknown").lower(),
        "allowed_strategies": strategies,
        "quote_health": {
            "bid": str(bid) if bid is not None else None,
            "ask": str(ask) if ask is not None else None,
            "spread_pct": str(spread_pct.quantize(Decimal("0.0001"))) if spread_pct is not None else None,
            "max_spread_pct": str(threshold_raw) if threshold_raw is not None else None,
            "fresh": "invalid_or_stale_quote" not in deduped_reasons,
        },
        "fee_drag": {
            "expected_gross_move_rate": str(expected_gross_move_rate) if expected_gross_move_rate is not None else None,
            "required_gross_move_rate": str(required_gross_move_rate) if required_gross_move_rate is not None else None,
            "cleared": "fee_drag_expected_edge_too_small" not in deduped_reasons,
        },
        "shared_caps": bool(policy.get("shared_caps", True)),
    }
