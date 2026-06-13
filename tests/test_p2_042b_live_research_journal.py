"""P2-042B tests for the isolated live-research evidence journal."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import live_research_journal as journal
import live_research_policy


ROOT = Path(__file__).resolve().parents[1]
TS = "2026-06-13T20:00:00Z"


def _base_values() -> dict:
    return {
        "research_session_id": "research-session-001",
        "run_id": "run-001",
        "correlation_id": "correlation-001",
        "symbol": "BTC/USD",
        "mode": "live_research_evidence",
        "live_research_for_data": True,
        "live_trading_for_profit": False,
        "strategy_id": "strategy-current",
        "signal_id": "signal-001",
        "decision_id": "decision-001",
        "source": "unit-test-fixture",
        "created_by": "p2-042b-test",
        "live_research_policy_version": "p2_042a_v1",
        "live_research_approval_present": True,
        "live_research_budget_usd": 5.0,
        "max_daily_research_loss_usd": 2.0,
        "max_weekly_research_loss_usd": 4.0,
        "max_single_trade_notional_usd": 1.0,
        "max_research_trades_per_day": 3,
        "research_mode_expires_at": "2026-06-14T20:00:00Z",
    }


def _replay_values() -> dict:
    return {
        "replay_dataset_id": "btc-usd-replay-001",
        "replay_window_start_utc": "2026-06-12T20:00:00Z",
        "replay_window_end_utc": "2026-06-13T20:00:00Z",
        "replay_signal_match": True,
        "replay_expected_decision": "buy",
        "live_decision": "buy",
        "divergence_reason": "none",
    }


def _event(event_type: str, **values):
    payload = _base_values()
    payload.update(values)
    return journal.build_journal_event(
        event_type,
        event_id=f"event-{event_type}",
        timestamp_utc=TS,
        values=payload,
    )


def _proposal_event():
    return _event(
        "proposal_evaluated",
        proposal_side="buy",
        proposal_notional_usd=1.0,
        proposal_qty=0.00001,
        signal_reason="high-volatility research candidate",
        signal_score=0.81,
        decision="allow_research_intent",
        decision_reason="policy checks passed for evidence proposal",
        expected_move_bps=80.0,
        expected_fee_bps=12.0,
        expected_spread_bps=5.0,
        expected_slippage_bps=3.0,
        quote_timestamp_utc=TS,
        bid_price=99.95,
        ask_price=100.05,
        mid_price=100.0,
        spread_abs=0.10,
        spread_bps=10.0,
        quote_age_ms=125,
        **_replay_values(),
    )


def _fill_event():
    return _event(
        "fill_observed",
        broker_order_id="broker-order-001",
        fill_id="fill-001",
        fill_timestamp_utc=TS,
        fill_side="buy",
        fill_qty=0.01,
        avg_fill_price=100.02,
        gross_notional_usd=1.0002,
        fee_amount=0.006,
        fee_currency="USD",
        fee_bps=6.0,
        liquidity_flag="maker",
        fill_source="sanitized-broker-observation",
        fill_complete=True,
        reference_mid_price=100.0,
        reference_bid_price=99.95,
        reference_ask_price=100.05,
        slippage_abs=0.02,
        slippage_bps=2.0,
        effective_spread_bps=7.0,
        **_replay_values(),
    )


def _mark_event():
    return _event(
        "position_mark_observed",
        entry_price=100.0,
        current_mark_price=101.0,
        best_price_since_entry=102.0,
        worst_price_since_entry=99.0,
        mfe_abs=2.0,
        mfe_bps=200.0,
        mae_abs=1.0,
        mae_bps=100.0,
        mfe_timestamp_utc=TS,
        mae_timestamp_utc=TS,
    )


def test_valid_minimal_research_session_started_event_passes():
    event = _event("research_session_started")

    assert journal.validate_journal_event(event) == []
    assert tuple(event) == journal.JOURNAL_FIELDS


def test_valid_proposal_evaluated_event_passes_with_quote_and_spread_context():
    event = _proposal_event()

    assert journal.validate_journal_event(event) == []
    assert event["spread_bps"] == 10.0
    assert event["replay_dataset_id"] == "btc-usd-replay-001"


def test_valid_skip_observed_event_passes_with_skip_reason():
    event = _event(
        "skip_observed",
        decision="skip",
        decision_reason="spread exceeds research threshold",
        skip_reason="spread_too_wide",
        **_replay_values(),
    )

    assert journal.validate_journal_event(event) == []


def test_valid_fill_observed_event_requires_complete_fill_evidence():
    event = _fill_event()

    assert journal.validate_journal_event(event) == []


@pytest.mark.parametrize(
    ("field", "reason"),
    (
        ("fee_amount", "missing_event_field:fee_amount"),
        ("fee_currency", "missing_event_field:fee_currency"),
        ("avg_fill_price", "missing_event_field:avg_fill_price"),
        ("fill_qty", "missing_event_field:fill_qty"),
    ),
)
def test_fill_observed_fails_when_required_fill_or_fee_field_is_missing(field, reason):
    event = _fill_event()
    event[field] = None

    assert reason in journal.validate_journal_event(event)


def test_position_mark_observed_requires_all_mfe_mae_fields():
    event = _mark_event()
    assert journal.validate_journal_event(event) == []

    event["mae_bps"] = None
    assert "missing_event_field:mae_bps" in journal.validate_journal_event(event)


def test_exit_observed_requires_realized_net_pnl_fields():
    event = _event(
        "exit_observed",
        exit_reason="research_time_exit",
        exit_timestamp_utc=TS,
        exit_price=101.0,
        realized_gross_pnl_usd=0.01,
        realized_fees_usd=0.006,
        realized_slippage_usd=0.001,
        realized_net_pnl_usd=0.003,
        hold_seconds=600,
        **_replay_values(),
    )
    assert journal.validate_journal_event(event) == []

    event["realized_net_pnl_usd"] = None
    assert (
        "missing_event_field:realized_net_pnl_usd"
        in journal.validate_journal_event(event)
    )


def test_journal_append_writes_one_deterministic_json_object_per_line(tmp_path):
    path = tmp_path / "research" / "evidence.jsonl"
    first = _event("research_session_started")
    second = _proposal_event()

    journal.append_journal_event(first, path)
    journal.append_journal_event(second, path)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["event_type"] == "research_session_started"
    assert json.loads(lines[1])["event_type"] == "proposal_evaluated"
    assert lines[0] == json.dumps(
        first,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def test_journal_append_refuses_invalid_event_without_creating_file(tmp_path):
    path = tmp_path / "invalid.jsonl"
    event = _fill_event()
    event["fee_amount"] = None

    with pytest.raises(ValueError, match="missing_event_field:fee_amount"):
        journal.append_journal_event(event, path)

    assert not path.exists()


def test_journal_append_requires_explicit_jsonl_path(tmp_path):
    event = _event("research_session_started")
    with pytest.raises(ValueError, match="explicit JSONL path"):
        journal.append_journal_event(event, None)
    with pytest.raises(ValueError, match="must end with .jsonl"):
        journal.append_journal_event(event, tmp_path / "journal.txt")


def test_spread_bps_helper_computes_correctly():
    assert journal.compute_spread_bps(99.0, 101.0) == pytest.approx(200.0)
    assert journal.compute_spread_bps(99.0, 101.0, 100.0) == pytest.approx(200.0)


def test_slippage_bps_helper_computes_buy_and_sell_correctly():
    assert journal.compute_slippage_bps("buy", 100.0, 100.1) == pytest.approx(10.0)
    assert journal.compute_slippage_bps("sell", 100.0, 99.9) == pytest.approx(10.0)
    assert journal.compute_slippage_bps("buy", 100.0, 99.9) == pytest.approx(-10.0)


def test_mfe_mae_helper_computes_long_correctly():
    result = journal.update_mfe_mae(
        side="long",
        entry_price=100.0,
        current_mark_price=98.0,
        best_price_since_entry=103.0,
        worst_price_since_entry=99.0,
        mark_timestamp_utc=TS,
        mfe_timestamp_utc="2026-06-13T19:55:00Z",
    )

    assert result["best_price_since_entry"] == 103.0
    assert result["worst_price_since_entry"] == 98.0
    assert result["mfe_bps"] == pytest.approx(300.0)
    assert result["mae_bps"] == pytest.approx(200.0)
    assert result["mae_timestamp_utc"] == TS


def test_mfe_mae_helper_computes_short_correctly():
    result = journal.update_mfe_mae(
        side="short",
        entry_price=100.0,
        current_mark_price=102.0,
        best_price_since_entry=97.0,
        worst_price_since_entry=101.0,
        mark_timestamp_utc=TS,
        mfe_timestamp_utc="2026-06-13T19:55:00Z",
    )

    assert result["best_price_since_entry"] == 97.0
    assert result["worst_price_since_entry"] == 102.0
    assert result["mfe_bps"] == pytest.approx(300.0)
    assert result["mae_bps"] == pytest.approx(200.0)
    assert result["mae_timestamp_utc"] == TS


def test_secret_like_keys_and_values_are_rejected():
    event = _event("research_session_started")
    event["api_key"] = "NEVER-LOG-THIS"
    reasons = journal.validate_journal_event(event)
    assert "secret_field_forbidden:api_key" in reasons
    assert "unexpected_schema_field:api_key" in reasons

    event = _event("research_session_started")
    event["decision_reason"] = "authorization=Bearer-NEVER-LOG"
    assert any(
        reason.startswith("sensitive_value_forbidden")
        for reason in journal.validate_journal_event(event)
    )


def test_account_identifier_fields_are_rejected():
    event = _event("research_session_started")
    event["account_id"] = "account-should-not-be-logged"

    reasons = journal.validate_journal_event(event)

    assert "account_identifier_field_forbidden:account_id" in reasons
    assert "unexpected_schema_field:account_id" in reasons


@pytest.mark.parametrize(
    ("events", "reason"),
    (
        ([_mark_event()], "missing_fill_capture"),
        ([_mark_event()], "missing_fee_capture"),
        ([_fill_event()], "missing_mfe_mae_capture"),
    ),
)
def test_readiness_fails_closed_when_required_capture_is_missing(events, reason):
    reasons = journal.live_research_journal_fail_closed_reasons(events)
    assert reason in reasons
    assert journal.live_research_journal_capture_ready(events) is False


def test_readiness_fails_closed_when_fee_capture_is_incomplete():
    event = _fill_event()
    event["fee_currency"] = None

    reasons = journal.live_research_journal_fail_closed_reasons([event, _mark_event()])

    assert "missing_fee_capture" in reasons
    assert "invalid_journal_event:0" in reasons


def test_readiness_passes_only_with_valid_fill_fee_and_mfe_mae_capture():
    events = [_fill_event(), _mark_event()]

    report = journal.live_research_journal_readiness(events)

    assert report["ready"] is True
    assert report["fail_closed_reasons"] == []
    assert report["fill_capture_present"] is True
    assert report["fee_capture_present"] is True
    assert report["mfe_mae_capture_present"] is True


def test_no_live_enablement_or_strategy_risk_sizing_capital_integration_occurs():
    source = (ROOT / "live_research_journal.py").read_text(encoding="utf-8")
    forbidden = (
        "import broker_coinbase",
        "from broker_coinbase",
        "import broker_alpaca",
        "from broker_alpaca",
        "import order_manager",
        "import risk_manager",
        "import strategy_crypto",
        "place_order(",
        "submit_order(",
        "cancel_order(",
        "close_position(",
        "load_dotenv",
        "os.environ",
        "STOP_TRADING",
        "launchctl",
    )
    for token in forbidden:
        assert token not in source

    assert live_research_policy.DEFAULT_LIVE_RESEARCH_POLICY[
        "LIVE_RESEARCH_FOR_DATA"
    ] is False
    assert live_research_policy.DEFAULT_LIVE_RESEARCH_POLICY[
        "LIVE_TRADING_FOR_PROFIT"
    ] is False
    readiness = journal.live_research_journal_readiness([_fill_event(), _mark_event()])
    assert readiness["live_research_enabled"] is False
    assert readiness["live_trading_for_profit_enabled"] is False
    assert readiness["ml_live_influence_enabled"] is False
    assert readiness["online_learning_started"] is False
    assert readiness["actual_order_placement_integrated"] is False
