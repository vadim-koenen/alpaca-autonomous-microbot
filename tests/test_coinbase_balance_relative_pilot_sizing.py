# ADVISORY ONLY - offline tests for P2-023B balance-relative Coinbase pilot sizing.
# No broker calls, no .env reads, no order activity, no state/log writes.

from pathlib import Path
import importlib.util
import sys

import yaml

from coinbase_fee_aware_pilot import (
    calculate_fee_drag_metrics,
    evaluate_pilot_candidate,
    resolve_balance_relative_pilot_sizing,
)
from risk_manager import AccountState, RiskManager, TradeProposal


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config_coinbase_crypto.yaml"
PREVIEW_SCRIPT = ROOT / "scripts" / "coinbase_pilot_sizing_preview.py"
EXPANDED = ["BTC/USD", "ETH/USD", "ADA/USD", "AVAX/USD", "DOGE/USD", "LINK/USD", "LTC/USD"]

spec = importlib.util.spec_from_file_location("coinbase_pilot_sizing_preview", PREVIEW_SCRIPT)
preview_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = preview_module
spec.loader.exec_module(preview_module)


def _metrics():
    return calculate_fee_drag_metrics(
        entry_value="1.0000",
        entry_fee="0.0060",
        exit_value="1.0025",
        exit_fee="0.0120",
        spread_slippage_buffer_rate="0.0010",
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


def test_observed_current_balance_resolves_to_5usd_with_min_floor():
    sizing = resolve_balance_relative_pilot_sizing(equity="50.3762", buying_power="49.4345")

    assert sizing["verdict"] == "SIZING_PREVIEW_OK"
    assert sizing["balance_source"] == "min_buying_power_equity"
    assert sizing["effective_balance"] == "49.4345"
    assert sizing["target_trade_notional"] == "4.9435"
    assert sizing["final_trade_notional"] == "5.0000"
    assert sizing["min_trade_floor_applied"] is True


def test_100_balance_resolves_to_10usd():
    sizing = resolve_balance_relative_pilot_sizing(equity="100", buying_power="100")

    assert sizing["verdict"] == "SIZING_PREVIEW_OK"
    assert sizing["target_trade_notional"] == "10.0000"
    assert sizing["final_trade_notional"] == "10.0000"


def test_250_balance_remains_capped_at_10usd():
    sizing = resolve_balance_relative_pilot_sizing(equity="250", buying_power="250")

    assert sizing["verdict"] == "SIZING_PREVIEW_OK"
    assert sizing["target_trade_notional"] == "25.0000"
    assert sizing["final_trade_notional"] == "10.0000"
    assert sizing["absolute_hard_trade_cap_usd"] == "10.0000"


def test_30_balance_blocks_instead_of_blindly_forcing_5usd():
    sizing = resolve_balance_relative_pilot_sizing(equity="30", buying_power="30")

    assert sizing["verdict"] == "BLOCKED"
    assert sizing["reason"] == "target_notional_below_fee_aware_minimum"
    assert sizing["final_trade_notional"] is None


def test_candidate_never_exceeds_buying_power_or_absolute_hard_cap():
    low_bp = evaluate_pilot_candidate(
        symbol="ETH/USD",
        expected_gross_move_rate="0.0325",
        equity="100.00",
        buying_power="4.99",
        enabled=True,
        metrics=_metrics(),
    )
    high_balance = evaluate_pilot_candidate(
        symbol="ETH/USD",
        expected_gross_move_rate="0.0325",
        equity="200.00",
        buying_power="200.00",
        enabled=True,
        metrics=_metrics(),
    )

    assert low_bp["allowed"] is False
    assert low_bp["reason"] == "target_notional_below_fee_aware_minimum"
    assert high_balance["allowed"] is True
    assert high_balance["notional_usd"] == "10.0000"
    assert high_balance["absolute_hard_trade_cap_usd"] == "10.0000"


def test_expanded_symbols_eligible_and_sol_excluded():
    for symbol in EXPANDED:
        result = evaluate_pilot_candidate(
            symbol=symbol,
            expected_gross_move_rate="0.0325",
            equity="100.00",
            buying_power="100.00",
            allowed_symbols=EXPANDED,
            enabled=True,
            metrics=_metrics(),
        )
        assert result["allowed"] is True
        assert result["notional_usd"] == "10.0000"

    sol = evaluate_pilot_candidate(
        symbol="SOL/USD",
        expected_gross_move_rate="0.0500",
        equity="100.00",
        buying_power="100.00",
        allowed_symbols=EXPANDED,
        enabled=True,
        metrics=_metrics(),
    )
    assert sol["allowed"] is False
    assert sol["reason"] == "sol_external_staked_inventory_excluded"


def test_fee_drag_guard_still_blocks_low_expected_edge():
    result = evaluate_pilot_candidate(
        symbol="ETH/USD",
        expected_gross_move_rate="0.0050",
        equity="100.00",
        buying_power="100.00",
        enabled=True,
        metrics=_metrics(),
    )

    assert result["allowed"] is False
    assert result["reason"] == "fee_drag_expected_edge_too_small"


def test_risk_manager_enforces_balance_relative_size_and_caps(monkeypatch):
    manager = RiskManager()
    monkeypatch.setattr(manager, "_c", _pilot_cfg)

    state_50 = AccountState(crypto_enabled=True, equity=50.3762, buying_power=49.4345)
    state_100 = AccountState(crypto_enabled=True, equity=100.0, buying_power=100.0)
    state_30 = AccountState(crypto_enabled=True, equity=30.0, buying_power=30.0)

    assert manager._check_controlled_fee_aware_pilot(_proposal(notional=1.00), state_50, "live")[0] is False
    assert manager._check_controlled_fee_aware_pilot(_proposal(notional=6.00), state_50, "live")[0] is False
    assert manager._check_controlled_fee_aware_pilot(_proposal(notional=5.00), state_50, "live") == (True, "")
    assert manager._check_controlled_fee_aware_pilot(_proposal(notional=10.00), state_100, "live") == (True, "")
    assert manager._check_controlled_fee_aware_pilot(_proposal(notional=11.00), state_100, "live")[0] is False
    assert manager._check_controlled_fee_aware_pilot(_proposal(notional=5.00), state_30, "live")[0] is False


def test_config_declares_balance_relative_5_to_10_expanded_spot_basket():
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))

    assert config["global_risk"]["max_open_positions"] == 1
    assert config["global_risk"]["max_trades_per_day"] == 3
    assert config["crypto"]["controlled_fee_aware_pilot_enabled"] is True
    assert config["crypto"]["pilot_trade_percent_of_balance"] == 0.10
    assert config["crypto"]["min_trade_notional_usd"] == 5.00
    assert config["crypto"]["max_trade_notional_usd"] == 10.00
    assert config["crypto"]["absolute_hard_trade_cap_usd"] == 10.00
    assert config["crypto"]["live_symbols"] == EXPANDED
    assert config["crypto"]["symbols"] == EXPANDED
    assert config["crypto"]["fee_aware_pilot_symbols"] == EXPANDED
    assert config["crypto"]["fee_aware_pilot_excluded_symbols"] == ["SOL/USD"]
    assert config["crypto"]["controlled_live_symbol_expansion"]["enabled"] is True
    assert config["crypto"]["controlled_live_symbol_expansion"]["shared_caps"] is True
    assert config["crypto"]["multi_asset_spot"]["enabled"] is False


def test_preview_script_outputs_expected_shape():
    preview = preview_module.build_preview(equity="50.3762", buying_power="49.4345")

    assert preview["verdict"] == "SIZING_PREVIEW_OK"
    assert preview["final_trade_notional"] == "5.0000"
    assert preview["eligible_symbols"] == EXPANDED
    assert preview["expanded_live_symbols"] == EXPANDED
    assert preview["excluded_symbols"] == ["SOL/USD"]
    assert preview["risk_increase"] == "not_approved"
    assert preview["safety"]["broker_calls_made"] is False


def test_new_sizing_code_is_offline_and_has_no_forbidden_runtime_hooks(tmp_path, monkeypatch):
    combined = "\n".join([
        (ROOT / "coinbase_fee_aware_pilot.py").read_text(encoding="utf-8"),
        PREVIEW_SCRIPT.read_text(encoding="utf-8"),
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
    preview = preview_module.build_preview(equity="100", buying_power="100", config_path=CONFIG)
    after = {p.name for p in tmp_path.iterdir()}

    assert preview["safety"]["secrets_or_env_read"] is False
    assert after == before
