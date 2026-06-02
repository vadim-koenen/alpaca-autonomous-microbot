# ADVISORY ONLY - tests for offline Coinbase fee-drag pilot gate/reporting.
# No broker calls, no .env reads, no order activity, no state/log writes.

from pathlib import Path
import importlib.util
import sys

import yaml

from coinbase_fee_aware_pilot import (
    calculate_fee_drag_metrics,
    evaluate_pilot_candidate,
)
from risk_manager import AccountState, RiskManager, TradeProposal


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "coinbase_fee_drag_profitability_report.py"
FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "coinbase_fee_drag_profitability"
CONFIG = Path(__file__).resolve().parents[1] / "config_coinbase_crypto.yaml"
EXPANDED = ["BTC/USD", "ETH/USD", "ADA/USD", "AVAX/USD", "DOGE/USD", "LINK/USD", "LTC/USD"]

spec = importlib.util.spec_from_file_location("coinbase_fee_drag_profitability_report", SCRIPT)
fee_report = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fee_report
spec.loader.exec_module(fee_report)


def _report(name: str):
    return fee_report.build_report(FIXTURES / name)


def _measured_metrics():
    return calculate_fee_drag_metrics(
        entry_value="1.0000",
        entry_fee="0.0060",
        exit_value="1.0025",
        exit_fee="0.0120",
        spread_slippage_buffer_rate="0.0010",
    )


def _proposal(symbol="ETH/USD", notional=5.00, expected=0.0325, required=0.018970):
    return TradeProposal(
        symbol=symbol,
        asset_class="crypto",
        strategy="coinbase_exploration",
        side="buy",
        order_type="limit",
        notional=notional,
        limit_price=100.0,
        confidence=0.60,
        bid=100.0,
        ask=100.01,
        price=100.005,
        stop_loss_price=98.50,
        take_profit_price=103.25,
        meta={
            "controlled_fee_aware_pilot_enabled": True,
            "fee_drag_expected_gross_move_rate": expected,
            "fee_drag_required_gross_move_rate": required,
        },
    )


def _pilot_cfg(*keys, default=None):
    cfg = {
        "crypto": {
            "controlled_fee_aware_pilot_enabled": True,
            "fee_aware_pilot_symbols": EXPANDED,
            "fee_aware_pilot_excluded_symbols": ["SOL/USD"],
            "pilot_trade_percent_of_balance": 0.10,
            "min_trade_notional_usd": 5.00,
            "max_trade_notional_usd": 10.00,
            "absolute_hard_trade_cap_usd": 10.00,
            "balance_basis": "buying_power_then_equity",
            "fee_drag_guard_enabled": True,
        }
    }
    cur = cfg
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def test_real_style_1usd_eth_cycle_confirms_fee_drag():
    report = _report("real_style_1usd_eth_fee_drag_cycle.json")

    assert report["verdict"] == "FEE_DRAG_CONFIRMED"
    assert report["cycle_id"] == "real-ethusd-029"
    assert report["product_id"] == "ETH-USD"
    assert report["gross_pnl"] == "0.0025"
    assert report["total_fees"] == "0.0180"
    assert report["net_pnl"] == "-0.0155"
    assert report["micro_trade_fee_drag_detected"] is True
    assert report["break_even_exit_value"] == "1.0180"
    assert report["recommendation"] == "do_not_continue_1usd_micro_trades"
    assert report["scale_allowed"] is False
    assert report["scaling_allowed"] is False
    assert report["risk_increase"] == "not_approved"


def test_positive_net_cycle_is_ok_only_when_gross_exceeds_fees():
    report = _report("positive_net_fee_clears_cycle.json")

    assert report["verdict"] == "OK"
    assert report["gross_pnl"] == "0.2000"
    assert report["total_fees"] == "0.0200"
    assert report["net_pnl"] == "0.1800"
    assert report["micro_trade_fee_drag_detected"] is False
    assert report["scaling_allowed"] is False


def test_redacted_or_non_numeric_payload_blocks_fee_drag_report():
    report = _report("redacted_numeric_values_blocked_cycle.json")

    assert report["verdict"] == "BLOCKED"
    assert report["net_pnl"] is None
    assert report["scaling_allowed"] is False
    assert any("missing_or_non_numeric" in blocker for blocker in report["blockers"])


def test_controlled_pilot_notional_is_balance_relative_and_caps_oversized_requests():
    metrics = _measured_metrics()
    result = evaluate_pilot_candidate(
        symbol="ETH/USD",
        expected_gross_move_rate="0.0325",
        equity="50.00",
        buying_power="50.00",
        max_trade_notional_usd="25.00",
        absolute_hard_trade_cap_usd="10.00",
        min_trade_notional_usd="5.00",
        allowed_symbols=EXPANDED,
        enabled=True,
        metrics=metrics,
    )

    assert result["allowed"] is True
    assert result["notional_usd"] == "5.0000"
    assert result["hard_cap_notional_usd"] == "10.0000"
    assert result["micro_trade_1usd_disabled"] is True
    assert result["scaling_allowed"] is False


def test_skip_when_expected_move_is_below_fee_threshold():
    result = evaluate_pilot_candidate(
        symbol="ETH/USD",
        expected_gross_move_rate="0.0050",
        equity="50.00",
        buying_power="50.00",
        allowed_symbols=EXPANDED,
        enabled=True,
        metrics=_measured_metrics(),
    )

    assert result["allowed"] is False
    assert result["reason"] == "fee_drag_expected_edge_too_small"
    assert result["scaling_allowed"] is False


def test_allow_candidate_only_when_expected_move_clears_fee_plus_buffer():
    result = evaluate_pilot_candidate(
        symbol="BTC/USD",
        expected_gross_move_rate="0.0325",
        equity="50.00",
        buying_power="50.00",
        allowed_symbols=EXPANDED,
        enabled=True,
        metrics=_measured_metrics(),
    )

    assert result["allowed"] is True
    assert result["reason"] == "ok"
    assert result["notional_usd"] == "5.0000"


def test_sol_remains_excluded_from_controlled_pilot():
    result = evaluate_pilot_candidate(
        symbol="SOL/USD",
        expected_gross_move_rate="0.0500",
        equity="50.00",
        buying_power="50.00",
        allowed_symbols=EXPANDED,
        enabled=True,
        metrics=_measured_metrics(),
    )

    assert result["allowed"] is False
    assert result["reason"] == "sol_external_staked_inventory_excluded"


def test_risk_manager_rejects_1usd_above_resolved_size_and_above_10usd(monkeypatch):
    manager = RiskManager()
    monkeypatch.setattr(manager, "_c", _pilot_cfg)
    state_50 = AccountState(crypto_enabled=True, equity=50.0, buying_power=50.0)
    state_100 = AccountState(crypto_enabled=True, equity=100.0, buying_power=100.0)

    allowed_1, reason_1 = manager._check_controlled_fee_aware_pilot(
        _proposal(notional=1.00),
        state_50,
        "live",
    )
    allowed_too_big_for_50, reason_too_big_for_50 = manager._check_controlled_fee_aware_pilot(
        _proposal(notional=6.00),
        state_50,
        "live",
    )
    allowed_above_cap, reason_above_cap = manager._check_controlled_fee_aware_pilot(
        _proposal(notional=11.00),
        state_100,
        "live",
    )
    allowed_ok, reason_ok = manager._check_controlled_fee_aware_pilot(
        _proposal(notional=5.00),
        state_50,
        "live",
    )

    assert allowed_1 is False
    assert "1usd_micro_trades_disabled" in reason_1
    assert allowed_too_big_for_50 is False
    assert "exceeds balance-relative pilot size" in reason_too_big_for_50
    assert allowed_above_cap is False
    assert "exceeds controlled pilot cap" in reason_above_cap
    assert allowed_ok is True
    assert reason_ok == ""


def test_coinbase_config_is_controlled_5usd_expanded_spot_basket():
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))

    assert config["global_risk"]["max_open_positions"] == 1
    assert config["global_risk"]["max_trades_per_day"] == 3
    assert config["crypto"]["controlled_fee_aware_pilot_enabled"] is True
    assert config["crypto"]["pilot_trade_percent_of_balance"] == 0.10
    assert config["crypto"]["min_trade_notional_usd"] == 5.00
    assert config["crypto"]["max_trade_notional_usd"] == 10.00
    assert config["crypto"]["absolute_hard_trade_cap_usd"] == 10.00
    assert config["crypto"]["max_total_crypto_exposure_usd"] == 10.00
    assert config["crypto"]["live_symbols"] == EXPANDED
    assert config["crypto"]["symbols"] == EXPANDED
    assert config["crypto"]["fee_aware_pilot_symbols"] == EXPANDED
    assert config["crypto"]["controlled_exploration"]["approved_symbols"] == EXPANDED
    assert config["crypto"]["controlled_live_symbol_expansion"]["enabled"] is True
    assert config["crypto"]["controlled_live_symbol_expansion"]["shared_caps"] is True
    assert config["crypto"]["multi_asset_spot"]["enabled"] is False
    assert "SOL/USD" not in config["crypto"]["live_symbols"]
    assert "SOL/USD" not in config["crypto"]["symbols"]


def test_fee_drag_scripts_are_offline_and_have_no_forbidden_runtime_hooks(tmp_path, monkeypatch):
    combined = "\n".join([
        SCRIPT.read_text(encoding="utf-8"),
        (Path(__file__).resolve().parents[1] / "coinbase_fee_aware_pilot.py").read_text(encoding="utf-8"),
    ])
    forbidden = [
        "broker_coinbase",
        "load_dotenv",
        "os.environ",
        "append_coinbase_fill_row(",
        "logs/coinbase_fills.csv",
        "place_order",
        "place_market_order",
        "submit_order",
        "preview_order",
        "cancel_order",
        "close_position",
        "modify_order",
    ]
    for token in forbidden:
        assert token not in combined

    (tmp_path / ".env").write_text("COINBASE_API_KEY=NEVER\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    before = {p.name for p in tmp_path.iterdir()}
    report = _report("real_style_1usd_eth_fee_drag_cycle.json")
    after = {p.name for p in tmp_path.iterdir()}

    assert report["safety"]["offline_only"] is True
    assert report["safety"]["broker_calls_made"] is False
    assert report["safety"]["live_read_only_used"] is False
    assert report["safety"]["secrets_or_env_read"] is False
    assert report["safety"]["orders_cancels_closes_modifications"] is False
    assert after == before
