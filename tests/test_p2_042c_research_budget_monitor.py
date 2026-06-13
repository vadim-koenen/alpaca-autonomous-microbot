"""Tests for P2-042C live research budget monitor."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from live_research_budget import (
    ResearchBudgetPolicy,
    ResearchKillReason,
    evaluate_research_budget_state,
    should_allow_next_research_trade,
    summarize_research_budget_usage,
)
from live_research_journal import build_journal_event


@pytest.fixture
def base_event_values():
    return {
        "research_session_id": "session-1",
        "run_id": "run-1",
        "correlation_id": "cor-1",
        "symbol": "BTC/USD",
        "mode": "live_research_evidence",
        "source": "test",
        "created_by": "test",
    }


@pytest.fixture
def now():
    return datetime(2026, 6, 13, 20, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def base_policy():
    return ResearchBudgetPolicy(
        live_research_for_data=True,
        live_trading_for_profit=False,
        live_research_approval_present=True,
        approval_text="LIVE_RESEARCH_APPROVED for Coinbase high-volatility evidence collection with max loss budget $50",
        research_budget_usd=50.0,
        max_daily_research_loss_usd=20.0,
        max_weekly_research_loss_usd=40.0,
        max_single_trade_notional_usd=10.0,
        max_research_trades_per_day=5,
        allowed_research_symbols=("BTC/USD",),
        research_mode_expires_at="2026-06-14T20:00:00Z",
    )


@pytest.fixture
def valid_journal_events(now, base_event_values):
    ts = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    
    fill_values = {
        **base_event_values,
        "fee_amount": 0.01,
        "fee_currency": "USD",
        "fee_bps": 10.0,
        "fill_complete": True,
        "gross_notional_usd": 1.0,
        "reference_mid_price": 100.0,
        "reference_bid_price": 100.0,
        "reference_ask_price": 100.0,
        "slippage_abs": 0.0,
        "slippage_bps": 0.0,
        "effective_spread_bps": 0.0,
        "fill_id": "fill-1",
        "fill_timestamp_utc": ts,
        "fill_side": "buy",
        "fill_qty": 0.01,
        "avg_fill_price": 100.0,
        "liquidity_flag": "maker",
        "fill_source": "test",
        "replay_dataset_id": "ds-1",
        "replay_window_start_utc": ts,
        "replay_window_end_utc": ts,
        "replay_signal_match": True,
        "replay_expected_decision": "buy",
        "live_decision": "buy",
        "divergence_reason": "none",
    }
    
    mark_values = {
        **base_event_values,
        "entry_price": 100.0,
        "current_mark_price": 100.0,
        "best_price_since_entry": 100.0,
        "worst_price_since_entry": 100.0,
        "mfe_abs": 0.0,
        "mfe_bps": 0.0,
        "mae_abs": 0.0,
        "mae_bps": 0.0,
        "mfe_timestamp_utc": ts,
        "mae_timestamp_utc": ts,
    }

    return [
        build_journal_event("fill_observed", timestamp_utc=ts, values=fill_values),
        build_journal_event("position_mark_observed", timestamp_utc=ts, values=mark_values)
    ]


def test_defaults_fail_closed(base_policy, valid_journal_events, now):
    # Replace live_research_for_data with False
    policy = ResearchBudgetPolicy(**{**base_policy.__dict__, "live_research_for_data": False})
    decision = evaluate_research_budget_state(policy, valid_journal_events, "BTC/USD", 5.0, now)
    assert decision.decision == "FAIL_CLOSED"
    assert any(r.reason == "live_research_disabled" for r in decision.reasons)


def test_missing_approval_fails_closed(base_policy, valid_journal_events, now):
    policy = ResearchBudgetPolicy(**{**base_policy.__dict__, "live_research_approval_present": False})
    decision = evaluate_research_budget_state(policy, valid_journal_events, "BTC/USD", 5.0, now)
    assert decision.decision == "FAIL_CLOSED"
    assert any(r.reason == "missing_approval" for r in decision.reasons)


def test_invalid_approval_phrase_fails_closed(base_policy, valid_journal_events, now):
    policy = ResearchBudgetPolicy(**{**base_policy.__dict__, "approval_text": "I approve this"})
    decision = evaluate_research_budget_state(policy, valid_journal_events, "BTC/USD", 5.0, now)
    assert decision.decision == "FAIL_CLOSED"
    assert any(r.reason == "invalid_approval_phrase" for r in decision.reasons)


def test_missing_total_budget_fails_closed(base_policy, valid_journal_events, now):
    policy = ResearchBudgetPolicy(**{**base_policy.__dict__, "research_budget_usd": 0.0})
    decision = evaluate_research_budget_state(policy, valid_journal_events, "BTC/USD", 5.0, now)
    assert decision.decision == "FAIL_CLOSED"
    assert any(r.reason == "missing_budget" for r in decision.reasons)


def test_missing_daily_cap_fails_closed(base_policy, valid_journal_events, now):
    policy = ResearchBudgetPolicy(**{**base_policy.__dict__, "max_daily_research_loss_usd": 0.0})
    decision = evaluate_research_budget_state(policy, valid_journal_events, "BTC/USD", 5.0, now)
    assert decision.decision == "FAIL_CLOSED"
    assert any(r.reason == "missing_daily_cap" for r in decision.reasons)


def test_missing_weekly_cap_fails_closed(base_policy, valid_journal_events, now):
    policy = ResearchBudgetPolicy(**{**base_policy.__dict__, "max_weekly_research_loss_usd": 0.0})
    decision = evaluate_research_budget_state(policy, valid_journal_events, "BTC/USD", 5.0, now)
    assert decision.decision == "FAIL_CLOSED"
    assert any(r.reason == "missing_weekly_cap" for r in decision.reasons)


def test_missing_max_notional_fails_closed(base_policy, valid_journal_events, now):
    policy = ResearchBudgetPolicy(**{**base_policy.__dict__, "max_single_trade_notional_usd": 0.0})
    decision = evaluate_research_budget_state(policy, valid_journal_events, "BTC/USD", 5.0, now)
    assert decision.decision == "FAIL_CLOSED"
    assert any(r.reason == "missing_max_notional" for r in decision.reasons)


def test_missing_max_trades_per_day_fails_closed(base_policy, valid_journal_events, now):
    policy = ResearchBudgetPolicy(**{**base_policy.__dict__, "max_research_trades_per_day": 0})
    decision = evaluate_research_budget_state(policy, valid_journal_events, "BTC/USD", 5.0, now)
    assert decision.decision == "FAIL_CLOSED"
    assert any(r.reason == "missing_max_trades_per_day" for r in decision.reasons)


def test_missing_allowed_symbols_fails_closed(base_policy, valid_journal_events, now):
    policy = ResearchBudgetPolicy(**{**base_policy.__dict__, "allowed_research_symbols": ()})
    decision = evaluate_research_budget_state(policy, valid_journal_events, "BTC/USD", 5.0, now)
    assert decision.decision == "FAIL_CLOSED"
    assert any(r.reason == "missing_allowed_symbols" for r in decision.reasons)


def test_missing_expiry_fails_closed(base_policy, valid_journal_events, now):
    policy = ResearchBudgetPolicy(**{**base_policy.__dict__, "research_mode_expires_at": ""})
    decision = evaluate_research_budget_state(policy, valid_journal_events, "BTC/USD", 5.0, now)
    assert decision.decision == "FAIL_CLOSED"
    assert any(r.reason == "missing_expiry" for r in decision.reasons)


def test_expired_mode_fails_closed(base_policy, valid_journal_events, now):
    policy = ResearchBudgetPolicy(**{**base_policy.__dict__, "research_mode_expires_at": "2026-06-12T20:00:00Z"})
    decision = evaluate_research_budget_state(policy, valid_journal_events, "BTC/USD", 5.0, now)
    assert decision.decision == "FAIL_CLOSED"
    assert any(r.reason == "expired_approval" for r in decision.reasons)


def test_live_profit_trading_true_fails_closed(base_policy, valid_journal_events, now):
    policy = ResearchBudgetPolicy(**{**base_policy.__dict__, "live_trading_for_profit": True})
    decision = evaluate_research_budget_state(policy, valid_journal_events, "BTC/USD", 5.0, now)
    assert decision.decision == "FAIL_CLOSED"
    assert any(r.reason == "live_profit_trading_enabled" for r in decision.reasons)


def test_missing_journal_readiness_fails_closed(base_policy, now):
    decision = evaluate_research_budget_state(base_policy, [], "BTC/USD", 5.0, now)
    assert decision.decision == "FAIL_CLOSED"
    assert any(r.reason == "missing_journal_capture" for r in decision.reasons)


def test_missing_fill_capture_readiness_fails_closed(base_policy, valid_journal_events, now):
    events = [e for e in valid_journal_events if e["event_type"] != "fill_observed"]
    decision = evaluate_research_budget_state(base_policy, events, "BTC/USD", 5.0, now)
    assert decision.decision == "FAIL_CLOSED"
    assert any(r.reason == "missing_fill_capture" for r in decision.reasons)


def test_missing_fee_capture_readiness_fails_closed(base_policy, valid_journal_events, now):
    events = list(valid_journal_events)
    events[0] = {**events[0], "fee_amount": None}  # Break fee capture
    decision = evaluate_research_budget_state(base_policy, events, "BTC/USD", 5.0, now)
    assert decision.decision == "FAIL_CLOSED"
    assert any(r.reason == "missing_fee_capture" for r in decision.reasons)


def test_missing_mfe_mae_readiness_fails_closed(base_policy, valid_journal_events, now):
    events = [e for e in valid_journal_events if e["event_type"] != "position_mark_observed"]
    decision = evaluate_research_budget_state(base_policy, events, "BTC/USD", 5.0, now)
    assert decision.decision == "FAIL_CLOSED"
    assert any(r.reason == "missing_mfe_mae_capture" for r in decision.reasons)


def test_malformed_journal_event_fails_closed(base_policy, valid_journal_events, now, base_event_values):
    # Add a malformed event
    events = valid_journal_events + [{"malformed": True}]
    decision = evaluate_research_budget_state(base_policy, events, "BTC/USD", 5.0, now)
    assert decision.decision == "FAIL_CLOSED"
    assert any(r.reason.startswith("invalid_journal_event") for r in decision.reasons)


def test_requested_symbol_outside_allowed_list_fails_closed(base_policy, valid_journal_events, now):
    decision = evaluate_research_budget_state(base_policy, valid_journal_events, "ETH/USD", 5.0, now)
    assert decision.decision == "FAIL_CLOSED"
    assert any(r.reason == "symbol_not_allowed" for r in decision.reasons)


def test_requested_notional_above_max_single_trade_notional_fails_closed(base_policy, valid_journal_events, now):
    decision = evaluate_research_budget_state(base_policy, valid_journal_events, "BTC/USD", 15.0, now)
    assert decision.decision == "FAIL_CLOSED"
    assert any(r.reason == "notional_exceeds_max" for r in decision.reasons)


def test_total_budget_breach_returns_kill(base_policy, valid_journal_events, now, base_event_values):
    ts = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    
    exit_values = {
        **base_event_values,
        "exit_reason": "test",
        "exit_timestamp_utc": ts,
        "exit_price": 100.0,
        "realized_gross_pnl_usd": -55.0,
        "realized_fees_usd": 0.0,
        "realized_slippage_usd": 0.0,
        "realized_net_pnl_usd": -55.0,
        "hold_seconds": 10,
        "replay_dataset_id": "ds",
        "replay_window_start_utc": ts,
        "replay_window_end_utc": ts,
        "replay_signal_match": True,
        "replay_expected_decision": "buy",
        "live_decision": "buy",
        "divergence_reason": "none"
    }
    
    events = valid_journal_events + [build_journal_event("exit_observed", timestamp_utc=ts, values=exit_values)]
    decision = evaluate_research_budget_state(base_policy, events, "BTC/USD", 5.0, now)
    assert decision.decision == "KILL"
    assert any(r.reason == "total_budget_exceeded" for r in decision.reasons)
    assert decision.kill_event is not None
    assert decision.kill_event["kill_reason"] == "total_budget_exceeded"


def test_daily_loss_breach_returns_kill(base_policy, valid_journal_events, now, base_event_values):
    ts = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    exit_values = {
        **base_event_values,
        "exit_reason": "test",
        "exit_timestamp_utc": ts,
        "exit_price": 100.0,
        "realized_gross_pnl_usd": -25.0,
        "realized_fees_usd": 0.0,
        "realized_slippage_usd": 0.0,
        "realized_net_pnl_usd": -25.0,
        "hold_seconds": 10,
        "replay_dataset_id": "ds",
        "replay_window_start_utc": ts,
        "replay_window_end_utc": ts,
        "replay_signal_match": True,
        "replay_expected_decision": "buy",
        "live_decision": "buy",
        "divergence_reason": "none"
    }
    events = valid_journal_events + [build_journal_event("exit_observed", timestamp_utc=ts, values=exit_values)]
    decision = evaluate_research_budget_state(base_policy, events, "BTC/USD", 5.0, now)
    assert decision.decision == "KILL"
    assert any(r.reason == "daily_loss_exceeded" for r in decision.reasons)


def test_weekly_loss_breach_returns_kill(base_policy, valid_journal_events, now, base_event_values):
    # Event happened 3 days ago
    ts = (now - timedelta(days=3)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    exit_values = {
        **base_event_values,
        "exit_reason": "test",
        "exit_timestamp_utc": ts,
        "exit_price": 100.0,
        "realized_gross_pnl_usd": -45.0,
        "realized_fees_usd": 0.0,
        "realized_slippage_usd": 0.0,
        "realized_net_pnl_usd": -45.0,
        "hold_seconds": 10,
        "replay_dataset_id": "ds",
        "replay_window_start_utc": ts,
        "replay_window_end_utc": ts,
        "replay_signal_match": True,
        "replay_expected_decision": "buy",
        "live_decision": "buy",
        "divergence_reason": "none"
    }
    events = valid_journal_events + [build_journal_event("exit_observed", timestamp_utc=ts, values=exit_values)]
    decision = evaluate_research_budget_state(base_policy, events, "BTC/USD", 5.0, now)
    assert decision.decision == "KILL"
    assert any(r.reason == "weekly_loss_exceeded" for r in decision.reasons)


def test_max_trades_per_day_breach_returns_kill(base_policy, valid_journal_events, now, base_event_values):
    ts = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    fill_values = {
        **base_event_values,
        "fee_amount": 0.01,
        "fee_currency": "USD",
        "fee_bps": 10.0,
        "fill_complete": True,
        "gross_notional_usd": 1.0,
        "reference_mid_price": 100.0,
        "reference_bid_price": 100.0,
        "reference_ask_price": 100.0,
        "slippage_abs": 0.0,
        "slippage_bps": 0.0,
        "effective_spread_bps": 0.0,
        "fill_id": "fill-1",
        "fill_timestamp_utc": ts,
        "fill_side": "buy",
        "fill_qty": 0.01,
        "avg_fill_price": 100.0,
        "liquidity_flag": "maker",
        "fill_source": "test",
        "replay_dataset_id": "ds-1",
        "replay_window_start_utc": ts,
        "replay_window_end_utc": ts,
        "replay_signal_match": True,
        "replay_expected_decision": "buy",
        "live_decision": "buy",
        "divergence_reason": "none",
    }
    fills = [
        build_journal_event("fill_observed", timestamp_utc=ts, values=fill_values)
        for _ in range(6)
    ]
    events = valid_journal_events + fills
    decision = evaluate_research_budget_state(base_policy, events, "BTC/USD", 5.0, now)
    assert decision.decision == "KILL"
    assert any(r.reason == "max_trades_per_day_exceeded" for r in decision.reasons)


def test_prior_kill_switch_triggered_event_blocks_continuation(base_policy, valid_journal_events, now, base_event_values):
    ts = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    kill_values = {**base_event_values, "decision": "kill", "decision_reason": "test"}
    events = valid_journal_events + [build_journal_event("kill_switch_triggered", timestamp_utc=ts, values=kill_values)]
    decision = evaluate_research_budget_state(base_policy, events, "BTC/USD", 5.0, now)
    assert decision.decision == "KILL"
    assert any(r.reason == "prior_kill_event" for r in decision.reasons)


def test_valid_policy_and_evidence_within_budget_returns_allow(base_policy, valid_journal_events, now):
    decision = evaluate_research_budget_state(base_policy, valid_journal_events, "BTC/USD", 5.0, now)
    assert decision.decision == "ALLOW"
    assert decision.reasons == ()
    assert decision.kill_event is None


def test_budget_summary_computes_realized_loss_correctly(now):
    ts = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    events = [
        {"event_type": "exit_observed", "realized_net_pnl_usd": -10.0, "timestamp_utc": ts},
        {"event_type": "exit_observed", "realized_net_pnl_usd": -5.0, "timestamp_utc": ts},
        # Profits do not reduce budget used
        {"event_type": "exit_observed", "realized_net_pnl_usd": 20.0, "timestamp_utc": ts},
    ]
    state = summarize_research_budget_usage(events, now)
    assert state.total_budget_used_usd == 15.0


def test_fees_are_included_in_budget_summary(now):
    ts = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    events = [
        {"event_type": "exit_observed", "realized_net_pnl_usd": 10.0, "realized_fees_usd": 2.0, "timestamp_utc": ts},
    ]
    state = summarize_research_budget_usage(events, now)
    assert state.total_budget_used_usd == 2.0  # Even with profit, fees consume budget


def test_jsonl_journal_reading_uses_explicit_path_only_and_writes_test_to_tmp(tmp_path, now, base_event_values):
    policy_dict = {
        "LIVE_RESEARCH_FOR_DATA": True,
        "LIVE_TRADING_FOR_PROFIT": False,
        "LIVE_RESEARCH_APPROVAL_REQUIRED": True,
        "approval_text": "LIVE_RESEARCH_APPROVED for Coinbase high-volatility evidence collection with max loss budget $50",
        "LIVE_RESEARCH_BUDGET_USD": 50.0,
        "MAX_DAILY_RESEARCH_LOSS_USD": 20.0,
        "MAX_WEEKLY_RESEARCH_LOSS_USD": 40.0,
        "MAX_SINGLE_TRADE_NOTIONAL_USD": 10.0,
        "MAX_RESEARCH_TRADES_PER_DAY": 5,
        "ALLOWED_RESEARCH_SYMBOLS": ["BTC/USD"],
        "RESEARCH_MODE_EXPIRES_AT": "2026-06-14T20:00:00Z"
    }

    journal_path = tmp_path / "test_journal.jsonl"
    ts = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    
    fill_values = {
        **base_event_values,
        "fee_amount": 0.01,
        "fee_currency": "USD",
        "fee_bps": 10.0,
        "fill_complete": True,
        "gross_notional_usd": 1.0,
        "reference_mid_price": 100.0,
        "reference_bid_price": 100.0,
        "reference_ask_price": 100.0,
        "slippage_abs": 0.0,
        "slippage_bps": 0.0,
        "effective_spread_bps": 0.0,
        "fill_id": "fill-1",
        "fill_timestamp_utc": ts,
        "fill_side": "buy",
        "fill_qty": 0.01,
        "avg_fill_price": 100.0,
        "liquidity_flag": "maker",
        "fill_source": "test",
        "replay_dataset_id": "ds-1",
        "replay_window_start_utc": ts,
        "replay_window_end_utc": ts,
        "replay_signal_match": True,
        "replay_expected_decision": "buy",
        "live_decision": "buy",
        "divergence_reason": "none",
    }
    
    mark_values = {
        **base_event_values,
        "entry_price": 100.0,
        "current_mark_price": 100.0,
        "best_price_since_entry": 100.0,
        "worst_price_since_entry": 100.0,
        "mfe_abs": 0.0,
        "mfe_bps": 0.0,
        "mae_abs": 0.0,
        "mae_bps": 0.0,
        "mfe_timestamp_utc": ts,
        "mae_timestamp_utc": ts,
    }
    
    fill_evt = build_journal_event("fill_observed", timestamp_utc=ts, values=fill_values)
    mark_evt = build_journal_event("position_mark_observed", timestamp_utc=ts, values=mark_values)

    with journal_path.open("w") as f:
        f.write(json.dumps(fill_evt) + "\n")
        f.write(json.dumps(mark_evt) + "\n")

    decision = should_allow_next_research_trade(policy_dict, journal_path, "BTC/USD", 5.0, now)
    assert decision.decision == "ALLOW"


def test_no_live_research_enablement_or_runtime_kill_file_written():
    import live_research_budget
    source = open(live_research_budget.__file__).read()
    assert "STOP_TRADING" not in source
    assert "launchctl" not in source
    assert "broker_alpaca" not in source
    assert "broker_coinbase" not in source
    assert "place_order" not in source
    assert "open(" not in source or "journal_path" in source # It only opens the path passed in
