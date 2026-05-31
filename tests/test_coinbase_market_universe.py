"""
P2-012A tests for Coinbase Market Universe classification scaffold.
"""

import json
import tempfile
from pathlib import Path

from coinbase_market_universe import CoinbaseMarketUniverse


def test_parses_spot_crypto_payload():
    payload = [
        {"product_id": "BTC-USD", "base_currency": "BTC", "quote_currency": "USD", "product_type": "spot", "status": "online"},
        {"product_id": "ETH-USD", "base_currency": "ETH", "quote_currency": "USD", "product_type": "spot"},
    ]
    u = CoinbaseMarketUniverse()
    u.ingest_products(payload)
    p = u.get_product("BTC-USD")
    assert p is not None
    assert p.product_type == "spot_crypto"
    assert p.allow_live_trading is True   # currently configured live symbol


def test_parses_perpetual_future_payload():
    payload = [
        {"product_id": "BTC-PERP", "base_currency": "BTC", "quote_currency": "USD", "contract_type": "perpetual"},
    ]
    u = CoinbaseMarketUniverse()
    u.ingest_products(payload)
    p = u.get_product("BTC-PERP")
    assert p.product_type == "perpetual_future"
    assert p.allow_live_trading is False  # newly discovered


def test_classifies_gold_silver_like_products():
    payload = [
        {"product_id": "GOLD-PERP", "base_currency": "GOLD", "quote_currency": "USD", "contract_type": "perpetual"},
        {"product_id": "SILVER-PERP", "base_currency": "SILVER", "quote_currency": "USD"},
        {"product_id": "XAU-USD", "base_currency": "XAU", "quote_currency": "USD"},
    ]
    u = CoinbaseMarketUniverse()
    u.ingest_products(payload)

    for pid in ["GOLD-PERP", "SILVER-PERP", "XAU-USD"]:
        p = u.get_product(pid)
        assert p is not None
        assert p.product_type in ("commodity_linked_derivative", "perpetual_future")
        assert p.is_gold_or_silver_like is True
        assert p.allow_live_trading is False   # deliberately disabled


def test_newly_discovered_products_default_disabled():
    payload = [
        {"product_id": "DOGE-PERP", "base_currency": "DOGE", "quote_currency": "USD", "contract_type": "perpetual"},
    ]
    u = CoinbaseMarketUniverse()
    u.ingest_products(payload)
    p = u.get_product("DOGE-PERP")
    assert p.allow_live_trading is False


def test_summarize_and_gold_silver_list():
    payload = [
        {"product_id": "BTC-USD", "base_currency": "BTC", "quote_currency": "USD", "product_type": "spot"},
        {"product_id": "GOLD-PERP", "base_currency": "GOLD", "quote_currency": "USD", "contract_type": "perpetual"},
    ]
    u = CoinbaseMarketUniverse()
    u.ingest_products(payload)
    s = u.summarize()
    assert s["total_products"] == 2
    assert "GOLD-PERP" in s["gold_silver_like"]
    assert s["tradable_under_current_policy"] == 1  # only BTC-USD
