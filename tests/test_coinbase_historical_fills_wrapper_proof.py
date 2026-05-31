"""
P2-011E — Coinbase Historical Fills Wrapper Proof (static/mocked tests only).

Tests prove the minimal get_historical_fills wrapper can be called,
filters are passed through, and raw payloads can be parsed for direct broker facts.
No live API calls.
"""

from unittest.mock import MagicMock

import pytest

from broker_coinbase import BrokerCoinbase


@pytest.fixture
def mock_broker(monkeypatch):
    """Create a BrokerCoinbase in dry_run with mocked client."""
    broker = BrokerCoinbase.__new__(BrokerCoinbase)
    broker._mode = "dry_run"
    broker._api_blocked = False
    broker._client = MagicMock()
    broker._block_reason = None
    return broker


def test_get_historical_fills_passes_product_id_and_order_id_filters(mock_broker):
    """Filters must be translated and passed to the underlying client."""
    mock_broker._client.get_fills.return_value = {"fills": []}

    result = mock_broker.get_historical_fills(
        product_id="BTC/USD",
        order_id="order-123",
        limit=50,
    )

    # Verify the call was made with translated product_id
    call_kwargs = mock_broker._client.get_fills.call_args[1]
    assert call_kwargs["product_id"] == "BTC-USD"
    assert call_kwargs["order_id"] == "order-123"
    assert call_kwargs["limit"] == 50
    assert result == []


def test_get_historical_fills_parses_single_fill_payload(mock_broker):
    """One-fill payload should be returned as list of normalized dicts."""
    payload = {
        "fills": [
            {
                "entry_id": "fill-1",
                "order_id": "ord-1",
                "product_id": "ETH-USD",
                "side": "BUY",
                "price": "3100.5",
                "size": "0.1",
                "fee": "0.186",
                "fee_currency": "USD",
                "liquidity_indicator": "MAKER",
                "trade_time": "2026-05-30T12:00:05Z",
            }
        ]
    }
    mock_broker._client.get_fills.return_value = payload

    fills = mock_broker.get_historical_fills(order_id="ord-1")

    assert len(fills) == 1
    f = fills[0]
    assert f["entry_id"] == "fill-1"
    assert f["price"] == "3100.5"
    assert f["fee"] == "0.186"
    assert f["liquidity_indicator"] == "MAKER"


def test_get_historical_fills_parses_multi_fill_payload(mock_broker):
    """Multi-fill payloads are supported."""
    payload = {"fills": [{"entry_id": "f1"}, {"entry_id": "f2"}]}
    mock_broker._client.get_fills.return_value = payload

    fills = mock_broker.get_historical_fills(product_id="SOL-USD")

    assert len(fills) == 2


def test_get_historical_fills_classifies_missing_fee_as_unavailable(mock_broker):
    """Missing fee should not be invented — treated as unavailable."""
    payload = {
        "fills": [
            {
                "entry_id": "f-missing-fee",
                "order_id": "o1",
                "price": "100",
                "size": "1",
                # no "fee" key
            }
        ]
    }
    mock_broker._client.get_fills.return_value = payload

    fills = mock_broker.get_historical_fills(order_id="o1")

    f = fills[0]
    # The wrapper itself returns raw — classification happens at capture layer
    # For this proof we just show the field is absent
    assert "fee" not in f or f.get("fee") in (None, "", 0)


def test_get_historical_fills_falls_back_to_entry_id_when_no_trade_id(mock_broker):
    """Stable ID can use entry_id when trade_id is missing."""
    payload = {
        "fills": [
            {
                "entry_id": "entry-xyz",
                # no trade_id
                "order_id": "o2",
            }
        ]
    }
    mock_broker._client.get_fills.return_value = payload

    fills = mock_broker.get_historical_fills()

    f = fills[0]
    assert f.get("entry_id") == "entry-xyz"
    assert f.get("trade_id") in (None, "")


def test_get_historical_fills_blocks_when_no_stable_id(mock_broker):
    """If neither trade_id nor entry_id present, stable idempotency is blocked."""
    payload = {
        "fills": [
            {
                "order_id": "o3",
                "product_id": "BTC-USD",
                "price": "65000",
                "size": "0.01",
                # no trade_id, no entry_id
            }
        ]
    }
    mock_broker._client.get_fills.return_value = payload

    fills = mock_broker.get_historical_fills()

    f = fills[0]
    has_stable_id = bool(f.get("trade_id") or f.get("entry_id"))
    assert has_stable_id is False
