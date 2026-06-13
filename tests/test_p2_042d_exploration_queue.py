"""Tests for P2-042D high-volatility exploration strategy queue."""

from datetime import datetime, timezone

import pytest

from live_research_exploration_queue import (
    ExplorationCandidate,
    ExplorationProfile,
    ExplorationQueue,
    build_exploration_candidate,
    candidate_to_journal_proposal_event,
    rank_exploration_candidates,
    reject_candidate_reasons,
    rejected_candidate_to_skip_journal_event,
    select_next_research_candidate,
)
from live_research_journal import validate_journal_event


@pytest.fixture
def now_utc():
    return datetime(2026, 6, 13, 20, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def ts_str(now_utc):
    return now_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _base_candidate_args(ts_str):
    return dict(
        symbol="BTC/USD",
        profile=ExplorationProfile.VOLATILITY_BREAKOUT,
        proposed_side="buy",
        proposed_notional_usd=5.0,
        gross_expected_edge_bps=100.0,
        expected_fee_bps=10.0,
        spread_bps=20.0,
        expected_slippage_bps=5.0,
        proposal_only_dry_run=False,
        signal_reason="high volatility detected",
        quote_timestamp_utc=ts_str,
        bid_price=100.0,
        ask_price=100.2,
        mid_price=100.1,
        quote_age_ms=50,
    )


def test_all_four_profiles_exist():
    assert ExplorationProfile.VOLATILITY_BREAKOUT.value == "volatility_breakout"
    assert ExplorationProfile.TREND_CONTINUATION.value == "trend_continuation"
    assert ExplorationProfile.REVERSAL_SNAPBACK.value == "reversal_snapback"
    assert ExplorationProfile.SPREAD_DISLOCATION_SKIP.value == "spread_dislocation_skip"


def test_fee_spread_slippage_drag_lowers_net_edge(ts_str):
    args = _base_candidate_args(ts_str)
    candidate = build_exploration_candidate(**args)
    # 100 - 10 - 20 - 5 = 65
    assert candidate.net_expected_edge_bps == 65.0


def test_deterministic_candidate_ranking(ts_str):
    args1 = _base_candidate_args(ts_str)
    args1["gross_expected_edge_bps"] = 100.0 # net 65

    args2 = _base_candidate_args(ts_str)
    args2["gross_expected_edge_bps"] = 200.0 # net 165
    args2["symbol"] = "ETH/USD"

    args3 = _base_candidate_args(ts_str)
    args3["gross_expected_edge_bps"] = 50.0  # net 15

    c1 = build_exploration_candidate(**args1)
    c2 = build_exploration_candidate(**args2)
    c3 = build_exploration_candidate(**args3)

    ranked = rank_exploration_candidates([c1, c3, c2])
    assert [c.gross_expected_edge_bps for c in ranked] == [200.0, 100.0, 50.0]


def test_negative_or_zero_net_edge_rejected(ts_str):
    args = _base_candidate_args(ts_str)
    args["gross_expected_edge_bps"] = 35.0 # 35 - 10 - 20 - 5 = 0
    c_zero = build_exploration_candidate(**args)

    reasons = reject_candidate_reasons(
        c_zero,
        allowed_symbols=("BTC/USD",),
        max_spread_bps=100.0,
        max_notional_usd=10.0,
        live_trading_for_profit=False,
    )
    assert any(r.reason == "negative_or_zero_net_edge" for r in reasons)


def test_excessive_spread_rejected(ts_str):
    args = _base_candidate_args(ts_str)
    args["spread_bps"] = 150.0
    c = build_exploration_candidate(**args)

    reasons = reject_candidate_reasons(
        c,
        allowed_symbols=("BTC/USD",),
        max_spread_bps=100.0,
        max_notional_usd=10.0,
        live_trading_for_profit=False,
    )
    assert any(r.reason == "excessive_spread" for r in reasons)


def test_excessive_notional_rejected(ts_str):
    args = _base_candidate_args(ts_str)
    args["proposed_notional_usd"] = 15.0
    c = build_exploration_candidate(**args)

    reasons = reject_candidate_reasons(
        c,
        allowed_symbols=("BTC/USD",),
        max_spread_bps=100.0,
        max_notional_usd=10.0,
        live_trading_for_profit=False,
    )
    assert any(r.reason == "excessive_notional" for r in reasons)


def test_disallowed_symbol_rejected(ts_str):
    args = _base_candidate_args(ts_str)
    args["symbol"] = "ETH/USD"
    c = build_exploration_candidate(**args)

    reasons = reject_candidate_reasons(
        c,
        allowed_symbols=("BTC/USD",),
        max_spread_bps=100.0,
        max_notional_usd=10.0,
        live_trading_for_profit=False,
    )
    assert any(r.reason == "symbol_not_allowed" for r in reasons)


def test_live_trading_for_profit_true_fails_closed(ts_str):
    args = _base_candidate_args(ts_str)
    c = build_exploration_candidate(**args)

    reasons = reject_candidate_reasons(
        c,
        allowed_symbols=("BTC/USD",),
        max_spread_bps=100.0,
        max_notional_usd=10.0,
        live_trading_for_profit=True,
    )
    assert any(r.reason == "live_profit_trading_enabled" for r in reasons)


def test_selected_candidate_is_highest_valid_net_edge(ts_str):
    args1 = _base_candidate_args(ts_str)
    args1["gross_expected_edge_bps"] = 100.0 # net 65

    args2 = _base_candidate_args(ts_str)
    args2["gross_expected_edge_bps"] = 200.0 # net 165
    args2["symbol"] = "ETH/USD" # Disallowed!

    c1 = build_exploration_candidate(**args1)
    c2 = build_exploration_candidate(**args2)

    queue = ExplorationQueue(candidates=(c1, c2))
    decision = select_next_research_candidate(
        queue,
        allowed_symbols=("BTC/USD",),
        max_spread_bps=100.0,
        max_notional_usd=10.0,
        live_trading_for_profit=False,
    )
    
    assert decision.candidate is not None
    assert decision.candidate.candidate_id == c1.candidate_id
    # Reason should capture why ETH was rejected though it's not strictly required in the output unless there's no candidate,
    # but the API allows `reject_reasons` to contain skips if we wanted, right now it returns first valid or all rejects.


def test_no_valid_candidates_returns_safe_no_candidate_decision(ts_str):
    args = _base_candidate_args(ts_str)
    args["gross_expected_edge_bps"] = -10.0 # Rejected
    c = build_exploration_candidate(**args)
    
    queue = ExplorationQueue(candidates=(c,))
    decision = select_next_research_candidate(
        queue,
        allowed_symbols=("BTC/USD",),
        max_spread_bps=100.0,
        max_notional_usd=10.0,
        live_trading_for_profit=False,
    )

    assert decision.candidate is None
    assert len(decision.reject_reasons) > 0


def test_proposal_only_dry_run_creates_non_executable_proposal(ts_str, now_utc):
    args = _base_candidate_args(ts_str)
    args["proposal_only_dry_run"] = True
    c = build_exploration_candidate(**args)

    assert c.proposal_only_dry_run is True

    event = candidate_to_journal_proposal_event(
        c,
        research_session_id="session-1",
        run_id="run-1",
        correlation_id="cor-1",
        now_utc=now_utc,
    )

    assert event["decision"] == "dry_run_only"
    assert event["mode"] == "dry_run"


def test_candidate_to_journal_proposal_event_is_p2_042b_compatible(ts_str, now_utc):
    args = _base_candidate_args(ts_str)
    c = build_exploration_candidate(**args)

    event = candidate_to_journal_proposal_event(
        c,
        research_session_id="session-1",
        run_id="run-1",
        correlation_id="cor-1",
        now_utc=now_utc,
    )

    assert event["event_type"] == "proposal_evaluated"
    assert validate_journal_event(event) == []


def test_rejected_candidate_to_skip_journal_event_is_p2_042b_compatible(ts_str, now_utc):
    args = _base_candidate_args(ts_str)
    c = build_exploration_candidate(**args)
    
    reasons = reject_candidate_reasons(
        c,
        allowed_symbols=("BTC/USD",),
        max_spread_bps=1.0, # Will force rejection
        max_notional_usd=10.0,
        live_trading_for_profit=False,
    )

    event = rejected_candidate_to_skip_journal_event(
        c,
        reasons=reasons,
        research_session_id="session-1",
        run_id="run-1",
        correlation_id="cor-1",
        now_utc=now_utc,
    )

    assert event["event_type"] == "skip_observed"
    assert validate_journal_event(event) == []


def test_no_broker_order_live_imports_or_mutations_needed():
    import live_research_exploration_queue
    source = open(live_research_exploration_queue.__file__).read()
    
    assert "broker_" not in source
    assert "STOP_TRADING" not in source
    assert "launchctl" not in source
    assert "place_order" not in source
    assert "submit_order" not in source
    assert "import risk_manager" not in source
    assert "import order_manager" not in source
    assert "load_dotenv" not in source
    assert "jsonl" not in source  # Module does not write files
