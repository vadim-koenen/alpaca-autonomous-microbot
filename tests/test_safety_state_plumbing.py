"""
Tests for safety/state plumbing added around recovered exposure and
traceable client_order_id handling. No broker API calls are made.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ALPACA_API_KEY", "test_key_placeholder")
os.environ.setdefault("ALPACA_SECRET_KEY", "test_secret_placeholder")
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("ALPACA_PAPER", "true")

from order_manager import OrderManager, SessionState
from risk_manager import AccountState, RiskManager, TradeProposal
from utils import (
    build_client_order_id,
    calculate_crypto_entry_blockers,
    calculate_crypto_exposure,
    load_saved_positions,
    now_utc,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def paper_config():
    import utils

    cfg = utils.load_config()
    original_mode = cfg.get("mode")
    original_crypto = dict(cfg.get("crypto", {}))
    cfg["mode"] = "paper"
    cfg["crypto"] = {
        **original_crypto,
        "symbols": ["BTC/USD", "ETH/USD", "SOL/USD"],
        "max_total_crypto_exposure_usd": 4.0,
    }
    yield cfg
    cfg["mode"] = original_mode
    cfg["crypto"] = original_crypto


def _proposal(**overrides) -> TradeProposal:
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
        meta={
            "spread_pct": 0.04,
            "net_expected_edge_pct": 1.5,
            "worst_case_edge_pct": 0.8,
            "reward_risk_ratio": 1.5,
        },
    )
    base.update(overrides)
    return TradeProposal(**base)


def _state(**overrides) -> AccountState:
    base = dict(
        equity=10.0,
        buying_power=10.0,
        open_positions=0,
        open_position_symbols=[],
        open_orders=0,
        open_order_symbols=[],
        daily_realized_pnl=0.0,
        daily_trade_count=0,
        consecutive_losses=0,
        crypto_enabled=True,
        options_enabled=False,
        options_level=0,
        margin_enabled=False,
        short_selling_enabled=False,
        account_blocked=False,
        trading_blocked=False,
        api_error_count=0,
    )
    base.update(overrides)
    return AccountState(**base)


def test_account_state_default_compatibility():
    state = AccountState()
    assert state.tracked_crypto_exposure_usd == 0.0
    assert state.broker_recovered_crypto_exposure_usd == 0.0


def test_crypto_exposure_block_reason_mentions_external_untradeable(paper_config):
    proposal = _proposal()
    state = _state(
        tracked_crypto_exposure_usd=6.20,
        broker_recovered_crypto_exposure_usd=6.20,
    )

    allowed, reason = RiskManager().check(proposal, state)

    assert allowed is False
    assert "external/untradeable" in reason


def test_crypto_exposure_respects_counts_toward_exposure():
    positions = {
        "BTC/USD": {
            "asset_class": "crypto",
            "notional": 1.25,
            # Missing counts_toward_exposure stays conservative and counts.
            "order_status": "filled",
        },
        "ETH/USD": {
            "asset_class": "crypto",
            "notional": 6.20,
            "order_status": "broker_recovered",
            "counts_toward_exposure": False,
        },
        "SOL/USD": {
            "asset_class": "crypto",
            "notional": 3.00,
            "order_status": "broker_recovered",
            "counts_toward_exposure": True,
        },
        "SPY": {
            "asset_class": "equity",
            "notional": 100.00,
        },
    }

    total, recovered = calculate_crypto_exposure(positions)

    assert total == pytest.approx(4.25)
    assert recovered == pytest.approx(3.00)


def test_crypto_entry_blockers_ignore_exposure_exclusion_without_override():
    positions = {
        "BTC/USD": {
            "asset_class": "crypto",
            "notional": 0.50,
            "counts_toward_exposure": False,
            "user_action_required": True,
            "api_controllable": False,
            "exit_evaluation_enabled": False,
        }
    }

    manual_count, non_controllable_count = calculate_crypto_entry_blockers(positions)

    assert manual_count == 1
    assert non_controllable_count == 1


def test_crypto_entry_blocker_override_requires_explicit_human_approval_fields():
    positions = {
        "BTC/USD": {
            "asset_class": "crypto",
            "notional": 0.50,
            "counts_toward_exposure": False,
            "user_action_required": True,
            "api_controllable": False,
            "exit_evaluation_enabled": False,
            "manual_review_entry_override_approved": True,
            "manual_review_entry_override_scope": "allow_new_crypto_entries",
            "manual_review_entry_override_reason": "human approved separate risk review",
        }
    }

    manual_count, non_controllable_count = calculate_crypto_entry_blockers(positions)

    assert manual_count == 0
    assert non_controllable_count == 0


def test_broker_recovered_positions_normalize_from_saved_state(tmp_path, monkeypatch):
    import utils

    monkeypatch.setenv("BROKER", "coinbase")
    monkeypatch.setattr(utils, "STATE_ROOT", tmp_path)
    state_dir = tmp_path / "coinbase"
    state_dir.mkdir(parents=True)
    (state_dir / "open_positions.json").write_text(json.dumps({
        "saved_at": now_utc().isoformat(),
        "state_namespace": "coinbase",
        "positions": {
            "ETH/USD": {
                "entry_price": 2500.0,
                "qty": 0.00248,
                "notional": 6.20,
                "strategy": "recovered",
                "asset_class": "crypto",
                "order_id": "",
                "order_status": "pending_new",
            }
        },
    }))

    positions = load_saved_positions()
    pos = positions["ETH/USD"]

    assert pos["order_status"] == "broker_recovered"
    assert pos["api_controllable"] is False
    assert pos["exit_evaluation_enabled"] is False
    assert pos["counts_toward_exposure"] is True
    assert pos["user_action_required"] is True


def test_build_client_order_id_is_traceable_sanitized_and_unique():
    ts = datetime(2026, 5, 26, 13, 25, 0, tzinfo=timezone.utc)

    first = build_client_order_id(
        broker="coinbase",
        strategy="coinbase_probe",
        symbol="BTC/USD",
        side="buy",
        purpose="entry",
        timestamp=ts,
    )
    second = build_client_order_id(
        broker="coinbase",
        strategy="coinbase_probe",
        symbol="BTC/USD",
        side="buy",
        purpose="entry",
        timestamp=ts,
    )

    assert first.startswith("cb-")
    assert "coinbase_probe" in first
    assert "BTCUSD" in first
    assert "buy" in first
    assert "20260526T132500Z" in first
    assert "entry" in first
    assert "/" not in first
    assert " " not in first
    assert len(first) <= 64
    assert first != second


def test_order_manager_persists_and_journals_client_order_id(monkeypatch, tmp_path, paper_config):
    import utils

    monkeypatch.setenv("BROKER", "coinbase")
    monkeypatch.setattr(utils, "STATE_ROOT", tmp_path)
    monkeypatch.setattr("order_manager.save_positions", utils.save_positions)
    class FakeStore:
        def record_order(self, **kwargs):
            return True

        def record_incident(self, **kwargs):
            return True

    monkeypatch.setattr("order_manager.get_event_store", lambda: FakeStore())

    class FakeBroker:
        def __init__(self):
            self.submitted = None

        def get_open_orders(self):
            return []

        def place_limit_order(self, **kwargs):
            self.submitted = kwargs
            return SimpleNamespace(
                id="broker-order-123",
                status="pending_new",
                client_order_id=kwargs["client_order_id"],
            )

    class FakeJournal:
        def __init__(self):
            self.order_row = None
            self.preview_row = None

        def log_skip(self, **kwargs):
            raise AssertionError(f"unexpected skip: {kwargs}")

        def find_recent_order_intent(self, *args, **kwargs):
            return None

        def log_order_preview(self, **kwargs):
            self.preview_row = kwargs

        def log_order(self, **kwargs):
            self.order_row = kwargs

    broker = FakeBroker()
    journal = FakeJournal()
    session = SessionState()

    order = OrderManager(broker, journal).execute(
        proposal=_proposal(),
        session=session,
        account_equity=10.0,
        buying_power=10.0,
        open_positions=0,
    )

    client_order_id = broker.submitted["client_order_id"]
    assert order.client_order_id == client_order_id
    assert journal.preview_row["client_order_id"] == client_order_id
    assert journal.order_row["client_order_id"] == client_order_id
    assert journal.order_row["intent_key"]
    assert session.open_positions["BTC/USD"]["client_order_id"] == client_order_id
    assert session.open_positions["BTC/USD"]["intent_key"] == journal.order_row["intent_key"]
    assert session.open_positions["BTC/USD"]["order_id"] == "broker-order-123"
    assert session.open_positions["BTC/USD"]["counts_toward_exposure"] is True
    assert session.open_positions["BTC/USD"]["api_controllable"] is True
    assert session.open_positions["BTC/USD"]["bot_opened"] is True
    assert session.open_positions["BTC/USD"]["exit_evaluation_enabled"] is True
    assert session.open_positions["BTC/USD"]["user_action_required"] is False

    saved = json.loads((tmp_path / "coinbase" / "open_positions.json").read_text())
    saved_pos = saved["positions"]["BTC/USD"]
    assert saved_pos["counts_toward_exposure"] is True
    assert saved_pos["api_controllable"] is True
    assert saved_pos["bot_opened"] is True
    assert saved_pos["exit_evaluation_enabled"] is True
    assert saved_pos["user_action_required"] is False


def test_saved_bot_position_missing_safety_fields_defaults_true(tmp_path, monkeypatch):
    import utils

    monkeypatch.setenv("BROKER", "coinbase")
    monkeypatch.setattr(utils, "STATE_ROOT", tmp_path)
    state_dir = tmp_path / "coinbase"
    state_dir.mkdir(parents=True)
    (state_dir / "open_positions.json").write_text(json.dumps({
        "saved_at": now_utc().isoformat(),
        "state_namespace": "coinbase",
        "positions": {
            "BTC/USD": {
                "asset_class": "crypto",
                "strategy": "coinbase_probe",
                "order_id": "bot-order",
                "order_status": "filled",
                "notional": 0.50,
            }
        },
    }))

    pos = utils.load_saved_positions()["BTC/USD"]

    assert pos["counts_toward_exposure"] is True
    assert pos["api_controllable"] is True
    assert pos["bot_opened"] is True
    assert pos["exit_evaluation_enabled"] is True
    assert pos["user_action_required"] is False


def test_saved_position_explicit_counts_false_remains_false(tmp_path, monkeypatch):
    import utils

    monkeypatch.setenv("BROKER", "coinbase")
    monkeypatch.setattr(utils, "STATE_ROOT", tmp_path)
    state_dir = tmp_path / "coinbase"
    state_dir.mkdir(parents=True)
    (state_dir / "open_positions.json").write_text(json.dumps({
        "saved_at": now_utc().isoformat(),
        "state_namespace": "coinbase",
        "positions": {
            "SOL/USD": {
                "asset_class": "crypto",
                "strategy": "coinbase_probe",
                "order_id": "bot-order",
                "order_status": "filled",
                "notional": 0.50,
                "counts_toward_exposure": False,
            }
        },
    }))

    pos = utils.load_saved_positions()["SOL/USD"]

    assert pos["counts_toward_exposure"] is False
    assert pos["api_controllable"] is True
    assert pos["exit_evaluation_enabled"] is True


def test_broker_recovered_safety_fields_remain_non_controllable(tmp_path, monkeypatch):
    import utils

    monkeypatch.setenv("BROKER", "coinbase")
    monkeypatch.setattr(utils, "STATE_ROOT", tmp_path)
    state_dir = tmp_path / "coinbase"
    state_dir.mkdir(parents=True)
    (state_dir / "open_positions.json").write_text(json.dumps({
        "saved_at": now_utc().isoformat(),
        "state_namespace": "coinbase",
        "positions": {
            "ETH/USD": {
                "asset_class": "crypto",
                "strategy": "recovered",
                "order_status": "broker_recovered",
                "notional": 6.00,
                "api_controllable": True,
                "exit_evaluation_enabled": True,
            }
        },
    }))

    pos = utils.load_saved_positions()["ETH/USD"]

    assert pos["order_status"] == "broker_recovered"
    assert pos["api_controllable"] is False
    assert pos["bot_opened"] is False
    assert pos["exit_evaluation_enabled"] is False
    assert pos["counts_toward_exposure"] is True
    assert pos["user_action_required"] is True


def test_state_consistency_patch_did_not_change_risk_caps():
    import yaml

    coinbase = yaml.safe_load((ROOT / "config_coinbase_crypto.yaml").read_text())
    alpaca = yaml.safe_load((ROOT / "config_alpaca_stocks.yaml").read_text())

    assert coinbase["global_risk"]["max_total_live_exposure_usd"] == 8.00
    assert coinbase["crypto"]["max_trade_notional_usd"] == 2.00
    assert coinbase["crypto"]["max_total_crypto_exposure_usd"] == 8.00
    assert alpaca["global_risk"]["max_total_live_exposure_usd"] == 6.00
    assert alpaca["equities"]["max_trade_notional_usd"] == 2.00
    assert alpaca["equities"]["max_total_equity_exposure_usd"] == 4.00


def test_reconcile_script_smoke():
    result = subprocess.run(
        ["bash", "scripts/reconcile.sh"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert "BROKER RECONCILIATION REPORT" in result.stdout
    assert "crypto_exposure_cap" in result.stdout
    assert "external_untradeable_exposure" in result.stdout
    assert "entry_allowed" in result.stdout
