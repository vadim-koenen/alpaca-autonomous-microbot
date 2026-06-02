# ADVISORY ONLY - offline tests for P2-024D controlled Coinbase live symbol expansion.
# No broker calls, no .env reads, no order activity, no runtime/process mutations.

import importlib.util
import sys
from pathlib import Path

import yaml

from coinbase_controlled_live_symbol_expansion import (
    EXPANDED_LIVE_SYMBOLS,
    evaluate_symbol_eligibility,
    policy_from_crypto_config,
    quote_for_symbol,
    resolve_live_symbols_from_crypto_config,
)
from coinbase_fee_aware_pilot import calculate_fee_drag_metrics, evaluate_pilot_candidate
from risk_manager import AccountState, RiskManager, TradeProposal


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config_coinbase_crypto.yaml"
FIXTURES = ROOT / "tests" / "fixtures" / "controlled_live_symbol_expansion"
DASHBOARD_SCRIPT = ROOT / "scripts" / "coinbase_opportunity_dashboard.py"
LOOP_SCRIPT = ROOT / "scripts" / "coinbase_dashboard_observation_loop.py"
DIGEST_SCRIPT = ROOT / "scripts" / "coinbase_operator_digest.py"

dash_spec = importlib.util.spec_from_file_location("coinbase_opportunity_dashboard_p2_024d", DASHBOARD_SCRIPT)
dashboard_module = importlib.util.module_from_spec(dash_spec)
sys.modules[dash_spec.name] = dashboard_module
dash_spec.loader.exec_module(dashboard_module)

loop_spec = importlib.util.spec_from_file_location("coinbase_dashboard_observation_loop_p2_024d", LOOP_SCRIPT)
loop_module = importlib.util.module_from_spec(loop_spec)
sys.modules[loop_spec.name] = loop_module
loop_spec.loader.exec_module(loop_module)

digest_spec = importlib.util.spec_from_file_location("coinbase_operator_digest_p2_024d", DIGEST_SCRIPT)
digest_module = importlib.util.module_from_spec(digest_spec)
sys.modules[digest_spec.name] = digest_module
digest_spec.loader.exec_module(digest_module)


EXPANDED = ["BTC/USD", "ETH/USD", "ADA/USD", "AVAX/USD", "DOGE/USD", "LINK/USD", "LTC/USD"]


def _config():
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def _policy():
    return policy_from_crypto_config(_config()["crypto"])


def _metrics():
    return calculate_fee_drag_metrics(
        entry_value="1.0000",
        entry_fee="0.0060",
        exit_value="1.0025",
        exit_fee="0.0120",
        spread_slippage_buffer_rate="0.0010",
    )


def _proposal(symbol="ADA/USD", notional=5.00):
    return TradeProposal(
        symbol=symbol,
        asset_class="crypto",
        strategy="coinbase_exploration",
        side="buy",
        order_type="limit",
        notional=notional,
        limit_price=1.0,
        confidence=0.60,
        bid=1.0,
        ask=1.001,
        price=1.0005,
        stop_loss_price=0.985,
        take_profit_price=1.0325,
        meta={
            "fee_drag_expected_gross_move_rate": 0.0500,
            "fee_drag_required_gross_move_rate": 0.018970,
        },
    )


def test_config_declares_controlled_expanded_live_spot_basket_and_exclusions():
    cfg = _config()
    crypto = cfg["crypto"]
    section = crypto["controlled_live_symbol_expansion"]

    assert section["enabled"] is True
    assert section["live_symbols"] == EXPANDED
    assert section["excluded_symbols"] == ["SOL/USD"]
    assert crypto["live_symbols"] == EXPANDED
    assert crypto["symbols"] == EXPANDED
    assert crypto["fee_aware_pilot_symbols"] == EXPANDED
    assert crypto["fee_aware_pilot_excluded_symbols"] == ["SOL/USD"]
    assert crypto["controlled_exploration"]["approved_symbols"] == EXPANDED
    assert resolve_live_symbols_from_crypto_config(crypto) == EXPANDED
    assert list(EXPANDED_LIVE_SYMBOLS) == EXPANDED


def test_config_preserves_shared_caps_and_trade_limits():
    cfg = _config()
    crypto = cfg["crypto"]
    risk = cfg["global_risk"]
    section = crypto["controlled_live_symbol_expansion"]

    assert section["shared_caps"] is True
    assert crypto["max_trade_notional_usd"] == 10.00
    assert crypto["absolute_hard_trade_cap_usd"] == 10.00
    assert crypto["max_total_crypto_exposure_usd"] == 10.00
    assert risk["max_open_positions"] == 1
    assert risk["max_trades_per_day"] == 3
    assert crypto["fee_drag_guard_enabled"] is True


def test_sol_derivatives_and_unlisted_symbols_are_excluded():
    policy = _policy()
    quotes = yaml.safe_load((FIXTURES / "expanded_symbol_quotes_healthy.json").read_text(encoding="utf-8"))

    sol = evaluate_symbol_eligibility(
        symbol="SOL/USD",
        policy=policy,
        quote=quote_for_symbol("SOL/USD", quotes),
        regime="uptrend",
        allowed_strategies=["momentum_breakout"],
        expected_gross_move_rate="0.0500",
        required_gross_move_rate="0.018970",
    )
    xrp = evaluate_symbol_eligibility(
        symbol="XRP/USD",
        policy=policy,
        quote=quote_for_symbol("XRP/USD", quotes),
        regime="uptrend",
        allowed_strategies=["momentum_breakout"],
        expected_gross_move_rate="0.0500",
        required_gross_move_rate="0.018970",
    )
    perp = evaluate_symbol_eligibility(
        symbol="BTC-PERP",
        policy=policy,
        quote={"bid": "100", "ask": "100.01", "fresh": True},
        regime="uptrend",
        allowed_strategies=["momentum_breakout"],
        expected_gross_move_rate="0.0500",
        required_gross_move_rate="0.018970",
    )

    assert "symbol_excluded_external_inventory" in sol["skip_reasons"]
    assert "symbol_not_in_live_basket" in xrp["skip_reasons"]
    assert "symbol_not_in_live_basket" in perp["skip_reasons"]


def test_invalid_stale_and_wide_quotes_block_symbol():
    policy = _policy()
    quotes = yaml.safe_load((FIXTURES / "expanded_symbol_quotes_mixed_invalid_stale.json").read_text(encoding="utf-8"))

    avax = evaluate_symbol_eligibility(
        symbol="AVAX/USD",
        policy=policy,
        quote=quote_for_symbol("AVAX/USD", quotes),
        regime="uptrend",
        allowed_strategies=["momentum_breakout"],
        expected_gross_move_rate="0.0500",
        required_gross_move_rate="0.018970",
    )
    doge = evaluate_symbol_eligibility(
        symbol="DOGE/USD",
        policy=policy,
        quote=quote_for_symbol("DOGE/USD", quotes),
        regime="uptrend",
        allowed_strategies=["momentum_breakout"],
        expected_gross_move_rate="0.0500",
        required_gross_move_rate="0.018970",
    )
    link = evaluate_symbol_eligibility(
        symbol="LINK/USD",
        policy=policy,
        quote=quote_for_symbol("LINK/USD", quotes),
        regime="uptrend",
        allowed_strategies=["momentum_breakout"],
        expected_gross_move_rate="0.0500",
        required_gross_move_rate="0.018970",
    )

    assert "invalid_or_stale_quote" in avax["skip_reasons"]
    assert "spread_too_wide" in doge["skip_reasons"]
    assert "invalid_or_stale_quote" in link["skip_reasons"]


def test_fee_drag_regime_and_risk_limits_block_with_explicit_reasons():
    policy = _policy()
    quote = {"bid": "0.4500", "ask": "0.4503", "fresh": True, "max_spread_pct": "0.20"}

    weak_fee = evaluate_symbol_eligibility(
        symbol="ADA/USD",
        policy=policy,
        quote=quote,
        regime="uptrend",
        allowed_strategies=["momentum_breakout"],
        expected_gross_move_rate="0.0050",
        required_gross_move_rate="0.018970",
    )
    no_strategy = evaluate_symbol_eligibility(
        symbol="BTC/USD",
        policy=policy,
        quote={"bid": "100", "ask": "100.05", "fresh": True, "max_spread_pct": "0.10"},
        regime="downtrend",
        allowed_strategies=[],
        expected_gross_move_rate="0.0500",
        required_gross_move_rate="0.018970",
    )
    max_pos = evaluate_symbol_eligibility(
        symbol="ADA/USD",
        policy=policy,
        quote=quote,
        regime="uptrend",
        allowed_strategies=["momentum_breakout"],
        expected_gross_move_rate="0.0500",
        required_gross_move_rate="0.018970",
        open_positions=1,
        max_open_positions=1,
    )
    max_trades = evaluate_symbol_eligibility(
        symbol="ADA/USD",
        policy=policy,
        quote=quote,
        regime="uptrend",
        allowed_strategies=["momentum_breakout"],
        expected_gross_move_rate="0.0500",
        required_gross_move_rate="0.018970",
        daily_trade_count=3,
        max_trades_per_day=3,
    )

    assert "fee_drag_expected_edge_too_small" in weak_fee["skip_reasons"]
    assert "regime_disallows_strategy" in no_strategy["skip_reasons"]
    assert "max_open_positions_reached" in max_pos["skip_reasons"]
    assert "max_trades_per_day_reached" in max_trades["skip_reasons"]


def test_candidate_allowed_only_when_all_gates_clear():
    result = evaluate_symbol_eligibility(
        symbol="ADA/USD",
        policy=_policy(),
        quote={"bid": "0.4500", "ask": "0.4503", "fresh": True, "max_spread_pct": "0.20"},
        regime="uptrend",
        allowed_strategies=["momentum_breakout"],
        expected_gross_move_rate="0.0500",
        required_gross_move_rate="0.018970",
        open_positions=0,
        max_open_positions=1,
        daily_trade_count=0,
        max_trades_per_day=3,
    )

    assert result["allowed"] is True
    assert result["opportunity_verdict"] == "candidate"
    assert result["skip_reasons"] == []
    assert result["shared_caps"] is True


def test_fee_aware_candidate_uses_expanded_basket_and_current_5usd_notional():
    result = evaluate_pilot_candidate(
        symbol="ADA/USD",
        expected_gross_move_rate="0.0500",
        equity="50.3681",
        buying_power="49.4345",
        allowed_symbols=EXPANDED,
        excluded_symbols=["SOL/USD"],
        enabled=True,
        metrics=_metrics(),
    )

    assert result["allowed"] is True
    assert result["notional_usd"] == "5.0000"
    assert result["hard_cap_notional_usd"] == "10.0000"
    assert result["scaling_allowed"] is False


def test_risk_manager_enforces_expanded_basket_without_cap_increase(monkeypatch):
    manager = RiskManager()
    cfg = _config()
    monkeypatch.setattr(manager, "_c", lambda *keys, default=None: _cfg_lookup(cfg, *keys, default=default))
    state = AccountState(crypto_enabled=True, equity=50.3681, buying_power=49.4345)

    assert manager._check_controlled_live_symbol_expansion(_proposal("ADA/USD"), state, "live") == (True, "")
    assert manager._check_controlled_live_symbol_expansion(_proposal("SOL/USD"), state, "live") == (
        False,
        "symbol_excluded_external_inventory",
    )
    assert manager._check_controlled_live_symbol_expansion(_proposal("XRP/USD"), state, "live") == (
        False,
        "symbol_not_in_live_basket",
    )
    assert manager._check_controlled_fee_aware_pilot(_proposal("ADA/USD", 5.00), state, "live") == (True, "")
    assert manager._check_controlled_fee_aware_pilot(_proposal("ADA/USD", 11.00), state, "live")[0] is False


def test_dashboard_and_digest_show_expanded_symbols_but_no_trade_permission():
    dashboard = dashboard_module.build_dashboard(
        heartbeat_path=ROOT / "tests" / "fixtures" / "opportunity_dashboard" / "heartbeat_current_50usd.json",
        trend_source_json=FIXTURES / "expanded_symbol_regimes_sample.json",
        quote_source_json=FIXTURES / "expanded_symbol_quotes_healthy.json",
    )
    loop = loop_module.build_observation_loop(
        heartbeat_path=ROOT / "tests" / "fixtures" / "opportunity_dashboard" / "heartbeat_current_50usd.json",
        trend_source_json=FIXTURES / "expanded_symbol_regimes_sample.json",
        quote_source_json=FIXTURES / "expanded_symbol_quotes_healthy.json",
        iterations=1,
    )
    digest = digest_module.build_operator_digest(loop)

    symbols = [row["symbol"] for row in dashboard["symbols"]]
    assert symbols == EXPANDED
    assert dashboard["controlled_live_symbol_expansion"]["expanded_live_symbols"] == EXPANDED
    assert dashboard["controlled_live_symbol_expansion"]["shared_caps"] is True
    assert dashboard["trade_permission"] == "none"
    assert dashboard["live_order_actions_allowed"] is False
    assert dashboard["safety"]["sol_excluded"] is True
    assert dashboard["sizing"]["final_trade_notional"] == "5.0000"
    assert any(row["symbol"] == "ADA/USD" and row["opportunity_verdict"] == "candidate" for row in dashboard["symbols"])
    assert loop["aggregate"]["expanded_live_symbols"] == EXPANDED
    assert digest["expanded_live_symbols"] == EXPANDED
    assert digest["trade_permission"] == "none"
    assert digest["live_order_actions_allowed"] is False


def test_new_code_has_no_forbidden_runtime_hooks():
    combined = "\n".join([
        (ROOT / "coinbase_controlled_live_symbol_expansion.py").read_text(encoding="utf-8"),
        (ROOT / "strategy_router.py").read_text(encoding="utf-8"),
        (ROOT / "risk_manager.py").read_text(encoding="utf-8"),
        DASHBOARD_SCRIPT.read_text(encoding="utf-8"),
        LOOP_SCRIPT.read_text(encoding="utf-8"),
        DIGEST_SCRIPT.read_text(encoding="utf-8"),
    ])
    forbidden = [
        "broker_coinbase",
        "CoinbaseBroker",
        "load_dotenv",
        "append_coinbase_fill_row(",
        "logs/coinbase_fills.csv",
        "--live-read-only",
        "place_market_order(",
        "submit_order(",
        "preview_order(",
        "cancel_order(",
        "close_position(",
        "modify_order(",
        "launchctl",
        "prediction_market",
        "perpetual",
        "perps",
    ]
    for token in forbidden:
        assert token not in combined


def _cfg_lookup(cfg, *keys, default=None):
    node = cfg
    for key in keys:
        if not isinstance(node, dict):
            return default
        node = node.get(key, default)
        if node is None:
            return default
    return node
