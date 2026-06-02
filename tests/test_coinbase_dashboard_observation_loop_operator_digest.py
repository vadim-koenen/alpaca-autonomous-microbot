# ADVISORY ONLY - offline tests for P2-024C Coinbase observation loop and digest.
# No broker calls, no .env reads, no order activity, no runtime/state/log writes.

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOOP_SCRIPT = ROOT / "scripts" / "coinbase_dashboard_observation_loop.py"
DIGEST_SCRIPT = ROOT / "scripts" / "coinbase_operator_digest.py"
FIXTURES = ROOT / "tests" / "fixtures" / "opportunity_dashboard"
TREND_FIXTURES = ROOT / "tests" / "fixtures" / "trend_advisory"
EXPANSION_FIXTURES = ROOT / "tests" / "fixtures" / "controlled_live_symbol_expansion"
FEE_FIXTURES = ROOT / "tests" / "fixtures" / "coinbase_fee_drag_profitability"
EXPANDED = ["BTC/USD", "ETH/USD", "ADA/USD", "AVAX/USD", "DOGE/USD", "LINK/USD", "LTC/USD"]

loop_spec = importlib.util.spec_from_file_location("coinbase_dashboard_observation_loop", LOOP_SCRIPT)
loop_module = importlib.util.module_from_spec(loop_spec)
sys.modules[loop_spec.name] = loop_module
loop_spec.loader.exec_module(loop_module)

digest_spec = importlib.util.spec_from_file_location("coinbase_operator_digest", DIGEST_SCRIPT)
digest_module = importlib.util.module_from_spec(digest_spec)
sys.modules[digest_spec.name] = digest_module
digest_spec.loader.exec_module(digest_module)


def _loop(**kwargs):
    params = {
        "heartbeat_path": FIXTURES / "heartbeat_current_50usd.json",
        "trend_source_json": EXPANSION_FIXTURES / "expanded_symbol_regimes_sample.json",
        "quote_source_json": EXPANSION_FIXTURES / "expanded_symbol_quotes_healthy.json",
        "fee_drag_source_json": FEE_FIXTURES / "real_style_1usd_eth_fee_drag_cycle.json",
        "iterations": 2,
    }
    params.update(kwargs)
    return loop_module.build_observation_loop(**params)


def test_observation_loop_current_style_expanded_candidate_is_stable_and_read_only():
    observation = _loop()
    aggregate = observation["aggregate"]

    assert observation["schema_version"] == "p2-024c.coinbase_dashboard_observation_loop.v1"
    assert observation["mode"] == "offline_read_only_dashboard_observation_loop"
    assert observation["iterations_executed"] == 2
    assert observation["loop_control"]["sleep_performed"] is False
    assert observation["loop_control"]["writes_files"] is False
    assert aggregate["stable_verdict"] == "READY_TO_OBSERVE"
    assert aggregate["current_style_verdict"] == "READY_TO_OBSERVE"
    assert aggregate["next_required_action"] == "observe_candidate_only_no_trade_permission"
    assert aggregate["final_trade_notional"] == "5.0000"
    assert aggregate["trade_permission"] == "none"
    assert aggregate["live_order_actions_allowed"] is False


def test_observation_loop_preserves_expanded_basket_sol_excluded_and_profit_gate():
    observation = _loop()
    aggregate = observation["aggregate"]

    assert aggregate["btc_eth_only"] is False
    assert aggregate["expanded_basket_enabled"] is True
    assert aggregate["expanded_live_symbols"] == EXPANDED
    assert aggregate["shared_caps"] is True
    assert aggregate["sol_excluded"] is True
    assert aggregate["eligible_symbols"] == EXPANDED
    assert aggregate["excluded_symbols"] == ["SOL/USD"]
    assert aggregate["profit_readout"]["global_status"] == "unsafe_to_aggregate"
    assert aggregate["profit_readout"]["aggregation_allowed"] is False
    assert aggregate["profit_readout"]["scaling_allowed"] is False
    assert observation["safety"]["broker_calls_made"] is False
    assert observation["safety"]["live_read_only_used"] is False
    assert observation["safety"]["runtime_restart_performed"] is False
    assert observation["safety"]["runtime_control_touched"] is False


def test_operator_digest_summarizes_current_style_loop():
    digest = digest_module.build_operator_digest(_loop())

    assert digest["schema_version"] == "p2-024c.coinbase_operator_digest.v1"
    assert digest["mode"] == "offline_read_only_operator_digest"
    assert digest["current_style_verdict"] == "READY_TO_OBSERVE"
    assert digest["stable_verdict"] == "READY_TO_OBSERVE"
    assert digest["next_required_action"] == "observe_candidate_only_no_trade_permission"
    assert digest["final_trade_notional"] == "5.0000"
    assert digest["trade_permission"] == "none"
    assert digest["live_order_actions_allowed"] is False
    assert digest["btc_eth_only"] is False
    assert digest["expanded_basket_enabled"] is True
    assert digest["expanded_live_symbols"] == EXPANDED
    assert digest["shared_caps"] is True
    assert digest["sol_excluded"] is True
    assert "trade_permission=none" in digest["operator_digest_text"]
    assert "profit_readout=unsafe_to_aggregate" in digest["operator_digest_text"]


def test_candidate_context_digest_observes_but_does_not_grant_trade_permission():
    observation = _loop(
        trend_source_json=EXPANSION_FIXTURES / "expanded_symbol_regimes_sample.json",
        quote_source_json=EXPANSION_FIXTURES / "expanded_symbol_quotes_healthy.json",
    )
    digest = digest_module.build_operator_digest(observation)

    assert digest["current_style_verdict"] == "READY_TO_OBSERVE"
    assert digest["next_required_action"] == "observe_candidate_only_no_trade_permission"
    assert digest["trade_permission"] == "none"
    assert digest["live_order_actions_allowed"] is False
    assert digest["safety"]["strategy_auto_trigger_from_trends"] is False


def test_blocked_runtime_digest_investigates_without_runtime_action():
    observation = _loop(heartbeat_path=FIXTURES / "heartbeat_risk_halt.json")
    digest = digest_module.build_operator_digest(observation)

    assert digest["current_style_verdict"] == "BLOCKED"
    assert digest["next_required_action"] == "investigate_offline_runtime_blocker_no_trade_action"
    assert digest["safety"]["runtime_restart_performed"] is False
    assert digest["safety"]["runtime_control_touched"] is False


def test_digest_can_build_directly_from_local_inputs():
    digest = digest_module.build_digest_from_inputs(
        heartbeat_path=FIXTURES / "heartbeat_current_50usd.json",
        trend_source_json=EXPANSION_FIXTURES / "expanded_symbol_regimes_sample.json",
        quote_source_json=EXPANSION_FIXTURES / "expanded_symbol_quotes_healthy.json",
        fee_drag_source_json=FEE_FIXTURES / "real_style_1usd_eth_fee_drag_cycle.json",
        iterations=1,
    )

    assert digest["current_style_verdict"] == "READY_TO_OBSERVE"
    assert digest["source_observation"]["iterations_executed"] == 1
    assert digest["trade_permission"] == "none"


def test_scripts_have_no_forbidden_runtime_hooks():
    combined = "\n".join([
        LOOP_SCRIPT.read_text(encoding="utf-8"),
        DIGEST_SCRIPT.read_text(encoding="utf-8"),
    ])
    forbidden = [
        "broker_coinbase",
        "CoinbaseBroker",
        "load_dotenv",
        "dotenv",
        "os.environ",
        "append_coinbase_fill_row(",
        "logs/coinbase_fills.csv",
        "--live-read-only",
        "place_market_order(",
        "submit_order(",
        "preview_order(",
        "cancel_order(",
        "close_position(",
        "modify_order(",
        "strategy_crypto",
        "risk_manager",
        "prediction_market",
        "perpetual",
        "perps",
    ]
    for token in forbidden:
        assert token not in combined
