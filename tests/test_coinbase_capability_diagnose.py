"""Tests for scripts/coinbase_position_capability_diagnose.py.

All tests use fake state and mocked/absent broker data.
No live Coinbase API calls are made. No state is mutated.

Verified guarantees:
  - broker_recovered BTC with unknown origin stays manual-review
  - external-wallet BTC (no order_id) stays manual-review
  - bot-placed, api_controllable BTC with order_id → close_capability=yes
  - diagnostic never mutates state
  - no order endpoint is called
  - output includes recommended_action
  - JSON output is valid JSON
"""

from __future__ import annotations

import csv
import json
import sys
import tempfile
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# Make the scripts directory importable
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import coinbase_position_capability_diagnose as diag  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_position(
    symbol: str = "BTC/USD",
    order_status: str = "filled",
    api_controllable: bool = True,
    bot_opened: bool = True,
    exit_evaluation_enabled: bool = True,
    user_action_required: bool = False,
    order_id: str = "order-abc",
    client_order_id: str = "cb-probe-BTCUSD-buy",
    notional: float = 0.50,
    strategy: str = "coinbase_probe",
) -> dict:
    return {
        "order_status": order_status,
        "api_controllable": api_controllable,
        "bot_opened": bot_opened,
        "exit_evaluation_enabled": exit_evaluation_enabled,
        "user_action_required": user_action_required,
        "order_id": order_id,
        "client_order_id": client_order_id,
        "notional": notional,
        "strategy": strategy,
        "entry_price": 75000.0,
        "entry_time": "2026-05-26T23:30:34+00:00",
        "fill_price": 75010.0,
        "counts_toward_exposure": True,
    }


def _journal_no_evidence() -> dict:
    return {
        "journal_evidence_found": False,
        "journal_error": "",
        "matching_client_order_id": "",
        "matching_order_id": "",
        "row_count": 0,
        "actions_seen": [],
    }


def _journal_with_evidence(coid: str = "cb-probe-BTCUSD-buy") -> dict:
    return {
        "journal_evidence_found": True,
        "journal_error": "",
        "matching_client_order_id": coid,
        "matching_order_id": "order-abc",
        "row_count": 3,
        "actions_seen": ["BUY", "PLACED", "FILLED"],
    }


def _broker_unavailable() -> dict:
    return {
        "broker_available": False,
        "broker_error": "broker check skipped",
        "account_equity": None,
        "broker_balances": {},
        "order_status_checks": {},
    }


def _broker_with_balance(symbol: str = "BTC/USD", value: float = 0.50) -> dict:
    return {
        "broker_available": True,
        "broker_error": "",
        "account_equity": 29.93,
        "broker_balances": {symbol: value},
        "order_status_checks": {
            "order-abc": {
                "normalized_status": "filled",
                "settled": True,
            }
        },
    }


# ---------------------------------------------------------------------------
# 1. broker_recovered BTC with journal evidence → still manual-review
# ---------------------------------------------------------------------------

def test_broker_recovered_with_journal_evidence_stays_manual_review():
    pos = _make_position(
        order_status="broker_recovered",
        api_controllable=False,
        bot_opened=False,
        exit_evaluation_enabled=False,
        user_action_required=True,
        order_id="",
        client_order_id="",
    )
    journal = _journal_with_evidence()
    broker_data = _broker_unavailable()

    result = diag._classify_position("BTC/USD", pos, journal, broker_data, [])

    # Journal evidence may exist but close capability must not be auto-promoted
    assert result["advanced_trade_close_capability"] in ("unknown", "no"), (
        "broker_recovered position must not have close_capability=yes "
        "even if journal evidence is found"
    )
    assert result["user_action_required"] is True
    assert result["recommended_action"]  # non-empty


# ---------------------------------------------------------------------------
# 2. External wallet BTC (no order_id) → manual-review / close_capability=no
# ---------------------------------------------------------------------------

def test_external_wallet_btc_no_order_id_stays_manual_review():
    pos = _make_position(
        order_status="broker_recovered",
        api_controllable=False,
        bot_opened=False,
        exit_evaluation_enabled=False,
        user_action_required=True,
        order_id="",
        client_order_id="",
    )
    journal = _journal_no_evidence()
    broker_data = _broker_unavailable()

    result = diag._classify_position("BTC/USD", pos, journal, broker_data, [])

    # No order_id + api_controllable=False + user_action_required=True → "no"
    assert result["advanced_trade_close_capability"] == "no"
    assert result["user_action_required"] is True
    assert "manual" in result["recommended_action"].lower() or \
           "sell manually" in result["recommended_action"].lower()


# ---------------------------------------------------------------------------
# 3. Bot-placed, api_controllable, with order_id → close_capability=yes
# ---------------------------------------------------------------------------

def test_bot_placed_api_controllable_with_order_id_is_closeable():
    pos = _make_position(
        order_status="filled",
        api_controllable=True,
        bot_opened=True,
        exit_evaluation_enabled=True,
        user_action_required=False,
        order_id="order-abc",
        client_order_id="cb-probe-BTCUSD-buy",
    )
    journal = _journal_with_evidence()
    broker_data = _broker_with_balance()

    result = diag._classify_position("BTC/USD", pos, journal, broker_data, [])

    assert result["advanced_trade_close_capability"] == "yes"
    assert result["user_action_required"] is False
    assert result["journal_evidence_found"] is True
    assert result["broker_balance_visible"] is True


# ---------------------------------------------------------------------------
# 4. Diagnostic never mutates state
# ---------------------------------------------------------------------------

def test_diagnostic_does_not_mutate_state(tmp_path):
    # Write a fake open_positions.json
    state_file = tmp_path / "open_positions.json"
    original_data = {
        "saved_at": "2026-05-26T23:31:43Z",
        "state_namespace": "coinbase",
        "positions": {
            "BTC/USD": _make_position()
        },
    }
    state_file.write_text(json.dumps(original_data))

    # Patch the state path
    with patch.object(diag, "OPEN_STATE_PATH", state_file), \
         patch.object(diag, "CLOSED_STATE_PATH", tmp_path / "closed.json"), \
         patch.object(diag, "JOURNAL_PATH", tmp_path / "journal.csv"), \
         patch.object(diag, "LOG_PATH", tmp_path / "coinbase.log"), \
         patch.object(diag, "HEARTBEAT_PATH", tmp_path / "hb.json"), \
         patch.object(diag, "KILL_SWITCH_PATH", tmp_path / "STOP"):

        # Create empty journal/log
        (tmp_path / "journal.csv").write_text("timestamp,mode,asset_class,symbol,strategy,action,decision,reason,confidence,price,bid,ask,spread_pct,notional,qty,order_type,order_id,client_order_id,intent_key,status,fill_price,exit_price,gross_pnl,fees_paid,pnl_usd,pnl_pct,equity,buying_power,open_positions,daily_trade_count,consecutive_losses,error\n")
        (tmp_path / "coinbase.log").write_text("")
        (tmp_path / "hb.json").write_text("{}")

        # Run diagnostic without broker
        report = diag.run_diagnostic(use_broker=False)

    # State file must be identical after diagnostic
    after_data = json.loads(state_file.read_text())
    assert after_data == original_data, "State file was mutated by diagnostic"


# ---------------------------------------------------------------------------
# 5. No order endpoint is called
# ---------------------------------------------------------------------------

def test_no_order_endpoint_called():
    """Verify that _try_broker_access only uses the allowed read-only methods."""
    forbidden_methods = {
        "place_limit_order",
        "place_market_order",
        "close_position",
        "cancel_order",
        "place_stop_order",
        "sell",
        "buy",
        "submit_order",
        "place_order",
        "market_order",
    }
    # The allowed set must not overlap with the forbidden set
    assert not (diag._ALLOWED_BROKER_METHODS & forbidden_methods), (
        "Forbidden method found in _ALLOWED_BROKER_METHODS: "
        + str(diag._ALLOWED_BROKER_METHODS & forbidden_methods)
    )


def test_no_forbidden_method_calls_in_try_broker_access():
    """Verify that _try_broker_access never calls forbidden methods."""
    import inspect
    src = inspect.getsource(diag._try_broker_access)

    forbidden = [
        "place_limit_order",
        "place_market_order",
        "close_position",
        "cancel_order",
        "place_stop_order",
        "submit_order",
        ".sell(",
        ".buy(",
        "market_order",
    ]
    for method in forbidden:
        assert method not in src, (
            f"Forbidden method reference '{method}' found in _try_broker_access"
        )


# ---------------------------------------------------------------------------
# 6. Diagnostic output includes recommended_action
# ---------------------------------------------------------------------------

def test_output_includes_recommended_action():
    pos = _make_position(
        order_status="broker_recovered",
        api_controllable=False,
        bot_opened=False,
        exit_evaluation_enabled=False,
        user_action_required=True,
        order_id="",
        client_order_id="",
    )
    journal = _journal_no_evidence()
    broker_data = _broker_unavailable()

    result = diag._classify_position("BTC/USD", pos, journal, broker_data, [])
    assert "recommended_action" in result
    assert isinstance(result["recommended_action"], str)
    assert len(result["recommended_action"]) > 0


def test_bot_placed_output_includes_recommended_action():
    pos = _make_position()
    journal = _journal_with_evidence()
    broker_data = _broker_with_balance()

    result = diag._classify_position("BTC/USD", pos, journal, broker_data, [])
    assert "recommended_action" in result
    assert len(result["recommended_action"]) > 0


# ---------------------------------------------------------------------------
# 7. JSON output emits valid JSON
# ---------------------------------------------------------------------------

def test_json_output_is_valid(tmp_path, capsys):
    state_file = tmp_path / "open_positions.json"
    state_file.write_text(json.dumps({
        "saved_at": "2026-05-26T23:31:43Z",
        "state_namespace": "coinbase",
        "positions": {
            "BTC/USD": _make_position()
        },
    }))
    (tmp_path / "journal.csv").write_text(
        "timestamp,mode,asset_class,symbol,strategy,action,decision,reason,"
        "confidence,price,bid,ask,spread_pct,notional,qty,order_type,order_id,"
        "client_order_id,intent_key,status,fill_price,exit_price,gross_pnl,"
        "fees_paid,pnl_usd,pnl_pct,equity,buying_power,open_positions,"
        "daily_trade_count,consecutive_losses,error\n"
    )
    (tmp_path / "coinbase.log").write_text("")
    (tmp_path / "hb.json").write_text("{}")

    with patch.object(diag, "OPEN_STATE_PATH", state_file), \
         patch.object(diag, "CLOSED_STATE_PATH", tmp_path / "closed.json"), \
         patch.object(diag, "JOURNAL_PATH", tmp_path / "journal.csv"), \
         patch.object(diag, "LOG_PATH", tmp_path / "coinbase.log"), \
         patch.object(diag, "HEARTBEAT_PATH", tmp_path / "hb.json"), \
         patch.object(diag, "KILL_SWITCH_PATH", tmp_path / "STOP"):

        report = diag.run_diagnostic(use_broker=False)

    # Serialize and parse back — must not raise
    serialized = json.dumps(report, indent=2, default=str)
    parsed = json.loads(serialized)
    assert isinstance(parsed, dict)
    assert "positions" in parsed
    assert "state" in parsed
    assert "runtime" in parsed


# ---------------------------------------------------------------------------
# 8. broker_recovered with partial bot evidence stays unknown, not yes
# ---------------------------------------------------------------------------

def test_broker_recovered_with_order_id_but_no_api_controllable_stays_unknown():
    """Even if an order_id exists, api_controllable=False prevents close_capability=yes."""
    pos = _make_position(
        order_status="broker_recovered",
        api_controllable=False,
        bot_opened=False,
        exit_evaluation_enabled=False,
        user_action_required=True,
        order_id="order-old-123",  # order_id present but api_controllable=False
        client_order_id="cb-old",
    )
    journal = _journal_with_evidence()
    broker_data = _broker_unavailable()

    result = diag._classify_position("BTC/USD", pos, journal, broker_data, [])

    assert result["advanced_trade_close_capability"] != "yes", (
        "api_controllable=False must prevent close_capability=yes "
        "even when order_id is present"
    )


# ---------------------------------------------------------------------------
# 9. run_diagnostic returns expected top-level keys
# ---------------------------------------------------------------------------

def test_run_diagnostic_structure(tmp_path):
    state_file = tmp_path / "open_positions.json"
    state_file.write_text(json.dumps({
        "saved_at": "2026-05-26T00:00:00Z",
        "state_namespace": "coinbase",
        "positions": {},
    }))
    (tmp_path / "journal.csv").write_text(
        "timestamp,mode,asset_class,symbol,strategy,action,decision,reason,"
        "confidence,price,bid,ask,spread_pct,notional,qty,order_type,order_id,"
        "client_order_id,intent_key,status,fill_price,exit_price,gross_pnl,"
        "fees_paid,pnl_usd,pnl_pct,equity,buying_power,open_positions,"
        "daily_trade_count,consecutive_losses,error\n"
    )

    with patch.object(diag, "OPEN_STATE_PATH", state_file), \
         patch.object(diag, "CLOSED_STATE_PATH", tmp_path / "closed.json"), \
         patch.object(diag, "JOURNAL_PATH", tmp_path / "journal.csv"), \
         patch.object(diag, "LOG_PATH", tmp_path / "coinbase.log"), \
         patch.object(diag, "HEARTBEAT_PATH", tmp_path / "hb.json"), \
         patch.object(diag, "KILL_SWITCH_PATH", tmp_path / "STOP"):

        report = diag.run_diagnostic(use_broker=False)

    assert "generated_at" in report
    assert "runtime" in report
    assert "state" in report
    assert "broker" in report
    assert "positions" in report
    assert "recent_closed_positions" in report
    assert isinstance(report["positions"], list)
