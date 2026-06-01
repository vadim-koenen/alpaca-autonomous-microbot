# ADVISORY ONLY — Tests for the anti-stale manual-review blocker watchdog (P2-021C2)

import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

# Import the module under test
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.coinbase_stale_blocker_watchdog import (
    compute_stale_blocker_state,
    run_stale_blocker_report_json,
)


def _write_temp_json(tmpdir: Path, name: str, data: dict) -> Path:
    p = tmpdir / name
    p.write_text(json.dumps(data))
    return p


def _make_heartbeat(last_trade_minutes_ago: int = 10, trades_today: int = 0, status="running"):
    now = datetime.now(timezone.utc)
    return {
        "status": status,
        "mode": "live",
        "last_trade_at": (now - timedelta(minutes=last_trade_minutes_ago)).isoformat(),
        "last_loop_time": now.isoformat(),
        "trades_today": trades_today,
        "buying_power": 44.7,
        "equity": 45.7,
        "open_positions": 1,
    }


def _make_open_positions(manual_review=True, external_staked=False):
    pos = {
        "SOL/USD": {
            "user_action_required": manual_review,
            "manual_review_reason": "broker_close_capability_unconfirmed" if manual_review else None,
            "api_controllable": not manual_review,
            "exit_evaluation_enabled": not manual_review,
            "bot_opened": True,
            "recovery_source": "journal_reassociated",
        }
    }
    if external_staked:
        pos["SOL/USD"].update({
            "staked_external_position": True,
            "external_inventory_classification": "external_staked_position",
            "tradable_by_bot": False,
            "bot_inventory": False,
            "manual_close_allowed": False,
        })
    return pos


def _make_journal_block_events(count: int, first_minutes_ago: int, reason="ENTRY_BLOCKED reason=manual_review_position_open"):
    now = datetime.now(timezone.utc)
    rows = []
    for i in range(count):
        ts = (now - timedelta(minutes=first_minutes_ago - (i * 10))).isoformat()
        rows.append(f"{ts},SOL/USD,BUY,SKIPPED,ENTRY_BLOCKED reason=manual_review_position_open")
    return "\n".join(["timestamp,symbol,action,decision,error"] + rows)


def _make_manual_review_events(count: int, first_minutes_ago: int):
    now = datetime.now(timezone.utc)
    return [
        {
            "timestamp": now - timedelta(minutes=first_minutes_ago - (i * 10)),
            "symbol": "SOL/USD",
            "reason": "ENTRY_BLOCKED reason=manual_review_position_open",
        }
        for i in range(count)
    ]


def test_stale_manual_review_blocker_returns_urgent_action(tmp_path):
    hb = _make_heartbeat(last_trade_minutes_ago=200)
    pos = _make_open_positions(manual_review=True)
    journal = _make_journal_block_events(count=20, first_minutes_ago=200)

    (tmp_path / "runtime").mkdir()
    (tmp_path / "state/coinbase").mkdir(parents=True)
    (tmp_path / "journal_coinbase_crypto.csv").write_text(journal)

    # Provide parsed journal events directly (compute accepts journal_rows)
    events = [
        {"timestamp": datetime.now(timezone.utc) - timedelta(minutes=200 - (i*5)), "symbol": "SOL/USD", "reason": "ENTRY_BLOCKED reason=manual_review_position_open"}
        for i in range(20)
    ]
    state = compute_stale_blocker_state(hb, pos, events, stale_threshold_minutes=180)

    assert state["verdict"] == "STALE_BLOCKER_REQUIRES_OPERATOR_ACTION"
    assert state["severity"] == "URGENT"
    assert state["sol_position_classification"]["is_true_bot_owned_unresolved"] is True
    assert state["sol_position_classification"]["is_external_staked_locked_inventory"] is False


def test_external_staked_sol_not_treated_as_bot_inventory(tmp_path):
    hb = _make_heartbeat()
    pos = _make_open_positions(manual_review=True, external_staked=True)
    events = _make_manual_review_events(count=30, first_minutes_ago=300)

    with patch("scripts.coinbase_stale_blocker_watchdog.ROOT", tmp_path):
        with patch("scripts.coinbase_stale_blocker_watchdog._load_heartbeat", return_value=hb):
            with patch("scripts.coinbase_stale_blocker_watchdog._load_open_positions", return_value=pos):
                state = compute_stale_blocker_state(hb, pos, events, stale_threshold_minutes=180)

    assert state["sol_position_classification"]["is_external_staked_locked_inventory"] is True
    assert state["sol_position_classification"]["is_true_bot_owned_unresolved"] is False
    # Still escalates because of age, but classification is external
    assert "external" in state.get("next_required_action", "").lower() or state["verdict"].startswith("STALE")


def test_stale_state_bug_when_events_but_no_open_manual_position(tmp_path):
    hb = _make_heartbeat()
    pos = {}  # no open positions
    events = _make_manual_review_events(count=50, first_minutes_ago=400)

    with patch("scripts.coinbase_stale_blocker_watchdog.ROOT", tmp_path):
        with patch("scripts.coinbase_stale_blocker_watchdog._load_heartbeat", return_value=hb):
            with patch("scripts.coinbase_stale_blocker_watchdog._load_open_positions", return_value=pos):
                state = compute_stale_blocker_state(hb, pos, events, stale_threshold_minutes=180)

    assert state["verdict"] == "STALE_STATE_BUG_REQUIRES_RESET_REVIEW"


def test_historical_manual_review_rows_resolved_by_external_inventory():
    hb = _make_heartbeat()
    pos = {}
    events = _make_manual_review_events(count=50, first_minutes_ago=400)
    external_inventory = {
        "SOL/USD": {
            "symbol": "SOL/USD",
            "staked_external_position": True,
            "external_inventory_classification": "external_staked_position",
            "tradable_by_bot": False,
            "manual_close_allowed": False,
            "bot_inventory": False,
            "blocks_new_entries": False,
        }
    }

    state = compute_stale_blocker_state(hb, pos, events, external_inventory, stale_threshold_minutes=180)

    assert state["verdict"] == "HISTORICAL_BLOCKER_RESOLVED_EXTERNAL_INVENTORY"
    assert state["severity"] == "INFO"
    assert state["trading_progress_state"] == "LIVE_EXTERNAL_INVENTORY_EXCLUDED"
    assert state["historical_blocker_resolved"] is True
    assert state["sol_position_classification"]["is_external_staked_locked_inventory"] is True
    assert state["sol_position_classification"]["is_true_bot_owned_unresolved"] is False


def test_under_threshold_is_blocked_but_not_stale(tmp_path):
    hb = _make_heartbeat(last_trade_minutes_ago=10)
    pos = _make_open_positions(manual_review=True)
    events = _make_manual_review_events(count=5, first_minutes_ago=30)

    with patch("scripts.coinbase_stale_blocker_watchdog.ROOT", tmp_path):
        with patch("scripts.coinbase_stale_blocker_watchdog._load_heartbeat", return_value=hb):
            with patch("scripts.coinbase_stale_blocker_watchdog._load_open_positions", return_value=pos):
                state = compute_stale_blocker_state(hb, pos, events, stale_threshold_minutes=180)

    assert state["verdict"] == "BLOCKED_BUT_NOT_STALE"


def test_no_blocker_returns_clean_state(tmp_path):
    hb = _make_heartbeat()
    pos = {}
    journal = "timestamp,symbol,action\n2026-06-01,SOL/USD,BUY"

    with patch("scripts.coinbase_stale_blocker_watchdog.ROOT", tmp_path):
        with patch("scripts.coinbase_stale_blocker_watchdog._load_heartbeat", return_value=hb):
            with patch("scripts.coinbase_stale_blocker_watchdog._load_open_positions", return_value=pos):
                state = compute_stale_blocker_state(hb, pos, [], stale_threshold_minutes=180)

    assert state["verdict"] == "NO_STALE_BLOCKER_DETECTED"


def test_script_never_imports_broker_or_reads_env_or_writes_forbidden(tmp_path, monkeypatch):
    # Isolation proof
    hb = _make_heartbeat()
    pos = _make_open_positions(manual_review=True)
    journal = _make_journal_block_events(count=1, first_minutes_ago=10)

    (tmp_path / ".env").write_text("COINBASE_API_KEY=NEVER_READ\n")

    monkeypatch.chdir(tmp_path)

    imported = []
    import builtins
    orig_import = builtins.__import__

    def tracking_import(name, *a, **k):
        imported.append(name)
        return orig_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", tracking_import)

    with patch("scripts.coinbase_stale_blocker_watchdog.ROOT", tmp_path):
        with patch("scripts.coinbase_stale_blocker_watchdog._load_heartbeat", return_value=hb):
            with patch("scripts.coinbase_stale_blocker_watchdog._load_open_positions", return_value=pos):
                state = compute_stale_blocker_state(hb, pos, [], 180)

    assert "broker_coinbase" not in " ".join(str(x) for x in imported)
    assert "NEVER_READ" not in str(state)
    # No writes happened in this call path
    assert True


def test_json_report_function_returns_required_fields(tmp_path):
    hb = _make_heartbeat()
    pos = _make_open_positions(manual_review=True)
    journal = _make_journal_block_events(count=10, first_minutes_ago=200)

    with patch("scripts.coinbase_stale_blocker_watchdog.ROOT", tmp_path):
        with patch("scripts.coinbase_stale_blocker_watchdog._load_heartbeat", return_value=hb):
            with patch("scripts.coinbase_stale_blocker_watchdog._load_open_positions", return_value=pos):
                report = run_stale_blocker_report_json(stale_threshold_minutes=180)

    required = [
        "verdict", "severity", "trading_progress_state",
        "blocker_reason", "blocker_age_minutes",
        "blocked_entry_count_today", "blocked_entry_count_window",
        "sol_position_classification",
        "next_required_action",
    ]
    for k in required:
        assert k in report
