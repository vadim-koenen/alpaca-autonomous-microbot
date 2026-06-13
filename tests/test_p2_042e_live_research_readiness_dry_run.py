"""Tests for P2-042E live research readiness dry-run wiring."""

from typing import Any, Mapping

import pytest

from live_research_budget import ResearchBudgetPolicy
from live_research_exploration_queue import (
    ExplorationCandidate,
    ExplorationProfile,
    ExplorationQueue,
    build_exploration_candidate,
)
from live_research_readiness_dry_run import (
    LiveResearchReadinessInput,
    LiveResearchReadinessStatus,
    build_live_research_readiness_input,
    run_live_research_readiness_dry_run,
)


@pytest.fixture
def default_budget_config():
    return ResearchBudgetPolicy(
        live_research_for_data=True,
        live_trading_for_profit=False,
        live_research_approval_present=True,
        approval_text="LIVE_RESEARCH_APPROVED for Coinbase high-volatility evidence collection with max loss budget $50.0",
        research_budget_usd=50.0,
        max_daily_research_loss_usd=10.0,
        max_weekly_research_loss_usd=25.0,
        max_single_trade_notional_usd=10.0,
        max_research_trades_per_day=5,
        allowed_research_symbols=("BTC/USD",),
        research_mode_expires_at="2026-06-30T00:00:00Z",
    )


from live_research_journal import build_journal_event

@pytest.fixture
def valid_journal_events():
    ts = "2026-06-13T20:00:00Z"
    base_event_values = {
        "research_session_id": "session-1",
        "run_id": "run-1",
        "correlation_id": "cor-1",
        "symbol": "BTC/USD",
        "mode": "live_research_evidence",
        "source": "test",
        "created_by": "test",
    }

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

    return (
        build_journal_event("fill_observed", timestamp_utc=ts, values=fill_values),
        build_journal_event("position_mark_observed", timestamp_utc=ts, values=mark_values)
    )


@pytest.fixture
def valid_candidate():
    return build_exploration_candidate(
        symbol="BTC/USD",
        profile=ExplorationProfile.VOLATILITY_BREAKOUT,
        proposed_side="buy",
        proposed_notional_usd=5.0,
        gross_expected_edge_bps=100.0,
        expected_fee_bps=10.0,
        spread_bps=20.0,
        expected_slippage_bps=5.0,
        proposal_only_dry_run=True,
        signal_reason="test signal",
        quote_timestamp_utc="2026-06-13T20:00:00Z",
        bid_price=100.0,
        ask_price=100.2,
        mid_price=100.1,
        quote_age_ms=50,
    )


def test_live_trading_for_profit_true_fails_closed(default_budget_config, valid_journal_events, valid_candidate):
    input_data = build_live_research_readiness_input(
        live_trading_for_profit=True,
        live_research_enabled=False,
        journal_path="/tmp/fake.jsonl",
        requires_journal_validation=True,
        budget_config=default_budget_config,
        journal_events_for_budget=valid_journal_events,
        exploration_queue=ExplorationQueue(candidates=(valid_candidate,)),
        allowed_symbols=("BTC/USD",),
        max_spread_bps=100.0,
        max_notional_usd=10.0,
    )

    report = run_live_research_readiness_dry_run(input_data)
    assert report.decision.status == LiveResearchReadinessStatus.BLOCKED_LIVE_TRADING_FOR_PROFIT
    assert any("live_trading_for_profit is True" in r.context for r in report.decision.reject_reasons)
    
    assert report.executable is False
    assert report.order_submission_enabled is False
    assert report.broker_api_required is False
    assert report.runtime_mutation_required is False
    assert report.live_research_enabled is False


def test_missing_evidence_capture_fails_closed(default_budget_config, valid_journal_events, valid_candidate):
    input_data = build_live_research_readiness_input(
        live_trading_for_profit=False,
        live_research_enabled=False,
        journal_path="",
        requires_journal_validation=True,
        budget_config=default_budget_config,
        journal_events_for_budget=valid_journal_events,
        exploration_queue=ExplorationQueue(candidates=(valid_candidate,)),
        allowed_symbols=("BTC/USD",),
        max_spread_bps=100.0,
        max_notional_usd=10.0,
    )

    report = run_live_research_readiness_dry_run(input_data)
    assert report.decision.status == LiveResearchReadinessStatus.BLOCKED_EVIDENCE_CAPTURE


def test_budget_monitor_block_fails_closed(default_budget_config, valid_journal_events, valid_candidate):
    # Pass empty allowed_symbols to budget config to force an immediate budget block when evaluated
    # because it will see any trade as invalid, or we can just expire it
    expired_config = ResearchBudgetPolicy(
        live_research_for_data=True,
        live_trading_for_profit=False,
        live_research_approval_present=True,
        approval_text="LIVE_RESEARCH_APPROVED for Coinbase high-volatility evidence collection with max loss budget $50.0",
        research_budget_usd=50.0,
        max_daily_research_loss_usd=10.0,
        max_weekly_research_loss_usd=25.0,
        max_single_trade_notional_usd=10.0,
        max_research_trades_per_day=5,
        allowed_research_symbols=("BTC/USD",),
        research_mode_expires_at="2020-01-01T00:00:00Z", # Expired
    )

    input_data = build_live_research_readiness_input(
        live_trading_for_profit=False,
        live_research_enabled=False,
        journal_path="/tmp/fake.jsonl",
        requires_journal_validation=True,
        budget_config=expired_config,
        journal_events_for_budget=valid_journal_events,
        exploration_queue=ExplorationQueue(candidates=(valid_candidate,)),
        allowed_symbols=("BTC/USD",),
        max_spread_bps=100.0,
        max_notional_usd=10.0,
    )

    report = run_live_research_readiness_dry_run(input_data)
    assert report.decision.status == LiveResearchReadinessStatus.BLOCKED_BUDGET


def test_no_valid_candidate_fails_closed(default_budget_config, valid_journal_events):
    input_data = build_live_research_readiness_input(
        live_trading_for_profit=False,
        live_research_enabled=False,
        journal_path="/tmp/fake.jsonl",
        requires_journal_validation=True,
        budget_config=default_budget_config,
        journal_events_for_budget=valid_journal_events,
        exploration_queue=ExplorationQueue(candidates=()), # Empty
        allowed_symbols=("BTC/USD",),
        max_spread_bps=100.0,
        max_notional_usd=10.0,
    )

    report = run_live_research_readiness_dry_run(input_data)
    assert report.decision.status == LiveResearchReadinessStatus.BLOCKED_NO_CANDIDATE


def test_valid_candidate_plus_passing_policy_returns_ready(default_budget_config, valid_journal_events, valid_candidate):
    input_data = build_live_research_readiness_input(
        live_trading_for_profit=False,
        live_research_enabled=False,
        journal_path="/tmp/fake.jsonl",
        requires_journal_validation=True,
        budget_config=default_budget_config,
        journal_events_for_budget=valid_journal_events,
        exploration_queue=ExplorationQueue(candidates=(valid_candidate,)),
        allowed_symbols=("BTC/USD",),
        max_spread_bps=100.0,
        max_notional_usd=10.0,
    )

    report = run_live_research_readiness_dry_run(input_data)
    assert report.decision.status == LiveResearchReadinessStatus.READY_FOR_APPROVAL_PACKET
    
    # Assert flags remain false
    assert report.executable is False
    assert report.order_submission_enabled is False
    assert report.broker_api_required is False
    assert report.runtime_mutation_required is False
    assert report.live_research_enabled is False
    
    # Assert packet preview is populated
    assert report.approval_packet_preview is not None
    assert report.approval_packet_preview["candidate_profile"] == "volatility_breakout"
    assert report.approval_packet_preview["net_expected_edge_bps"] == 65.0
    assert report.approval_packet_preview["explicit_statement_1"] == "no order will be placed without future approval"


def test_simulated_invalid_approval_phrase_blocked(default_budget_config, valid_journal_events, valid_candidate):
    input_data = build_live_research_readiness_input(
        live_trading_for_profit=False,
        live_research_enabled=False,
        journal_path="/tmp/fake.jsonl",
        requires_journal_validation=True,
        budget_config=default_budget_config,
        journal_events_for_budget=valid_journal_events,
        exploration_queue=ExplorationQueue(candidates=(valid_candidate,)),
        allowed_symbols=("BTC/USD",),
        max_spread_bps=100.0,
        max_notional_usd=10.0,
        simulated_approval_phrase="wrong phrase",
    )

    report = run_live_research_readiness_dry_run(input_data)
    assert report.decision.status == LiveResearchReadinessStatus.BLOCKED_MISSING_APPROVAL


def test_simulated_valid_approval_phrase_ready(default_budget_config, valid_journal_events, valid_candidate):
    valid_phrase = "LIVE_RESEARCH_APPROVED for Coinbase high-volatility evidence collection with max loss budget $50.0"
    input_data = build_live_research_readiness_input(
        live_trading_for_profit=False,
        live_research_enabled=False,
        journal_path="/tmp/fake.jsonl",
        requires_journal_validation=True,
        budget_config=default_budget_config,
        journal_events_for_budget=valid_journal_events,
        exploration_queue=ExplorationQueue(candidates=(valid_candidate,)),
        allowed_symbols=("BTC/USD",),
        max_spread_bps=100.0,
        max_notional_usd=10.0,
        simulated_approval_phrase=valid_phrase,
    )

    report = run_live_research_readiness_dry_run(input_data)
    assert report.decision.status == LiveResearchReadinessStatus.READY_FOR_APPROVAL_PACKET


def test_no_broker_order_live_imports_or_mutations_needed():
    import live_research_readiness_dry_run
    source = open(live_research_readiness_dry_run.__file__).read()
    
    assert "import broker" not in source
    assert "STOP_TRADING" not in source
    assert "launchctl" not in source
    assert "place_order" not in source
    assert "submit_order" not in source
    assert "import risk_manager" not in source
    assert "import order_manager" not in source
    assert "load_dotenv" not in source
    assert "open(" not in source  # Module does not write files
