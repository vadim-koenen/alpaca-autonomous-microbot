"""
P2-012B tests for multi-asset spot candidate plumbing and conservative filters.

All tests are pure (no network, no real config mutation, no orders).
"""

import json
import tempfile
from pathlib import Path

import pytest

from coinbase_market_universe import CoinbaseMarketUniverse, PRODUCT_TYPE_SPOT_CRYPTO


def test_configured_symbols_preserved_and_new_assets_not_auto_enabled():
    """Current live symbols stay controlled; newly discovered stay disabled."""
    u = CoinbaseMarketUniverse()
    # Simulate a mixed product list (as if from List Products)
    payload = [
        {"product_id": "BTC-USD", "base_currency": "BTC", "quote_currency": "USD", "product_type": "spot", "status": "online"},
        {"product_id": "ETH-USD", "base_currency": "ETH", "quote_currency": "USD", "product_type": "spot"},
        {"product_id": "SOL-USD", "base_currency": "SOL", "quote_currency": "USD", "product_type": "spot"},
        {"product_id": "DOGE-USD", "base_currency": "DOGE", "quote_currency": "USD", "product_type": "spot"},  # new
        {"product_id": "BTC-PERP", "base_currency": "BTC", "quote_currency": "USD", "contract_type": "perpetual"},
        {"product_id": "GOLD-PERP", "base_currency": "GOLD", "quote_currency": "USD", "contract_type": "perpetual"},
        {"product_id": "XAU-USD", "base_currency": "XAU", "quote_currency": "USD"},
        {"product_id": "DISABLED-USD", "base_currency": "XXX", "quote_currency": "USD", "trading_disabled": True},
    ]
    u.ingest_products(payload)

    report = u.get_spot_crypto_candidates(configured_symbols=["BTC/USD", "ETH/USD", "SOL/USD"])

    # Configured live symbols are recognized
    assert set(report["configured_live_symbols"]) == {"BTC-USD", "ETH-USD", "SOL-USD"}

    # Candidates should include current live + new clean spot (DOGE), but none auto-enabled for live
    cand_pids = {c["product_id"] for c in report["candidates"]}
    assert "BTC-USD" in cand_pids
    assert "DOGE-USD" in cand_pids  # discovered as candidate
    assert "ETH-USD" in cand_pids
    assert "SOL-USD" in cand_pids

    # No new symbol gets allow_live_trading=True
    for c in report["candidates"]:
        if c["product_id"] not in {"BTC-USD", "ETH-USD", "SOL-USD"}:
            assert c["allow_live_trading"] is False
            assert c["is_currently_configured_live"] is False

    # Perps, gold, disabled, leverage are excluded with clear reasons
    excluded_reasons = set(report["excluded_reasons"])
    assert any("derivative" in r or "PERP" in r for r in excluded_reasons)
    assert any("gold" in r.lower() or "silver" in r.lower() or "XAU" in r or "XAG" in r or "commodity" in r.lower() for r in excluded_reasons)
    assert any("disabled" in r for r in excluded_reasons)

    # Current live symbols are never removed or altered
    assert report["candidates_count"] >= 3


def test_perps_futures_gold_silver_leverage_excluded():
    u = CoinbaseMarketUniverse()
    payload = [
        {"product_id": "BTC-USD", "base_currency": "BTC", "quote_currency": "USD", "product_type": "spot"},
        {"product_id": "ETH-PERP", "base_currency": "ETH", "quote_currency": "USD", "contract_type": "perpetual"},
        {"product_id": "SILVER-PERP", "base_currency": "SILVER", "quote_currency": "USD"},
        {"product_id": "LEVERAGED-USD", "base_currency": "FOO", "quote_currency": "USD", "leverage_enabled": True, "max_leverage": 5},
        {"product_id": "FUT-EXPIRING", "base_currency": "BAR", "quote_currency": "USD", "product_type": "future"},
    ]
    u.ingest_products(payload)

    report = u.get_spot_crypto_candidates(configured_symbols=["BTC/USD"])

    cand_pids = {c["product_id"] for c in report["candidates"]}
    assert "BTC-USD" in cand_pids
    assert "ETH-PERP" not in cand_pids
    assert "SILVER-PERP" not in cand_pids
    assert "LEVERAGED-USD" not in cand_pids
    assert "FUT-EXPIRING" not in cand_pids

    reasons = {e["reason"] for e in report["excluded"]}
    assert any("derivative" in r or "PERP" in r for r in reasons)
    assert any("gold" in r.lower() or "silver" in r.lower() or "commodity" in r.lower() for r in reasons)
    assert any("leverage" in r.lower() for r in reasons)


def test_disabled_and_bad_quote_excluded():
    u = CoinbaseMarketUniverse()
    payload = [
        {"product_id": "GOOD-USD", "base_currency": "G", "quote_currency": "USD", "product_type": "spot"},
        {"product_id": "BAD-USDT", "base_currency": "B", "quote_currency": "USDT"},  # unsupported in default
        {"product_id": "OFFLINE-USD", "base_currency": "O", "quote_currency": "USD", "trading_disabled": True},
    ]
    u.ingest_products(payload)

    report = u.get_spot_crypto_candidates(configured_symbols=[], supported_quotes={"USD"})

    cand_pids = {c["product_id"] for c in report["candidates"]}
    assert "GOOD-USD" in cand_pids
    assert "BAD-USDT" not in cand_pids
    assert "OFFLINE-USD" not in cand_pids

    reasons = {e["reason"] for e in report["excluded"]}
    assert any("unsupported_quote" in r for r in reasons)
    assert any("disabled" in r for r in reasons)


def test_placeholder_scores_and_ranking_present():
    u = CoinbaseMarketUniverse()
    u.ingest_products([
        {"product_id": "AAA-USD", "base_currency": "A", "quote_currency": "USD", "product_type": "spot"},
    ])
    report = u.get_spot_crypto_candidates(configured_symbols=["AAA-USD"])
    c = report["candidates"][0]
    assert "liquidity_score" in c
    assert "spread_score" in c
    assert "volatility_score" in c
    assert "prediction_score" in c
    assert "risk_score" in c
    assert c["allow_live_trading"] is False or c["is_currently_configured_live"] is True
