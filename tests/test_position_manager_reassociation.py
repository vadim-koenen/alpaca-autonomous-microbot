"""
Tests for conservative Coinbase bot-origin position re-association.

No broker APIs are called; broker and journal objects are local fakes.
"""

from __future__ import annotations

import csv
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ALPACA_API_KEY", "test_key_placeholder")
os.environ.setdefault("ALPACA_SECRET_KEY", "test_secret_placeholder")
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("ALPACA_PAPER", "true")

from journal import Journal, JournalRow
from order_manager import SessionState
from position_manager import PositionManager

ROOT = Path(__file__).resolve().parents[1]


class FakeStore:
    def __init__(self):
        self.events = []

    def record_event(self, **kwargs):
        self.events.append(kwargs)
        return True


class FakeBroker:
    def __init__(self, positions=None, statuses=None):
        self.positions = positions or []
        self.statuses = statuses or {}
        self.close_calls = []

    def get_all_positions(self):
        return list(self.positions)

    def get_order_status(self, order_id):
        return self.statuses.get(order_id, {})

    def close_position(self, symbol):
        self.close_calls.append(symbol)
        raise AssertionError("close_position must not be called by these tests")


class FakeJournal:
    def __init__(self, evidence=None):
        self.evidence = evidence
        self.warning_rows = []
        self.lookup_kwargs = None

    def find_recent_bot_entry(self, symbol, **kwargs):
        self.lookup_kwargs = {"symbol": symbol, **kwargs}
        return self.evidence

    def log_warning(self, **kwargs):
        self.warning_rows.append(kwargs)


def _btc_position():
    return SimpleNamespace(
        symbol="BTC/USD",
        qty=0.00000658,
        current_price=75939.835,
        market_value=0.4996841143,
        unrealized_pl=0.0,
    )


def _bot_evidence(**overrides):
    base = {
        "timestamp": "2026-05-26T21:30:18.694111Z",
        "asset_class": "crypto",
        "symbol": "BTC/USD",
        "strategy": "coinbase_probe",
        "action": "BUY",
        "decision": "PLACED",
        "price": "75944.895",
        "notional": "0.5",
        "qty": "0.00000658",
        "order_type": "limit",
        "order_id": "c7981c80-d910-4874-b52c-03edf53a57ec",
        "client_order_id": "cb-coinbase_probe-BTCUSD-buy-20260526T213018Z-entry-35b5",
        "intent_key": "coinbase:coinbase_probe:crypto:BTC/USD:buy:entry",
        "status": "pending_new",
        "source": "journal_recent_bot_entry",
    }
    base.update(overrides)
    return base


@pytest.fixture
def capture_position_saves(monkeypatch):
    saved = []
    monkeypatch.setattr(
        "position_manager.save_positions",
        lambda positions: saved.append({k: dict(v) for k, v in positions.items()}),
    )
    return saved


@pytest.fixture
def fake_event_store(monkeypatch):
    store = FakeStore()
    monkeypatch.setattr("position_manager.get_event_store", lambda: store)
    return store


def test_bot_origin_recovered_btc_with_journal_evidence_reassociated_safely(
    capture_position_saves,
    fake_event_store,
):
    broker = FakeBroker([_btc_position()])
    journal = FakeJournal(_bot_evidence())
    session = SessionState()

    PositionManager(broker, journal).monitor(session)

    tracked = session.open_positions["BTC/USD"]
    assert tracked["strategy"] == "coinbase_probe"
    assert tracked["order_id"] == "c7981c80-d910-4874-b52c-03edf53a57ec"
    assert tracked["client_order_id"].startswith("cb-coinbase_probe")
    assert tracked["order_status"] == "filled"
    assert tracked["recovery_source"] == "journal_reassociated"
    assert tracked["bot_opened"] is True
    assert tracked["counts_toward_exposure"] is True
    assert tracked["api_controllable"] is False
    assert tracked["exit_evaluation_enabled"] is False
    assert tracked["user_action_required"] is True
    assert tracked["manual_review_reason"] == "broker_close_capability_unconfirmed"
    assert broker.close_calls == []
    assert journal.lookup_kwargs["qty"] == pytest.approx(0.00000658)
    assert capture_position_saves
    assert fake_event_store.events[-1]["event_type"] == "bot_origin_position_reassociated"


def test_external_wallet_btc_without_journal_evidence_remains_broker_recovered(
    capture_position_saves,
    fake_event_store,
):
    broker = FakeBroker([_btc_position()])
    journal = FakeJournal(None)
    session = SessionState()

    PositionManager(broker, journal).monitor(session)

    tracked = session.open_positions["BTC/USD"]
    assert tracked["strategy"] == "recovered"
    assert tracked["order_id"] == ""
    assert tracked["order_status"] == "broker_recovered"
    assert tracked["recovery_source"] == "broker_position"
    assert tracked["bot_opened"] is False
    assert tracked["counts_toward_exposure"] is True
    assert tracked["api_controllable"] is False
    assert tracked["exit_evaluation_enabled"] is False
    assert tracked["user_action_required"] is True
    assert broker.close_calls == []
    assert capture_position_saves
    assert fake_event_store.events[-1]["event_type"] == "broker_recovered_position_detected"


def test_broker_recovered_eth_absent_from_snapshot_is_retained_for_manual_review(
    capture_position_saves,
    fake_event_store,
):
    broker = FakeBroker([])
    session = SessionState(open_positions={
        "ETH/USD": {
            "entry_price": 2500.0,
            "qty": 0.00248,
            "notional": 6.20,
            "stop_loss": 2462.5,
            "take_profit": 2562.5,
            "strategy": "recovered",
            "asset_class": "crypto",
            "order_id": "",
            "order_status": "broker_recovered",
            "recovery_source": "broker_position",
            "reconciliable": False,
            "api_controllable": False,
            "bot_opened": False,
            "exit_evaluation_enabled": False,
            "counts_toward_exposure": True,
            "user_action_required": True,
            "entry_time": "2026-05-26T21:30:18.694111+00:00",
            "side": "buy",
        }
    })

    PositionManager(broker, FakeJournal()).monitor(session)

    tracked = session.open_positions["ETH/USD"]
    assert tracked["order_status"] == "broker_recovered"
    assert tracked["exit_evaluation_enabled"] is False
    assert tracked["counts_toward_exposure"] is True
    assert tracked["user_action_required"] is True
    assert broker.close_calls == []
    assert capture_position_saves == []
    assert fake_event_store.events == []


def test_exit_evaluation_false_prevents_close_attempt(capture_position_saves, fake_event_store):
    broker = FakeBroker([_btc_position()])
    session = SessionState(open_positions={
        "BTC/USD": {
            "entry_price": 80000.0,
            "qty": 0.00000658,
            "notional": 0.5,
            "stop_loss": 79000.0,
            "take_profit": 81000.0,
            "strategy": "coinbase_probe",
            "asset_class": "crypto",
            "order_id": "bot-order",
            "order_status": "filled",
            "bot_opened": True,
            "api_controllable": False,
            "exit_evaluation_enabled": False,
            "counts_toward_exposure": True,
            "user_action_required": True,
        }
    })

    PositionManager(broker, FakeJournal()).monitor(session)

    assert broker.close_calls == []
    assert session.open_positions["BTC/USD"]["order_id"] == "bot-order"


def test_pending_order_not_removed_when_broker_position_snapshot_is_empty(
    capture_position_saves,
    fake_event_store,
):
    broker = FakeBroker([], statuses={
        "pending-order": {
            "normalized_status": "open",
            "raw_status": "OPEN",
            "filled_size": "0",
            "average_filled_price": "0",
        }
    })
    session = SessionState(open_positions={
        "BTC/USD": {
            "entry_price": 75944.89,
            "qty": 0.00000658,
            "notional": 0.5,
            "strategy": "coinbase_probe",
            "asset_class": "crypto",
            "order_id": "pending-order",
            "order_status": "pending_new",
            "bot_opened": True,
            "counts_toward_exposure": True,
        }
    })

    PositionManager(broker, FakeJournal()).monitor(session)

    assert "BTC/USD" in session.open_positions
    assert session.open_positions["BTC/USD"]["order_status"] == "pending_new"


def test_recent_filled_bot_order_not_removed_during_position_visibility_grace(
    capture_position_saves,
    fake_event_store,
):
    broker = FakeBroker([], statuses={
        "filled-order": {
            "normalized_status": "filled",
            "raw_status": "FILLED",
            "filled_size": "0.00000658",
            "average_filled_price": "75944.89",
            "total_fees": "0.006",
            "last_fill_time": datetime.now(timezone.utc).isoformat(),
            "settled": True,
        }
    })
    session = SessionState(open_positions={
        "BTC/USD": {
            "entry_price": 75944.89,
            "qty": 0.00000658,
            "notional": 0.5,
            "strategy": "coinbase_probe",
            "asset_class": "crypto",
            "order_id": "filled-order",
            "order_status": "pending_new",
            "bot_opened": True,
            "counts_toward_exposure": True,
            "entry_time": datetime.now(timezone.utc),
        }
    })

    PositionManager(broker, FakeJournal()).monitor(session)

    assert "BTC/USD" in session.open_positions
    assert session.open_positions["BTC/USD"]["order_status"] == "filled"


def test_old_filled_bot_order_absent_at_broker_is_removed(
    capture_position_saves,
    fake_event_store,
):
    broker = FakeBroker([])
    session = SessionState(open_positions={
        "BTC/USD": {
            "entry_price": 75944.89,
            "qty": 0.00000658,
            "notional": 0.5,
            "strategy": "coinbase_probe",
            "asset_class": "crypto",
            "order_id": "old-filled-order",
            "order_status": "filled",
            "bot_opened": True,
            "counts_toward_exposure": True,
            "entry_time": datetime.now(timezone.utc) - timedelta(minutes=30),
        }
    })

    PositionManager(broker, FakeJournal()).monitor(session)

    assert "BTC/USD" not in session.open_positions


def test_restore_state_keeps_pending_order_absent_from_broker_for_reconciliation(
    monkeypatch,
    capture_position_saves,
    fake_event_store,
):
    saved_positions = {
        "BTC/USD": {
            "entry_price": 75944.89,
            "qty": 0.00000658,
            "notional": 0.5,
            "strategy": "coinbase_probe",
            "asset_class": "crypto",
            "order_id": "pending-order",
            "order_status": "pending_new",
            "bot_opened": True,
            "counts_toward_exposure": True,
        }
    }
    monkeypatch.setattr("position_manager.load_saved_positions", lambda: saved_positions)
    broker = FakeBroker([], statuses={
        "pending-order": {
            "normalized_status": "filled",
            "raw_status": "FILLED",
            "filled_size": "0.00000658",
            "average_filled_price": "75944.89",
            "total_fees": "0.006",
            "last_fill_time": datetime.now(timezone.utc).isoformat(),
            "settled": True,
        }
    })
    session = SessionState()

    PositionManager(broker, FakeJournal()).restore_state(session)

    assert "BTC/USD" in session.open_positions
    assert session.open_positions["BTC/USD"]["order_status"] == "filled"


def test_restore_state_keeps_broker_recovered_absent_from_broker_for_manual_review(
    monkeypatch,
    capture_position_saves,
    fake_event_store,
):
    saved_positions = {
        "ETH/USD": {
            "entry_price": 2500.0,
            "qty": 0.00248,
            "notional": 6.20,
            "strategy": "recovered",
            "asset_class": "crypto",
            "order_id": "",
            "order_status": "broker_recovered",
            "recovery_source": "broker_position",
            "api_controllable": False,
            "bot_opened": False,
            "exit_evaluation_enabled": False,
            "counts_toward_exposure": True,
            "user_action_required": True,
        }
    }
    monkeypatch.setattr("position_manager.load_saved_positions", lambda: saved_positions)
    broker = FakeBroker([])
    session = SessionState()

    PositionManager(broker, FakeJournal()).restore_state(session)

    assert "ETH/USD" in session.open_positions
    assert session.open_positions["ETH/USD"]["order_status"] == "broker_recovered"
    assert session.open_positions["ETH/USD"]["counts_toward_exposure"] is True
    assert broker.close_calls == []
    assert capture_position_saves
    assert fake_event_store.events == []


def test_journal_bot_entry_requires_matching_qty_and_no_later_close(tmp_path):
    journal_path = tmp_path / "journal.csv"
    rows = [
        {
            "timestamp": "2026-05-26T20:15:48.191842Z",
            "mode": "live",
            "asset_class": "crypto",
            "symbol": "BTC/USD",
            "strategy": "coinbase_probe",
            "action": "BUY",
            "decision": "PLACED",
            "price": "75999.705",
            "notional": "0.5",
            "qty": "0.00000658",
            "order_id": "old-order",
            "client_order_id": "old-client",
            "intent_key": "coinbase:coinbase_probe:crypto:BTC/USD:buy:entry",
            "status": "pending_new",
        },
        {
            "timestamp": "2026-05-26T20:28:46.316237Z",
            "symbol": "BTC/USD",
            "action": "ERROR",
            "decision": "ERROR",
            "error": "Position closed during emergency halt",
        },
        {
            "timestamp": "2026-05-26T21:30:18.694111Z",
            "mode": "live",
            "asset_class": "crypto",
            "symbol": "BTC/USD",
            "strategy": "coinbase_probe",
            "action": "BUY",
            "decision": "PLACED",
            "price": "75944.895",
            "notional": "0.5",
            "qty": "0.00000658",
            "order_id": "new-order",
            "client_order_id": "new-client",
            "intent_key": "coinbase:coinbase_probe:crypto:BTC/USD:buy:entry",
            "status": "pending_new",
        },
    ]
    with journal_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=JournalRow.columns())
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in JournalRow.columns()})

    journal = object.__new__(Journal)
    journal._path = journal_path

    evidence = journal.find_recent_bot_entry(
        "BTC/USD",
        qty=0.00000658,
        notional=0.5,
        window_seconds=10 * 365 * 24 * 60 * 60,
    )

    assert evidence is not None
    assert evidence["order_id"] == "new-order"
    assert journal.find_recent_bot_entry(
        "BTC/USD",
        qty=0.00001234,
        notional=0.5,
        window_seconds=10 * 365 * 24 * 60 * 60,
    ) is None


def test_risk_caps_not_changed_by_reassociation_patch():
    import yaml

    coinbase = yaml.safe_load((ROOT / "config_coinbase_crypto.yaml").read_text())
    alpaca = yaml.safe_load((ROOT / "config_alpaca_stocks.yaml").read_text())

    assert coinbase["global_risk"]["max_total_live_exposure_usd"] == 6.00
    assert coinbase["crypto"]["max_trade_notional_usd"] == 2.00
    assert coinbase["crypto"]["max_total_crypto_exposure_usd"] == 4.00
    assert alpaca["global_risk"]["max_total_live_exposure_usd"] == 6.00
    assert alpaca["equities"]["max_trade_notional_usd"] == 2.00
    assert alpaca["equities"]["max_total_equity_exposure_usd"] == 4.00
