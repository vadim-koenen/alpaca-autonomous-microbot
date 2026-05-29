import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ALPACA_API_KEY", "test_key_placeholder")
os.environ.setdefault("ALPACA_SECRET_KEY", "test_secret_placeholder")
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("ALPACA_PAPER", "true")

from order_manager import OrderManager, SessionState
from risk_manager import TradeProposal


def _proposal(**overrides):
    base = dict(
        symbol="BTC/USD",
        asset_class="crypto",
        strategy="coinbase_probe",
        side="buy",
        order_type="limit",
        notional=0.50,
        limit_price=50000.0,
        confidence=0.80,
        bid=49990.0,
        ask=50010.0,
        price=50000.0,
        quote_time=datetime.now(timezone.utc),
        stop_loss_price=49000.0,
        take_profit_price=51500.0,
        meta={"spread_pct": 0.04},
    )
    base.update(overrides)
    return TradeProposal(**base)


class FakeStore:
    def __init__(self):
        self.orders = []
        self.incidents = []

    def record_order(self, **kwargs):
        self.orders.append(kwargs)
        return True

    def record_incident(self, **kwargs):
        self.incidents.append(kwargs)
        return True


class FakeJournal:
    def __init__(self, recent=None):
        self.recent = recent
        self.skips = []
        self.previews = []
        self.orders = []

    def find_recent_order_intent(self, *args, **kwargs):
        return self.recent

    def log_skip(self, **kwargs):
        self.skips.append(kwargs)

    def log_order_preview(self, **kwargs):
        self.previews.append(kwargs)

    def log_order(self, **kwargs):
        self.orders.append(kwargs)


class FakeBroker:
    def __init__(self, open_orders=None, open_error=""):
        self.open_orders = open_orders or []
        self.last_open_orders_error = open_error
        self.submitted = False

    def get_open_orders(self):
        return self.open_orders

    def place_limit_order(self, **kwargs):
        self.submitted = True
        return SimpleNamespace(
            id="broker-order",
            status="pending_new",
            client_order_id=kwargs["client_order_id"],
        )


@pytest.fixture(autouse=True)
def paper_config(monkeypatch, tmp_path):
    import utils

    cfg = utils.load_config()
    original_mode = cfg.get("mode")
    original_global = dict(cfg.get("global_risk", {}))
    cfg["mode"] = "paper"
    cfg["global_risk"] = {
        **original_global,
        "duplicate_order_safety_window_seconds": 900,
    }
    monkeypatch.setenv("BROKER", "coinbase")
    monkeypatch.setattr("order_manager.save_positions", lambda _positions: None)
    yield
    cfg["mode"] = original_mode
    cfg["global_risk"] = original_global


def test_duplicate_local_open_position_blocks_new_entry(monkeypatch):
    store = FakeStore()
    monkeypatch.setattr("order_manager.get_event_store", lambda: store)
    broker = FakeBroker()
    journal = FakeJournal()
    session = SessionState(open_positions={
        "BTC/USD": {
            "strategy": "coinbase_probe",
            "asset_class": "crypto",
            "side": "buy",
            "client_order_id": "existing-client",
        }
    })

    order = OrderManager(broker, journal).execute(
        _proposal(), session, account_equity=10.0, buying_power=10.0, open_positions=1
    )

    assert order is None
    assert broker.submitted is False
    assert journal.skips
    assert "duplicate_order_intent_detected" in journal.skips[0]["reason"]
    assert store.orders[0]["status"] == "blocked"
    assert store.orders[0]["payload"]["source"] == "local_state"


def test_duplicate_broker_open_order_blocks_new_entry(monkeypatch):
    store = FakeStore()
    monkeypatch.setattr("order_manager.get_event_store", lambda: store)
    broker = FakeBroker(open_orders=[
        SimpleNamespace(symbol="BTC/USD", side="buy", client_order_id="open-client")
    ])
    journal = FakeJournal()
    session = SessionState()

    order = OrderManager(broker, journal).execute(
        _proposal(), session, account_equity=10.0, buying_power=10.0, open_positions=0
    )

    assert order is None
    assert broker.submitted is False
    assert store.orders[0]["payload"]["source"] == "broker_open_orders"
    assert store.orders[0]["payload"]["existing_client_order_id"] == "open-client"


def test_recent_journal_intent_blocks_new_entry(monkeypatch):
    store = FakeStore()
    monkeypatch.setattr("order_manager.get_event_store", lambda: store)
    broker = FakeBroker()
    journal = FakeJournal(recent={"client_order_id": "recent-client"})
    session = SessionState()

    order = OrderManager(broker, journal).execute(
        _proposal(), session, account_equity=10.0, buying_power=10.0, open_positions=0
    )

    assert order is None
    assert broker.submitted is False
    assert store.orders[0]["payload"]["source"] == "journal_recent"


def test_broker_open_order_check_failure_blocks_fail_closed(monkeypatch):
    store = FakeStore()
    monkeypatch.setattr("order_manager.get_event_store", lambda: store)
    broker = FakeBroker(open_error="network unavailable")
    journal = FakeJournal()
    session = SessionState()

    order = OrderManager(broker, journal).execute(
        _proposal(), session, account_equity=10.0, buying_power=10.0, open_positions=0
    )

    assert order is None
    assert broker.submitted is False
    assert store.orders[0]["status"] == "blocked"
    assert store.orders[0]["payload"]["reason"] == "order_state_uncertain"


def test_traceable_client_order_id_still_logged_and_stored(monkeypatch):
    store = FakeStore()
    monkeypatch.setattr("order_manager.get_event_store", lambda: store)
    broker = FakeBroker()
    journal = FakeJournal()
    session = SessionState()

    order = OrderManager(broker, journal).execute(
        _proposal(), session, account_equity=10.0, buying_power=10.0, open_positions=0
    )

    assert order is not None
    client_order_id = order.client_order_id
    assert "coinbase_probe" in client_order_id
    assert journal.previews[0]["client_order_id"] == client_order_id
    assert journal.orders[0]["client_order_id"] == client_order_id
    assert session.open_positions["BTC/USD"]["client_order_id"] == client_order_id
    assert session.open_positions["BTC/USD"]["intent_key"] == journal.orders[0]["intent_key"]
