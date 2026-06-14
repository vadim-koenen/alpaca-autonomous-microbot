import pytest
from profit_thesis_ev_contract import (
    TradeEconomicInputs,
    TradeCostModel,
    ExpectedMoveModel,
    ProfitThesisStatus,
    ProfitThesisRejectReason,
    build_profit_thesis,
    evaluate_profit_thesis,
    profit_thesis_to_dict,
    calculate_round_trip_cost_bps,
    calculate_expected_net_edge_bps,
)

@pytest.fixture
def valid_inputs():
    return TradeEconomicInputs(
        why_this_symbol="High relative volume and breakout setup",
        why_now="Resistance broken with 5x volume 1m ago",
        signal_name="volatility_breakout",
        signal_value=0.85
    )

@pytest.fixture
def valid_costs():
    return TradeCostModel(
        expected_fee_bps=10.0,
        expected_spread_bps=2.0,
        expected_slippage_bps=5.0
    )

@pytest.fixture
def valid_move():
    return ExpectedMoveModel(
        expected_move_bps=100.0,
        expected_hold_minutes=15,
        invalidation_price_or_bps=30.0,
        target_price_or_bps=100.0,
        max_loss_usd=5.0,
        evidence_required_after_trade="Check if volume sustained next 5m",
        scale_no_scale_criteria="No scaling, full size"
    )

def test_cost_model_calculates_round_trip_deterministically(valid_costs):
    # formula: fee + spread + slippage
    cost = calculate_round_trip_cost_bps(valid_costs)
    assert cost == 17.0

def test_net_edge_subtracts_fees_spread_slippage(valid_costs):
    net = calculate_expected_net_edge_bps(100.0, valid_costs)
    assert net == 100.0 - 17.0

def test_positive_gross_edge_can_fail_after_fees(valid_inputs, valid_costs, valid_move):
    # gross edge = 15.0, cost = 17.0 -> net = -2.0
    thesis = build_profit_thesis(valid_inputs, valid_costs, valid_move, gross_expected_edge_bps=15.0)
    decision = evaluate_profit_thesis(thesis, live_trading_for_profit=False)
    assert decision.status == ProfitThesisStatus.REJECTED
    assert ProfitThesisRejectReason.NEGATIVE_NET_EDGE in decision.reject_reasons

def test_zero_or_negative_net_edge_rejected(valid_inputs, valid_costs, valid_move):
    # gross edge = 17.0, cost = 17.0 -> net = 0.0
    thesis = build_profit_thesis(valid_inputs, valid_costs, valid_move, gross_expected_edge_bps=17.0)
    decision = evaluate_profit_thesis(thesis, live_trading_for_profit=False)
    assert decision.status == ProfitThesisStatus.REJECTED
    assert ProfitThesisRejectReason.NEGATIVE_NET_EDGE in decision.reject_reasons

def test_expected_move_below_round_trip_cost_rejected(valid_inputs, valid_costs):
    # expected_move = 15.0, cost = 17.0
    move = ExpectedMoveModel(
        expected_move_bps=15.0,
        expected_hold_minutes=15,
        invalidation_price_or_bps=5.0,
        target_price_or_bps=15.0,
        max_loss_usd=5.0,
        evidence_required_after_trade="x",
        scale_no_scale_criteria="x"
    )
    # Give it huge gross edge to bypass net edge checks (just testing the move check)
    thesis = build_profit_thesis(valid_inputs, valid_costs, move, gross_expected_edge_bps=100.0)
    decision = evaluate_profit_thesis(thesis, live_trading_for_profit=False)
    assert decision.status == ProfitThesisStatus.REJECTED
    assert ProfitThesisRejectReason.MOVE_BELOW_COST in decision.reject_reasons

def test_missing_why_this_symbol_rejected(valid_costs, valid_move):
    inputs = TradeEconomicInputs(why_this_symbol="", why_now="Now", signal_name="x", signal_value=1.0)
    thesis = build_profit_thesis(inputs, valid_costs, valid_move, 100.0)
    decision = evaluate_profit_thesis(thesis, live_trading_for_profit=False)
    assert ProfitThesisRejectReason.MISSING_NARRATIVE in decision.reject_reasons

def test_missing_why_now_rejected(valid_costs, valid_move):
    inputs = TradeEconomicInputs(why_this_symbol="Symbol", why_now="", signal_name="x", signal_value=1.0)
    thesis = build_profit_thesis(inputs, valid_costs, valid_move, 100.0)
    decision = evaluate_profit_thesis(thesis, live_trading_for_profit=False)
    assert ProfitThesisRejectReason.MISSING_NARRATIVE in decision.reject_reasons

def test_missing_invalidation_rejected(valid_inputs, valid_costs):
    move = ExpectedMoveModel(
        expected_move_bps=100.0,
        expected_hold_minutes=15,
        invalidation_price_or_bps=None,
        target_price_or_bps=100.0,
        max_loss_usd=5.0,
        evidence_required_after_trade="x",
        scale_no_scale_criteria="x"
    )
    thesis = build_profit_thesis(valid_inputs, valid_costs, move, 100.0)
    decision = evaluate_profit_thesis(thesis, live_trading_for_profit=False)
    assert ProfitThesisRejectReason.MISSING_INVALIDATION in decision.reject_reasons

def test_missing_target_rejected(valid_inputs, valid_costs):
    move = ExpectedMoveModel(
        expected_move_bps=100.0,
        expected_hold_minutes=15,
        invalidation_price_or_bps=30.0,
        target_price_or_bps=None,
        max_loss_usd=5.0,
        evidence_required_after_trade="x",
        scale_no_scale_criteria="x"
    )
    thesis = build_profit_thesis(valid_inputs, valid_costs, move, 100.0)
    decision = evaluate_profit_thesis(thesis, live_trading_for_profit=False)
    assert ProfitThesisRejectReason.MISSING_TARGET in decision.reject_reasons

def test_missing_evidence_requirements_rejected(valid_inputs, valid_costs):
    move = ExpectedMoveModel(
        expected_move_bps=100.0,
        expected_hold_minutes=15,
        invalidation_price_or_bps=30.0,
        target_price_or_bps=100.0,
        max_loss_usd=5.0,
        evidence_required_after_trade="",
        scale_no_scale_criteria="x"
    )
    thesis = build_profit_thesis(valid_inputs, valid_costs, move, 100.0)
    decision = evaluate_profit_thesis(thesis, live_trading_for_profit=False)
    assert ProfitThesisRejectReason.MISSING_EVIDENCE_REQUIREMENTS in decision.reject_reasons

def test_live_trading_for_profit_true_fails_closed(valid_inputs, valid_costs, valid_move):
    thesis = build_profit_thesis(valid_inputs, valid_costs, valid_move, 100.0)
    decision = evaluate_profit_thesis(thesis, live_trading_for_profit=True)
    assert decision.status == ProfitThesisStatus.REJECTED
    assert ProfitThesisRejectReason.LIVE_TRADING_FOR_PROFIT_NOT_ALLOWED in decision.reject_reasons

def test_valid_thesis_passes_only_when_net_edge_exceeds_cushion(valid_inputs, valid_costs, valid_move):
    # cost = 17.0, minimum_required = 34.0
    # gross = 50.0 -> net = 33.0 < 34.0 (fails)
    thesis_fail = build_profit_thesis(valid_inputs, valid_costs, valid_move, gross_expected_edge_bps=50.0)
    dec_fail = evaluate_profit_thesis(thesis_fail, False)
    assert dec_fail.status == ProfitThesisStatus.REJECTED
    assert ProfitThesisRejectReason.INSUFFICIENT_NET_EDGE in dec_fail.reject_reasons

    # gross = 52.0 -> net = 35.0 > 34.0 (passes)
    thesis_pass = build_profit_thesis(valid_inputs, valid_costs, valid_move, gross_expected_edge_bps=52.0)
    dec_pass = evaluate_profit_thesis(thesis_pass, False)
    assert dec_pass.status == ProfitThesisStatus.APPROVED
    assert not dec_pass.reject_reasons

def test_current_style_90_minute_low_edge_candidates_fail():
    # Model the current problem: 90 min timeout, zero/low edge, paying coinbase fees
    inputs = TradeEconomicInputs(why_this_symbol="random momentum", why_now="looks good", signal_name="momentum", signal_value=1.0)
    costs = TradeCostModel(expected_fee_bps=12.0, expected_spread_bps=2.0, expected_slippage_bps=2.0) # Cost = 16.0
    move = ExpectedMoveModel(
        expected_move_bps=10.0, # typical current low edge
        expected_hold_minutes=90,
        invalidation_price_or_bps=10.0,
        target_price_or_bps=10.0,
        max_loss_usd=5.0,
        evidence_required_after_trade="Wait 90 mins",
        scale_no_scale_criteria="none"
    )
    # Gross edge = 5.0 (which is less than cost)
    thesis = build_profit_thesis(inputs, costs, move, gross_expected_edge_bps=5.0)
    decision = evaluate_profit_thesis(thesis, False)
    
    assert decision.status == ProfitThesisStatus.REJECTED
    # Move is 10.0, Cost is 16.0, so move below cost
    assert ProfitThesisRejectReason.MOVE_BELOW_COST in decision.reject_reasons
    # Gross 5.0, Cost 16.0 -> Net -11.0
    assert ProfitThesisRejectReason.NEGATIVE_NET_EDGE in decision.reject_reasons

def test_output_dict_serialization_is_deterministic(valid_inputs, valid_costs, valid_move):
    thesis = build_profit_thesis(valid_inputs, valid_costs, valid_move, 100.0)
    decision = evaluate_profit_thesis(thesis, False)
    
    d = profit_thesis_to_dict(decision)
    assert d["status"] == "APPROVED"
    assert d["reject_reasons"] == []
    assert d["why_this_symbol"] == "High relative volume and breakout setup"
    assert d["expected_fee_bps"] == 10.0
    assert d["minimum_required_edge_bps"] == 34.0
    assert d["net_expected_edge_bps"] == 83.0

def test_no_broker_order_live_imports_required():
    import profit_thesis_ev_contract
    source = open(profit_thesis_ev_contract.__file__).read()
    assert "import broker" not in source
    assert "STOP_TRADING" not in source
    assert "launchctl" not in source
    assert "place_order" not in source
    assert "submit_order" not in source
    assert "open(" not in source
