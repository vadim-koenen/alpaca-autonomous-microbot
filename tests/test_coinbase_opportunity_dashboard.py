# ADVISORY ONLY - offline tests for P2-024B Coinbase opportunity dashboard.
# No broker calls, no .env reads, no order activity, no runtime/state/log writes.

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "coinbase_opportunity_dashboard.py"
FIXTURES = ROOT / "tests" / "fixtures" / "opportunity_dashboard"
TREND_FIXTURES = ROOT / "tests" / "fixtures" / "trend_advisory"
EXPANSION_FIXTURES = ROOT / "tests" / "fixtures" / "controlled_live_symbol_expansion"
FEE_FIXTURES = ROOT / "tests" / "fixtures" / "coinbase_fee_drag_profitability"
EXPANDED = ["BTC/USD", "ETH/USD", "ADA/USD", "AVAX/USD", "DOGE/USD", "LINK/USD", "LTC/USD"]

spec = importlib.util.spec_from_file_location("coinbase_opportunity_dashboard", SCRIPT)
dashboard_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = dashboard_module
spec.loader.exec_module(dashboard_module)


def _dashboard(**kwargs):
    params = {
        "heartbeat_path": FIXTURES / "heartbeat_current_50usd.json",
        "trend_source_json": EXPANSION_FIXTURES / "expanded_symbol_regimes_sample.json",
        "quote_source_json": EXPANSION_FIXTURES / "expanded_symbol_quotes_healthy.json",
        "fee_drag_source_json": FEE_FIXTURES / "real_style_1usd_eth_fee_drag_cycle.json",
    }
    params.update(kwargs)
    return dashboard_module.build_dashboard(**params)


def test_dashboard_schema_is_read_only_and_trade_permission_none():
    dashboard = _dashboard()

    assert dashboard["schema_version"] == "p2-024b.coinbase_opportunity_dashboard.v1"
    assert dashboard["mode"] == "offline_read_only_dashboard"
    assert dashboard["trade_permission"] == "none"
    assert dashboard["live_order_actions_allowed"] is False
    assert dashboard["risk_increase"] == "not_approved"
    assert dashboard["safety"]["broker_calls_made"] is False
    assert dashboard["safety"]["live_read_only_used"] is False
    assert dashboard["safety"]["order_actions_allowed"] is False
    assert dashboard["safety"]["risk_override_allowed"] is False


def test_current_expanded_context_observes_candidate_without_trade_permission():
    dashboard = _dashboard()

    assert dashboard["verdict"] == "READY_TO_OBSERVE"
    assert dashboard["runtime"]["open_positions"] == 0
    assert dashboard["runtime"]["risk_halt_active"] is False
    assert dashboard["sizing"]["final_trade_notional"] == "5.0000"

    by_symbol = {row["symbol"]: row for row in dashboard["symbols"]}
    assert list(by_symbol) == EXPANDED
    assert by_symbol["BTC/USD"]["local_regime"] == "downtrend"
    assert by_symbol["ETH/USD"]["local_regime"] == "downtrend"
    assert by_symbol["ADA/USD"]["local_regime"] == "uptrend"
    assert by_symbol["BTC/USD"]["allowed_strategies"] == []
    assert by_symbol["ETH/USD"]["allowed_strategies"] == []
    assert by_symbol["BTC/USD"]["opportunity_verdict"] == "sit_out"
    assert by_symbol["ETH/USD"]["opportunity_verdict"] == "sit_out"
    assert by_symbol["ADA/USD"]["opportunity_verdict"] == "candidate"
    assert dashboard["trade_permission"] == "none"


def test_dashboard_includes_trend_advisory_without_trade_trigger():
    dashboard = _dashboard()

    assert dashboard["trend_advisory"]["mode"] == "read_only_advisory"
    assert dashboard["trend_advisory"]["trade_permission"] == "none"
    assert dashboard["safety"]["strategy_auto_trigger_from_trends"] is False
    assert dashboard["controlled_live_symbol_expansion"]["expanded_live_symbols"] == EXPANDED
    assert dashboard["controlled_live_symbol_expansion"]["shared_caps"] is True


def test_fee_drag_latest_cycle_is_included_but_global_profit_stays_unsafe():
    dashboard = _dashboard()
    profit = dashboard["profit_readout"]

    assert profit["global_status"] == "unsafe_to_aggregate"
    assert profit["aggregation_allowed"] is False
    assert profit["scaling_allowed"] is False
    assert profit["latest_measured_cycle"]["cycle_id"] == "real-ethusd-029"
    assert profit["latest_measured_cycle"]["net_pnl"] == "-0.0155"
    assert profit["latest_measured_cycle"]["verdict"] == "FEE_DRAG_CONFIRMED"
    assert all(row["fee_drag_status"] == "threshold_active" for row in dashboard["symbols"])


def test_expanded_basket_and_sol_excluded():
    dashboard = _dashboard()

    symbols = [row["symbol"] for row in dashboard["symbols"]]
    assert symbols == EXPANDED
    assert "SOL/USD" not in symbols
    assert dashboard["safety"]["sol_excluded"] is True
    assert dashboard["sizing"]["eligible_symbols"] == EXPANDED
    assert dashboard["expanded_live_symbols"] == EXPANDED
    assert dashboard["sizing"]["excluded_symbols"] == ["SOL/USD"]


def test_candidate_context_still_has_no_trade_permission():
    dashboard = _dashboard(
        trend_source_json=EXPANSION_FIXTURES / "expanded_symbol_regimes_sample.json",
        quote_source_json=EXPANSION_FIXTURES / "expanded_symbol_quotes_healthy.json",
    )
    by_symbol = {row["symbol"]: row for row in dashboard["symbols"]}

    assert dashboard["verdict"] == "READY_TO_OBSERVE"
    assert by_symbol["ADA/USD"]["opportunity_verdict"] == "candidate"
    assert by_symbol["ADA/USD"]["allowed_strategies"] == ["momentum_breakout"]
    assert dashboard["trade_permission"] == "none"
    assert dashboard["live_order_actions_allowed"] is False


def test_risk_halt_blocks_dashboard_without_runtime_actions():
    dashboard = _dashboard(heartbeat_path=FIXTURES / "heartbeat_risk_halt.json")

    assert dashboard["verdict"] == "BLOCKED"
    assert "risk_halt_active" in dashboard["runtime"]["blockers"]
    assert all(row["opportunity_verdict"] == "blocked" for row in dashboard["symbols"])
    assert dashboard["safety"]["broker_calls_made"] is False


def test_existing_open_position_observes_instead_of_suggesting_new_entry():
    dashboard = _dashboard(heartbeat_path=FIXTURES / "heartbeat_with_open_position.json")

    assert dashboard["verdict"] == "OBSERVE_EXISTING_POSITION"
    assert dashboard["runtime"]["open_positions"] == 1
    assert dashboard["trade_permission"] == "none"


def test_missing_trend_source_blocks_symbol_evidence_safely(tmp_path):
    missing = tmp_path / "missing_trend.json"
    dashboard = _dashboard(trend_source_json=missing)

    assert dashboard["verdict"] in {"UNKNOWN", "SIT_OUT_CONFIRMED"}
    assert dashboard["trend_advisory"]["source_load_error"] is not None
    assert all("regime_disallows_strategy" in row["skip_reasons"] for row in dashboard["symbols"])


def test_script_has_no_forbidden_runtime_hooks():
    text = SCRIPT.read_text(encoding="utf-8")
    forbidden = [
        "broker_coinbase",
        "CoinbaseBroker",
        "load_dotenv",
        "dotenv",
        "os.environ",
        "append_coinbase_fill_row(",
        "logs/coinbase_fills.csv",
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
        assert token not in text
