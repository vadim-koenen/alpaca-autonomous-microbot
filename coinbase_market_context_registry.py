"""
Offline Coinbase market/trend context registry.

This registry is advisory/read-only by design. It prepares local source and
symbol context for later operator review without giving market, news, trend, or
sentiment data any trading authority.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from coinbase_controlled_live_symbol_expansion import (
    EXCLUDED_SYMBOLS,
    EXPANDED_LIVE_SYMBOLS,
    normalize_symbol,
)


SCHEMA_VERSION = "p2-025b.coinbase_market_context_registry.v1"
MODE = "offline_fixture_backed_read_only_market_context"
TRADE_PERMISSION = "none"
TRADING_AUTHORITY = "none"
ALLOWED_ADVISORY_LABELS = {
    "confirm_only",
    "watch",
    "avoid",
    "trend_attention",
    "insufficient_data",
}
FORBIDDEN_EXTERNAL_OUTPUTS = (
    "buy",
    "sell",
    "trade",
    "order",
    "size_increase",
    "risk_override",
    "strategy_override",
    "execution_override",
)
OUT_OF_SCOPE_MARKETS = (
    "perps",
    "derivatives",
    "prediction_markets",
    "stocks",
    "etfs",
    "margin",
    "leverage",
    "options",
)


SOURCE_DEFINITIONS: tuple[Dict[str, Any], ...] = (
    {
        "source_name": "coinbase_market_data",
        "category": "execution_venue",
        "default_status": "fixture_available",
        "requires_network": False,
        "requires_auth": False,
        "allowed_use": "execution_quality_input",
        "freshness": "fixture_snapshot",
        "symbols_covered": list(EXPANDED_LIVE_SYMBOLS),
        "mapping_notes": "Coinbase spot ticker/candle/book snapshots normalize product_id to SYMBOL/USD.",
    },
    {
        "source_name": "coinbase_product_metadata",
        "category": "execution_venue",
        "default_status": "fixture_available",
        "requires_network": False,
        "requires_auth": False,
        "allowed_use": "execution_quality_input",
        "freshness": "fixture_snapshot",
        "symbols_covered": list(EXPANDED_LIVE_SYMBOLS),
        "mapping_notes": "Spot-only product constraints; derivatives and non-spot products are out of scope.",
    },
    {
        "source_name": "coinbase_level2_order_book_future",
        "category": "future",
        "default_status": "future",
        "requires_network": True,
        "requires_auth": False,
        "allowed_use": "future_research",
        "freshness": "future_websocket_snapshot",
        "symbols_covered": list(EXPANDED_LIVE_SYMBOLS),
        "mapping_notes": "Future offline simulator should model level2 depth before any live WebSocket use.",
    },
    {
        "source_name": "coinbase_order_preview_future",
        "category": "future",
        "default_status": "disabled",
        "requires_network": True,
        "requires_auth": True,
        "allowed_use": "future_research",
        "freshness": "disabled_until_human_approved_adapter",
        "symbols_covered": list(EXPANDED_LIVE_SYMBOLS),
        "mapping_notes": "Preview PNL is advisory only and cannot prove final profitability because fees/slippage need separate modeling.",
    },
    {
        "source_name": "coingecko_trending",
        "category": "trend_context",
        "default_status": "fixture_available",
        "requires_network": False,
        "requires_auth": False,
        "allowed_use": "advisory_only",
        "freshness": "fixture_snapshot",
        "symbols_covered": list(EXPANDED_LIVE_SYMBOLS),
        "mapping_notes": "External trend context can confirm attention only; it never triggers trades.",
    },
    {
        "source_name": "coingecko_markets",
        "category": "market_context",
        "default_status": "fixture_available",
        "requires_network": False,
        "requires_auth": False,
        "allowed_use": "advisory_only",
        "freshness": "fixture_snapshot",
        "symbols_covered": list(EXPANDED_LIVE_SYMBOLS),
        "mapping_notes": "External market context is advisory and cannot override execution-quality gates.",
    },
    {
        "source_name": "crypto_news_sentiment_future",
        "category": "news_sentiment",
        "default_status": "future",
        "requires_network": True,
        "requires_auth": False,
        "allowed_use": "future_research",
        "freshness": "future_fixture_or_feed",
        "symbols_covered": list(EXPANDED_LIVE_SYMBOLS),
        "mapping_notes": "News/sentiment is advisory only and cannot trigger or size trades.",
    },
    {
        "source_name": "all_asset_opportunity_registry_future",
        "category": "future",
        "default_status": "future",
        "requires_network": False,
        "requires_auth": False,
        "allowed_use": "future_research",
        "freshness": "future_design",
        "symbols_covered": list(EXPANDED_LIVE_SYMBOLS),
        "mapping_notes": "Read-only future design; no stocks, ETFs, derivatives, or leverage are enabled.",
    },
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _source_payload(payload: Dict[str, Any], source_name: str) -> Dict[str, Any]:
    sources = _as_dict(payload.get("sources"))
    return _as_dict(sources.get(source_name))


def _symbol_payload(payload: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    contexts = _as_dict(payload.get("symbol_context"))
    return _as_dict(contexts.get(symbol) or contexts.get(symbol.replace("/", "-")))


def _normalize_label(value: Any, *, has_context: bool) -> tuple[str, list[str]]:
    label = str(value or "").strip().lower()
    if not has_context:
        return "insufficient_data", ["source_data_missing"]
    if label in ALLOWED_ADVISORY_LABELS:
        return label, []
    if label:
        return "insufficient_data", [f"forbidden_or_unknown_label_suppressed={label}"]
    return "insufficient_data", ["advisory_label_missing"]


def _source_record(definition: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    source_name = definition["source_name"]
    override = _source_payload(payload, source_name)
    status = str(override.get("status") or definition["default_status"])
    symbols = override.get("symbols_covered")
    if not isinstance(symbols, list):
        symbols = definition["symbols_covered"]

    return {
        "source_name": source_name,
        "category": definition["category"],
        "status": status,
        "requires_network": bool(override.get("requires_network", definition["requires_network"])),
        "requires_auth": bool(override.get("requires_auth", definition["requires_auth"])),
        "trading_authority": TRADING_AUTHORITY,
        "allowed_use": str(override.get("allowed_use") or definition["allowed_use"]),
        "forbidden_use": list(FORBIDDEN_EXTERNAL_OUTPUTS),
        "freshness": str(override.get("freshness") or definition["freshness"]),
        "update_cadence": str(override.get("update_cadence") or "offline_fixture_or_human_refresh"),
        "symbols_covered": [normalize_symbol(symbol) for symbol in symbols],
        "mapping_notes": str(override.get("mapping_notes") or definition["mapping_notes"]),
    }


def _symbol_context(symbol: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    symbol = normalize_symbol(symbol)
    source_context = _symbol_payload(payload, symbol)
    has_context = bool(source_context)
    label, label_reasons = _normalize_label(source_context.get("advisory_label"), has_context=has_context)
    sources = [str(item) for item in _as_list(source_context.get("sources_used")) if str(item).strip()]
    reasons = _dedupe(list(label_reasons) + [str(item) for item in _as_list(source_context.get("reasons"))])

    return {
        "symbol": symbol,
        "status": "available" if has_context else "insufficient_data",
        "advisory_label": label,
        "trading_authority": TRADING_AUTHORITY,
        "trade_permission": TRADE_PERMISSION,
        "can_trigger_trade": False,
        "can_change_sizing": False,
        "can_override_risk": False,
        "can_override_strategy": False,
        "can_override_execution_quality": False,
        "allowed_use": "advisory_only",
        "forbidden_use": list(FORBIDDEN_EXTERNAL_OUTPUTS),
        "sources_used": sources,
        "context_notes": str(source_context.get("context_notes") or "offline fixture context only"),
        "reasons": reasons,
    }


def _excluded_symbol_context(payload: Dict[str, Any]) -> list[Dict[str, Any]]:
    excluded = []
    for symbol in EXCLUDED_SYMBOLS:
        context = _symbol_payload(payload, symbol)
        excluded.append({
            "symbol": symbol,
            "status": str(context.get("status") or "external_staked_position"),
            "external_inventory_classification": str(
                context.get("external_inventory_classification") or "external_staked_position"
            ),
            "bot_inventory": False,
            "tradable_by_bot": False,
            "manual_close_allowed": False,
            "trading_authority": TRADING_AUTHORITY,
            "trade_permission": TRADE_PERMISSION,
            "advisory_label": "avoid",
            "forbidden_use": list(FORBIDDEN_EXTERNAL_OUTPUTS),
        })
    return excluded


def _out_of_scope_markets() -> list[Dict[str, Any]]:
    return [
        {
            "market": market,
            "status": "disabled" if market not in {"derivatives", "perps", "prediction_markets"} else "future_research_only",
            "trading_authority": TRADING_AUTHORITY,
            "allowed_use": "future_research",
            "forbidden_use": list(FORBIDDEN_EXTERNAL_OUTPUTS),
        }
        for market in OUT_OF_SCOPE_MARKETS
    ]


def build_market_context_report(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    live_symbols = payload.get("live_symbols") if isinstance(payload.get("live_symbols"), list) else list(EXPANDED_LIVE_SYMBOLS)
    normalized_symbols = [normalize_symbol(symbol) for symbol in live_symbols]
    source_records = [_source_record(definition, payload) for definition in SOURCE_DEFINITIONS]
    symbol_context = [_symbol_context(symbol, payload) for symbol in normalized_symbols]

    return {
        "schema_version": SCHEMA_VERSION,
        "mode": MODE,
        "generated_at": now_iso(),
        "trade_permission": TRADE_PERMISSION,
        "trading_authority": TRADING_AUTHORITY,
        "live_symbols": normalized_symbols,
        "source_registry": source_records,
        "symbol_context": symbol_context,
        "excluded_symbols": _excluded_symbol_context(payload),
        "out_of_scope_markets": _out_of_scope_markets(),
        "advisory_policy": {
            "allowed_labels": sorted(ALLOWED_ADVISORY_LABELS),
            "trading_authority": TRADING_AUTHORITY,
            "external_context_can_trigger_trades": False,
            "external_context_can_change_sizing": False,
            "external_context_can_override_risk": False,
            "external_context_can_override_strategy": False,
            "external_context_can_override_execution_quality": False,
            "forbidden_outputs": list(FORBIDDEN_EXTERNAL_OUTPUTS),
        },
        "next_integration_step": (
            "Keep standalone until P2-025C/P2-025D can prove product metadata, "
            "preview cost, and maker-first gates remain advisory or explicitly risk-gated."
        ),
        "summary": {
            "source_count": len(source_records),
            "symbol_context_count": len(symbol_context),
            "all_sources_trading_authority_none": all(row["trading_authority"] == TRADING_AUTHORITY for row in source_records),
            "all_symbol_context_trading_authority_none": all(
                row["trading_authority"] == TRADING_AUTHORITY for row in symbol_context
            ),
            "sol_excluded_non_tradable": all(row["tradable_by_bot"] is False for row in _excluded_symbol_context(payload)),
            "trend_news_context_can_trigger_trades": False,
            "profit_readout": "unsafe_to_aggregate",
            "risk_increase": "not_approved",
        },
        "safety": {
            "offline_only": True,
            "broker_calls_made": False,
            "live_read_only_used": False,
            "secrets_or_env_read": False,
            "orders_cancels_closes_modifications": False,
            "state_or_log_mutation": False,
            "runtime_restart_performed": False,
            "runtime_control_touched": False,
            "risk_sizing_symbols_strategy_thresholds_changed": False,
        },
    }
