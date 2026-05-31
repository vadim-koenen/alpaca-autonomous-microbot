"""
P2-011H — Focused tests for the opt-in dry-run capture seam in PositionManager.

These tests prove:
- Default constructor behavior is unchanged (dry_run_capture disabled).
- The seam only activates when explicitly enabled.
- No logger writes or append calls occur.
- In-memory capture results are collected only in opt-in mode.
- Blocking conditions are respected (missing proceeds, IDs, fees).
- No impact on live trading logic.
"""

from unittest.mock import MagicMock, patch

import pytest

from position_manager import PositionManager


def make_mock_broker():
    broker = MagicMock()
    broker.get_historical_fills.return_value = []
    broker.get_order_status.return_value = {}
    return broker


def make_mock_journal():
    return MagicMock()


def test_default_constructor_disables_dry_run_capture():
    broker = make_mock_broker()
    journal = make_mock_journal()

    # 2-arg constructor (existing usage)
    pm = PositionManager(broker, journal)
    assert not getattr(pm, "_dry_run_capture", True)
    assert getattr(pm, "_dry_run_captures", None) == []

    # Explicit False
    pm2 = PositionManager(broker, journal, dry_run_capture=False)
    assert not pm2._dry_run_capture


def test_seam_does_not_run_when_disabled():
    broker = make_mock_broker()
    journal = make_mock_journal()
    pm = PositionManager(broker, journal, dry_run_capture=False)

    # Simulate what the entry seam would do
    pm._maybe_dry_run_capture_entry("BTC/USD", "order-123", {"status": "filled"})

    # Simulate exit seam
    pm._maybe_dry_run_capture_exit("BTC/USD", "order-456")

    # No calls to broker historical fills
    broker.get_historical_fills.assert_not_called()
    assert len(pm._dry_run_captures) == 0


def test_seam_runs_only_when_opt_in_and_stores_in_memory_results():
    broker = make_mock_broker()
    journal = make_mock_journal()

    # Return realistic minimal data
    broker.get_historical_fills.return_value = [
        {"trade_id": "t1", "price": "65000", "size": "0.001", "fee": "0.39", "liquidity_indicator": "MAKER"}
    ]
    broker.get_order_status.return_value = {"filled_size": "0.001", "average_filled_price": "65000"}

    pm = PositionManager(broker, journal, dry_run_capture=True)

    # Trigger entry seam
    status_info = {"normalized_status": "filled", "filled_size": "0.001", "average_filled_price": "65000", "total_fees": "0.39"}
    pm._maybe_dry_run_capture_entry("BTC/USD", "order-entry-1", status_info)

    assert len(pm._dry_run_captures) == 1
    cap = pm._dry_run_captures[0]
    assert cap.leg_type == "entry"
    assert cap.symbol == "BTC/USD"
    broker.get_historical_fills.assert_called()

    # Trigger exit seam
    pm._maybe_dry_run_capture_exit("BTC/USD", "order-exit-1")
    assert len(pm._dry_run_captures) == 2

    # Still no real writes
    assert broker.get_historical_fills.call_count >= 2


def test_dry_run_seam_respects_blocking_conditions():
    broker = make_mock_broker()
    journal = make_mock_journal()

    # Missing stable ID and fee on fill
    broker.get_historical_fills.return_value = [
        {"price": "65000", "size": "0.001"}  # no trade_id/entry_id, no fee
    ]

    pm = PositionManager(broker, journal, dry_run_capture=True)

    status_info = {"normalized_status": "filled", "filled_size": "0.001", "average_filled_price": "65000"}
    pm._maybe_dry_run_capture_entry("BTC/USD", "order-1", status_info)

    assert len(pm._dry_run_captures) == 1
    cap = pm._dry_run_captures[0]
    assert cap.logger_ready is False
    assert any("Missing stable fill ID" in r or "Missing per-fill fee" in r for r in cap.blocking_reasons)


def test_no_append_coinbase_fill_row_called_during_dry_run_seam():
    broker = make_mock_broker()
    journal = make_mock_journal()
    pm = PositionManager(broker, journal, dry_run_capture=True)

    with patch("coinbase_fill_logger.append_coinbase_fill_row") as mock_append:
        pm._maybe_dry_run_capture_entry("BTC/USD", "o1", {"filled_size": "0.001"})
        pm._maybe_dry_run_capture_exit("BTC/USD", "o2")

        mock_append.assert_not_called()


def test_dry_run_captures_are_in_memory_only_no_file_writes(tmp_path, monkeypatch):
    broker = make_mock_broker()
    journal = make_mock_journal()
    pm = PositionManager(broker, journal, dry_run_capture=True)

    # Force the csv path to a temp location to detect any accidental write
    monkeypatch.setattr("coinbase_fill_logger.DEFAULT_COINBASE_FILLS_CSV", tmp_path / "should_not_exist.csv")

    pm._maybe_dry_run_capture_entry("BTC/USD", "o1", {})
    pm._maybe_dry_run_capture_exit("BTC/USD", "o2")

    # The file should not have been created by the seam
    assert not (tmp_path / "should_not_exist.csv").exists()
    assert len(pm._dry_run_captures) == 2  # in-memory only


def test_seam_does_not_affect_live_state_or_decisions():
    """Smoke test that enabling the flag does not change other PositionManager behavior in obvious ways."""
    broker = make_mock_broker()
    journal = make_mock_journal()

    pm_normal = PositionManager(broker, journal)
    pm_dry = PositionManager(broker, journal, dry_run_capture=True)

    # Basic attributes should behave the same
    assert pm_normal._mode == pm_dry._mode
    assert pm_normal._broker is pm_dry._broker
    assert pm_normal._journal is pm_dry._journal

    # The only difference is the capture flag and list
    assert not pm_normal._dry_run_capture
    assert pm_dry._dry_run_capture
