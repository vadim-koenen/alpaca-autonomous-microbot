"""
Tests for heartbeat activity timestamps.

These are observability-only checks: no broker API calls, no live mode, and
no order submission paths are exercised.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("ALPACA_API_KEY", "test_key_placeholder")
os.environ.setdefault("ALPACA_SECRET_KEY", "test_secret_placeholder")
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("ALPACA_PAPER", "true")

import main
from order_manager import SessionState
from permissions import AccountPermissions


def _write_test_heartbeat(tmp_path: Path, monkeypatch, session: SessionState) -> dict:
    monkeypatch.setattr(main, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(main, "kill_switch_active", lambda: False)
    permissions = AccountPermissions(equity=29.94, buying_power=29.44)

    main._write_heartbeat("coinbase", "paper", session, permissions)

    return json.loads((tmp_path / "coinbase_heartbeat.json").read_text())


def test_heartbeat_payload_includes_last_trade_at_after_trade_event(tmp_path, monkeypatch):
    session = SessionState()
    session.record_trade_event("2026-05-26T23:30:34+00:00")

    payload = _write_test_heartbeat(tmp_path, monkeypatch, session)

    assert payload["last_trade_at"] == "2026-05-26T23:30:34+00:00"
    assert payload["last_exit_at"] is None
    assert payload["trades_today"] == 0
    assert payload["open_positions"] == 0
    assert "last_loop_time" in payload
    assert "risk_halt_active" in payload


def test_heartbeat_payload_includes_last_exit_at_after_exit_event(tmp_path, monkeypatch):
    session = SessionState()
    session.record_exit_event("2026-05-26T23:42:10+00:00")

    payload = _write_test_heartbeat(tmp_path, monkeypatch, session)

    assert payload["last_trade_at"] is None
    assert payload["last_exit_at"] == "2026-05-26T23:42:10+00:00"


def test_heartbeat_missing_activity_values_default_to_none(tmp_path, monkeypatch):
    payload = _write_test_heartbeat(tmp_path, monkeypatch, SessionState())

    assert payload["last_trade_at"] is None
    assert payload["last_exit_at"] is None


def test_status_reads_activity_from_heartbeat_not_journals():
    status_script = (ROOT / "scripts" / "status.sh").read_text()

    assert "last_trade_at" in status_script
    assert "last_exit_at" in status_script
    assert "Last activity (from journals)" not in status_script
    assert "journal_alpaca_stocks.csv" not in status_script
    assert "journal_coinbase_crypto.csv" not in status_script


def test_status_script_syntax_is_valid():
    result = subprocess.run(
        ["bash", "-n", str(ROOT / "scripts" / "status.sh")],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_current_coinbase_config_uses_p2_023b_capped_pilot_caps():
    coinbase = yaml.safe_load((ROOT / "config_coinbase_crypto.yaml").read_text())
    alpaca = yaml.safe_load((ROOT / "config_alpaca_stocks.yaml").read_text())

    assert coinbase["global_risk"]["max_total_live_exposure_usd"] == 10.00
    assert coinbase["crypto"]["pilot_trade_percent_of_balance"] == 0.10
    assert coinbase["crypto"]["max_trade_notional_usd"] == 10.00
    assert coinbase["crypto"]["absolute_hard_trade_cap_usd"] == 10.00
    assert coinbase["crypto"]["max_total_crypto_exposure_usd"] == 10.00
    assert alpaca["global_risk"]["max_total_live_exposure_usd"] == 6.00
    assert alpaca["equities"]["max_trade_notional_usd"] == 2.00
    assert alpaca["equities"]["max_total_equity_exposure_usd"] == 4.00
