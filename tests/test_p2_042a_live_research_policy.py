"""P2-042A offline tests for the live-research policy/config gate."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

import live_research_policy as policy


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config_live_research.yaml"
NOW = datetime(2026, 6, 13, 18, 0, tzinfo=timezone.utc)


def _enabled_config() -> dict:
    return {
        **policy.DEFAULT_LIVE_RESEARCH_POLICY,
        "LIVE_RESEARCH_FOR_DATA": True,
        "LIVE_RESEARCH_APPROVAL_TEXT": (
            "LIVE_RESEARCH_APPROVED for Coinbase high-volatility evidence "
            "collection with max loss budget $5.00"
        ),
        "LIVE_RESEARCH_BUDGET_USD": 5.0,
        "MAX_DAILY_RESEARCH_LOSS_USD": 2.0,
        "MAX_WEEKLY_RESEARCH_LOSS_USD": 4.0,
        "MAX_SINGLE_TRADE_NOTIONAL_USD": 1.0,
        "MAX_RESEARCH_TRADES_PER_DAY": 3,
        "ALLOWED_RESEARCH_SYMBOLS": ["BTC/USD", "ETH-USD"],
        "RESEARCH_MODE_EXPIRES_AT": (NOW + timedelta(days=1)).isoformat(),
    }


def _ready_state() -> dict:
    return {
        "now": NOW,
        "research_budget_loss_usd": 0.0,
        "daily_research_loss_usd": 0.0,
        "weekly_research_loss_usd": 0.0,
        "broker_error": False,
        "journal_capture_available": True,
        "fee_capture_available": True,
        "fill_capture_available": True,
        "mfe_mae_capture_available": True,
    }


def test_standalone_config_contains_required_safe_defaults():
    loaded = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    resolved = policy.resolve_live_research_policy(loaded)

    assert resolved["LIVE_RESEARCH_FOR_DATA"] is False
    assert resolved["LIVE_TRADING_FOR_PROFIT"] is False
    assert resolved["LIVE_RESEARCH_APPROVAL_REQUIRED"] is True
    assert resolved["ML_LIVE_INFLUENCE_ENABLED"] is False
    assert resolved["ONLINE_LEARNING_ENABLED"] is False
    assert set(policy.DEFAULT_LIVE_RESEARCH_POLICY) <= set(loaded)


def test_defaults_disable_live_research_and_profit_trading():
    report = policy.evaluate_live_research_policy()

    assert report["live_research_policy_allowed"] is False
    assert "live_research_for_data_disabled" in report["fail_closed_reasons"]
    assert report["mode_separation"]["live_trading_for_profit"] is False
    assert report["execution"]["actual_order_placement_enabled"] is False


def test_complete_future_policy_can_clear_policy_gate_without_enabling_execution():
    report = policy.evaluate_live_research_policy(_enabled_config(), **_ready_state())

    assert report["live_research_policy_allowed"] is True
    assert report["fail_closed_reasons"] == []
    assert report["execution"]["actual_order_placement_integrated"] is False
    assert report["execution"]["actual_order_placement_enabled"] is False


def test_research_mode_requires_exact_budget_matching_approval_phrase():
    config = _enabled_config()
    config["LIVE_RESEARCH_APPROVAL_TEXT"] = ""
    assert "live_research_approval_missing_or_invalid" in policy.live_research_fail_closed_reasons(
        config, **_ready_state()
    )

    config["LIVE_RESEARCH_APPROVAL_TEXT"] = (
        "LIVE_RESEARCH_APPROVED for Coinbase high-volatility evidence "
        "collection with max loss budget $4.00"
    )
    assert policy.validate_live_research_approval(
        config["LIVE_RESEARCH_APPROVAL_TEXT"], config["LIVE_RESEARCH_BUDGET_USD"]
    ) is False


def test_approval_required_flag_cannot_be_disabled_to_bypass_phrase():
    config = _enabled_config()
    config["LIVE_RESEARCH_APPROVAL_REQUIRED"] = False

    reasons = policy.live_research_fail_closed_reasons(config, **_ready_state())

    assert "live_research_approval_required_must_be_true" in reasons


def test_research_mode_requires_every_numeric_budget_and_limit():
    expected = {
        "LIVE_RESEARCH_BUDGET_USD": "live_research_budget_usd_required",
        "MAX_DAILY_RESEARCH_LOSS_USD": "max_daily_research_loss_usd_required",
        "MAX_WEEKLY_RESEARCH_LOSS_USD": "max_weekly_research_loss_usd_required",
        "MAX_SINGLE_TRADE_NOTIONAL_USD": "max_single_trade_notional_usd_required",
        "MAX_RESEARCH_TRADES_PER_DAY": "max_research_trades_per_day_required",
    }
    for field, reason in expected.items():
        config = _enabled_config()
        config[field] = None
        reasons = policy.live_research_fail_closed_reasons(config, **_ready_state())
        assert reason in reasons


def test_research_mode_requires_allowed_symbols_and_expiry():
    config = _enabled_config()
    config["ALLOWED_RESEARCH_SYMBOLS"] = []
    config["RESEARCH_MODE_EXPIRES_AT"] = ""

    reasons = policy.live_research_fail_closed_reasons(config, **_ready_state())

    assert "allowed_research_symbols_required" in reasons
    assert "research_mode_expiry_required" in reasons


def test_research_mode_fails_closed_when_expired_or_expiry_has_no_timezone():
    config = _enabled_config()
    config["RESEARCH_MODE_EXPIRES_AT"] = (NOW - timedelta(seconds=1)).isoformat()
    assert "research_mode_expired" in policy.live_research_fail_closed_reasons(
        config, **_ready_state()
    )

    config["RESEARCH_MODE_EXPIRES_AT"] = "2026-06-14T18:00:00"
    assert (
        "research_mode_expiry_invalid_or_timezone_missing"
        in policy.live_research_fail_closed_reasons(config, **_ready_state())
    )


def test_research_mode_fails_closed_on_total_daily_and_weekly_budget_breach():
    cases = (
        ({"research_budget_loss_usd": 5.0}, "research_budget_breached"),
        ({"daily_research_loss_usd": 2.0}, "daily_research_loss_cap_breached"),
        ({"weekly_research_loss_usd": 4.0}, "weekly_research_loss_cap_breached"),
    )
    for override, reason in cases:
        state = _ready_state()
        state.update(override)
        assert reason in policy.live_research_fail_closed_reasons(
            _enabled_config(), **state
        )


def test_research_mode_fails_closed_on_broker_error():
    state = _ready_state()
    state["broker_error"] = True

    assert "broker_error_kill_switch" in policy.live_research_fail_closed_reasons(
        _enabled_config(), **state
    )


def test_research_mode_fails_closed_on_each_missing_evidence_capture():
    cases = {
        "journal_capture_available": "missing_journal_capture",
        "fee_capture_available": "missing_fee_capture",
        "fill_capture_available": "missing_fill_capture",
        "mfe_mae_capture_available": "missing_mfe_mae_capture",
    }
    for state_field, reason in cases.items():
        state = _ready_state()
        state[state_field] = False
        assert reason in policy.live_research_fail_closed_reasons(
            _enabled_config(), **state
        )


def test_required_kill_switches_cannot_be_disabled():
    kill_switches = [
        field
        for field in policy.DEFAULT_LIVE_RESEARCH_POLICY
        if field.startswith("RESEARCH_KILL_SWITCH_")
    ]
    for field in kill_switches:
        config = _enabled_config()
        config[field] = False
        reason = f"{field.lower()}_must_be_true"
        assert reason in policy.live_research_fail_closed_reasons(
            config, **_ready_state()
        )


def test_research_mode_cannot_enable_profit_ml_or_online_learning():
    config = _enabled_config()
    config["LIVE_TRADING_FOR_PROFIT"] = True
    config["ML_LIVE_INFLUENCE_ENABLED"] = True
    config["ONLINE_LEARNING_ENABLED"] = True

    reasons = policy.live_research_fail_closed_reasons(config, **_ready_state())

    assert "live_trading_for_profit_must_remain_disabled" in reasons
    assert "ml_live_influence_must_remain_disabled" in reasons
    assert "online_learning_must_remain_disabled" in reasons


def test_research_policy_does_not_approve_strategy_risk_sizing_or_capital_changes():
    report = policy.evaluate_live_research_policy(_enabled_config(), **_ready_state())

    assert report["mode_separation"]["research_does_not_prove_profitability"] is True
    assert report["learning"]["ml_live_influence_enabled"] is False
    assert report["learning"]["online_learning_started"] is False
    assert report["change_authority"] == {
        "strategy_changes_approved": False,
        "risk_cap_changes_approved": False,
        "sizing_changes_approved": False,
        "capital_or_notional_increase_approved": False,
    }


def test_policy_module_has_no_runtime_or_broker_side_effect_hooks():
    text = (ROOT / "live_research_policy.py").read_text(encoding="utf-8")
    forbidden = (
        "broker_coinbase",
        "broker_alpaca",
        "place_order",
        "submit_order",
        "cancel_order",
        "close_position",
        "load_dotenv",
        "os.environ",
        "STOP_TRADING",
        "launchctl",
    )
    for token in forbidden:
        assert token not in text
