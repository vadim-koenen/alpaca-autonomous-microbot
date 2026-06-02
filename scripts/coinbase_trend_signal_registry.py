#!/usr/bin/env python3
"""
Read-only Coinbase trend advisory signal registry.

This module normalizes fixture/local context into advisory-only signals. It does
not import broker clients, read .env, place orders, change sizing, or override
risk gates.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


SCHEMA_VERSION = "p2-024a.trend_advisory.v1"
MODE = "read_only_advisory"
TRADE_PERMISSION = "none"
ELIGIBLE_SYMBOLS = ("BTC/USD", "ETH/USD")
EXCLUDED_SYMBOLS = ("SOL/USD",)


SOURCE_REGISTRY: Dict[str, Dict[str, Any]] = {
    "coinbase_local_market_context": {
        "display_name": "Coinbase local market context",
        "enabled_by_default": True,
        "default_mode": "fixture_or_local_read_only",
        "requires_api_key": False,
        "network_default": False,
        "description": "Local regime, allowed strategies, candle/WebSocket-derived context.",
    },
    "coingecko_trending": {
        "display_name": "CoinGecko trending coins/categories",
        "enabled_by_default": False,
        "default_mode": "fixture_only",
        "requires_api_key": False,
        "network_default": False,
        "description": "Optional external trend context; confirm-only and never a trade trigger.",
    },
    "coindesk_rss_news": {
        "display_name": "CoinDesk RSS/news headlines",
        "enabled_by_default": False,
        "default_mode": "fixture_only",
        "requires_api_key": False,
        "network_default": False,
        "description": "Optional headline/narrative context; confirm-only and never a trade trigger.",
    },
    "future_sources": {
        "display_name": "Future trend/advisory sources",
        "enabled_by_default": False,
        "default_mode": "disabled",
        "requires_api_key": False,
        "network_default": False,
        "description": "Reserved for later human-approved offline adapters.",
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_symbol(symbol: Any) -> str:
    text = str(symbol or "").strip().upper().replace("-", "/")
    aliases = {
        "BTC": "BTC/USD",
        "BITCOIN": "BTC/USD",
        "ETH": "ETH/USD",
        "ETHEREUM": "ETH/USD",
        "SOL": "SOL/USD",
        "SOLANA": "SOL/USD",
    }
    return aliases.get(text, text)


def source_definitions() -> List[Dict[str, Any]]:
    return [
        {"source_id": source_id, **definition}
        for source_id, definition in SOURCE_REGISTRY.items()
    ]


def _load_json(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_load_error": str(exc)}
    return data if isinstance(data, dict) else {"payload": data}


def _source(payload: Dict[str, Any], source_id: str) -> Dict[str, Any]:
    sources = payload.get("sources")
    if isinstance(sources, dict) and isinstance(sources.get(source_id), dict):
        return sources[source_id]
    if isinstance(sources, dict):
        return {}
    if isinstance(payload.get(source_id), dict):
        return payload[source_id]
    if source_id == "coinbase_local_market_context" and any(
        key in payload for key in ("symbols", "symbol", "regime", "allowed_strategies")
    ):
        return payload
    return {}


def _source_status(payload: Dict[str, Any], source_id: str) -> str:
    src = _source(payload, source_id)
    if src.get("_load_error"):
        return "unavailable"
    return str(src.get("source_status") or ("available" if src else "unavailable"))


def _local_symbol_context(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    src = _source(payload, "coinbase_local_market_context")
    records = src.get("symbols")
    if records is None and any(key in src for key in ("symbol", "regime", "allowed_strategies")):
        records = [src]
    result: Dict[str, Dict[str, Any]] = {}
    if isinstance(records, list):
        for row in records:
            if not isinstance(row, dict):
                continue
            symbol = normalize_symbol(row.get("symbol"))
            if symbol:
                result[symbol] = row
    return result


def _external_mentions(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    mentions: Dict[str, Dict[str, Any]] = {}

    cg = _source(payload, "coingecko_trending")
    coins = cg.get("coins") or cg.get("trending") or []
    if isinstance(coins, list):
        for item in coins:
            if not isinstance(item, dict):
                continue
            symbol = normalize_symbol(item.get("symbol") or item.get("name") or item.get("coin_id"))
            if symbol:
                mentions.setdefault(symbol, {"positive": 0, "negative": 0, "sources": []})
                mentions[symbol]["positive"] += 1
                mentions[symbol]["sources"].append("coingecko_trending")

    cd = _source(payload, "coindesk_rss_news")
    headlines = cd.get("headlines") or cd.get("items") or []
    if isinstance(headlines, list):
        for item in headlines:
            if isinstance(item, dict):
                title = str(item.get("title") or item.get("headline") or "")
                sentiment = str(item.get("sentiment") or item.get("bias") or "neutral").lower()
                symbols = item.get("symbols") or []
            else:
                title = str(item)
                sentiment = "neutral"
                symbols = []
            haystack = " ".join([title, " ".join(str(s) for s in symbols)]).upper()
            found = [sym for sym in ("BTC/USD", "ETH/USD", "SOL/USD") if sym.split("/")[0] in haystack]
            for symbol in found:
                mentions.setdefault(symbol, {"positive": 0, "negative": 0, "sources": []})
                if sentiment in {"positive", "bullish"}:
                    mentions[symbol]["positive"] += 1
                elif sentiment in {"negative", "bearish"}:
                    mentions[symbol]["negative"] += 1
                mentions[symbol]["sources"].append("coindesk_rss_news")

    return mentions


def _local_signal(symbol: str, local: Dict[str, Any]) -> Dict[str, Any]:
    regime = str(local.get("regime") or "unknown").lower()
    allowed = local.get("allowed_strategies")
    allowed_count = len(allowed) if isinstance(allowed, list) else 0
    reasons: List[str] = []
    if regime:
        reasons.append(f"local_regime={regime}")
    if allowed_count == 0:
        reasons.append("allowed_strategies_empty")

    if regime == "downtrend" and allowed_count == 0:
        return {
            "trend_bias": "bearish",
            "trend_confidence": 0.78,
            "advisory_action": "avoid",
            "reasons": reasons,
            "sources_used": ["coinbase_local_market_context"],
        }
    if regime == "downtrend":
        return {
            "trend_bias": "bearish",
            "trend_confidence": 0.68,
            "advisory_action": "watch",
            "reasons": reasons,
            "sources_used": ["coinbase_local_market_context"],
        }
    if regime == "uptrend" and allowed_count > 0:
        return {
            "trend_bias": "bullish",
            "trend_confidence": 0.66,
            "advisory_action": "confirm_only",
            "reasons": reasons,
            "sources_used": ["coinbase_local_market_context"],
        }
    return {
        "trend_bias": "neutral" if regime != "unknown" else "unknown",
        "trend_confidence": 0.35,
        "advisory_action": "watch" if regime != "unknown" else "unknown",
        "reasons": reasons,
        "sources_used": ["coinbase_local_market_context"] if local else [],
    }


def _apply_external_context(signal: Dict[str, Any], mention: Dict[str, Any]) -> Dict[str, Any]:
    if not mention:
        return signal
    positive = int(mention.get("positive") or 0)
    negative = int(mention.get("negative") or 0)
    sources = sorted(set(signal.get("sources_used", []) + list(mention.get("sources") or [])))
    signal["sources_used"] = sources
    if positive:
        signal["reasons"].append(f"external_positive_mentions={positive}")
    if negative:
        signal["reasons"].append(f"external_negative_mentions={negative}")

    if signal["advisory_action"] == "avoid":
        signal["reasons"].append("external_positive_does_not_override_local_downtrend")
        return signal
    if positive > negative and signal["trend_bias"] in {"neutral", "unknown"}:
        signal["trend_bias"] = "bullish"
        signal["trend_confidence"] = max(float(signal["trend_confidence"]), 0.50)
        signal["advisory_action"] = "confirm_only"
    return signal


def build_advisory_snapshot(
    *,
    symbols: Iterable[str],
    source_json: Optional[Path] = None,
    allow_network: bool = False,
) -> Dict[str, Any]:
    payload = _load_json(source_json)
    requested = [normalize_symbol(symbol) for symbol in symbols]
    local_by_symbol = _local_symbol_context(payload)
    mentions = _external_mentions(payload)
    source_status = {
        source_id: _source_status(payload, source_id)
        for source_id in SOURCE_REGISTRY
    }

    rows: List[Dict[str, Any]] = []
    excluded_requested = sorted({symbol for symbol in requested if symbol in EXCLUDED_SYMBOLS})
    for symbol in requested:
        if symbol not in ELIGIBLE_SYMBOLS:
            continue
        signal = _local_signal(symbol, local_by_symbol.get(symbol, {}))
        signal = _apply_external_context(signal, mentions.get(symbol, {}))
        rows.append({
            "symbol": symbol,
            "trend_bias": signal["trend_bias"],
            "trend_confidence": f"{float(signal['trend_confidence']):.2f}",
            "advisory_action": signal["advisory_action"],
            "reasons": signal["reasons"],
            "sources_used": sorted(set(signal.get("sources_used", []))),
            "eligible_for_live_trade_trigger": False,
        })

    global_narratives = []
    if excluded_requested or any(symbol in mentions for symbol in EXCLUDED_SYMBOLS):
        global_narratives.append({
            "topic": "excluded_symbols",
            "message": "SOL/USD context ignored for live advisory symbols; SOL remains excluded.",
            "symbols": sorted(set(excluded_requested + list(EXCLUDED_SYMBOLS))),
        })
    if not allow_network:
        global_narratives.append({
            "topic": "network",
            "message": "Network fetching disabled; fixture/local sources only.",
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "mode": MODE,
        "trade_permission": TRADE_PERMISSION,
        "risk_increase": "not_approved",
        "symbols": rows,
        "global_narratives": global_narratives,
        "source_registry": source_definitions(),
        "source_status": source_status,
        "safety": {
            "advisory_only": True,
            "order_actions_allowed": False,
            "sizing_changes_allowed": False,
            "risk_override_allowed": False,
            "broker_calls_made": False,
            "live_read_only_used": False,
            "secrets_or_env_read": False,
            "network_used": bool(allow_network and False),
        },
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build read-only Coinbase trend advisory snapshot")
    parser.add_argument("--symbol", action="append", default=[], help="Symbol to include, repeatable")
    parser.add_argument("--source-json", type=Path, default=None, help="Fixture/local source JSON")
    parser.add_argument("--allow-network", action="store_true", help="Reserved; no network adapters are active in P2-024A")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args(argv)

    symbols = args.symbol or list(ELIGIBLE_SYMBOLS)
    snapshot = build_advisory_snapshot(
        symbols=symbols,
        source_json=args.source_json,
        allow_network=args.allow_network,
    )
    if args.json:
        print(json.dumps(snapshot, indent=2, sort_keys=True))
    else:
        print("=== Coinbase Trend Advisory Snapshot ===")
        print(f"Mode: {snapshot['mode']}")
        print(f"Trade permission: {snapshot['trade_permission']}")
        for row in snapshot["symbols"]:
            print(
                f"{row['symbol']}: {row['trend_bias']} "
                f"confidence={row['trend_confidence']} action={row['advisory_action']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
