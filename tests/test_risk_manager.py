"""
test_risk_manager.py — Deterministic risk manager tests.

These tests prove the risk layer blocks every unsafe scenario.
No real API calls are made. All account state is synthetic.

Run: pytest tests/test_risk_manager.py -v
"""

import os
import sys
from datetime import datetime, timezone, timedelta

import pytest

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set up minimal env before any import that touches utils
os.environ.setdefault("ALPACA_API_KEY", "test_key_placeholder")
os.environ.setdefault("ALPACA_SECRET_KEY", "test_secret_placeholder")
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("ALPACA_PAPER", "true")

from risk_manager import RiskManager, TradeProposal, AccountState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_proposal(**overrides) -> TradeProposal:
    """A valid crypto buy proposal that should pass all checks by default.

    notional=1.50 keeps it within config limits (min=0.50, max=2.00) and
    safely below the 85% buying-power-buffer check on a $10 account.
    """
    base = dict(
        symbol="BTC/USD",
        asset_class="crypto",
        strategy="momentum_breakout",
        side="buy",
        order_type="limit",
        notional=1.50,
        limit_price=50000.0,
        confidence=0.75,
        bid=49990.0,
        ask=50010.0,
        price=50000.0,
        quote_time=datetime.now(timezone.utc),
        stop_loss_price=49000.0,
        take_profit_price=51500.0,
    )
    base.update(overrides)
    return TradeProposal(**base)


def _healthy_state(**overrides) -> AccountState:
    """A healthy account state for a small $10 paper account."""
    base = dict(
        equity=10.0,
        buying_power=10.0,
        open_positions=0,
        open_position_symbols=[],
        open_orders=0,
        open_order_symbols=[],
        daily_realized_pnl=0.0,
        daily_trade_count=0,
        consecutive_losses=0,
        crypto_enabled=True,
        options_enabled=False,
        options_level=0,
        margin_enabled=False,
        short_selling_enabled=False,
        account_blocked=False,
        trading_blocked=False,
        api_error_count=0,
    )
    base.update(overrides)
    return AccountState(**base)


# Set config mode to paper for most tests
@pytest.fixture(autouse=True)
def set_paper_mode(monkeypatch):
    """Force config mode to paper so live gates don't interfere with basic tests."""
    import utils
    cfg = utils.load_config()
    original_mode = cfg.get("mode")
    cfg["mode"] = "paper"
    yield
    cfg["mode"] = original_mode


rm = RiskManager()


# ---------------------------------------------------------------------------
# Core kill switches
# ---------------------------------------------------------------------------

class TestLiveTradingGate:
    def test_live_trade_blocked_when_env_false(self, monkeypatch):
        """Live orders must be blocked when LIVE_TRADING env var is false."""
        import utils
        cfg = utils.load_config()
        cfg["mode"] = "live"
        monkeypatch.setenv("LIVE_TRADING", "false")
        cfg["live_trading"] = {"enabled": True, "require_env_live_trading_true": True,
                               "allow_crypto": True}

        proposal = _fresh_proposal()
        state = _healthy_state()
        allowed, reason = rm.check(proposal, state)

        assert not allowed, "Live trade should be blocked when LIVE_TRADING=false"
        assert "LIVE_TRADING" in reason or "master kill switch" in reason.lower()
        cfg["mode"] = "paper"

    def test_live_trade_blocked_when_config_disabled(self, monkeypatch):
        """Live orders must be blocked when live_trading.enabled is false."""
        import utils
        cfg = utils.load_config()
        cfg["mode"] = "live"
        monkeypatch.setenv("LIVE_TRADING", "true")
        cfg["live_trading"] = {"enabled": False, "require_env_live_trading_true": True,
                               "allow_crypto": True}

        proposal = _fresh_proposal()
        state = _healthy_state()
        allowed, reason = rm.check(proposal, state)

        assert not allowed
        assert "live_trading.enabled" in reason or "false" in reason.lower()
        cfg["mode"] = "paper"


class TestEquityFloor:
    def test_blocked_below_equity_floor(self, monkeypatch):
        """Live trading must stop if equity drops below the configured floor.
        Config has disable_live_below_equity: 1.50 for the $10 Coinbase account.
        """
        import utils
        cfg = utils.load_config()
        cfg["mode"] = "live"
        monkeypatch.setenv("LIVE_TRADING", "true")
        cfg["live_trading"] = {"enabled": True, "require_env_live_trading_true": True,
                               "allow_crypto": True}

        floor = cfg.get("account", {}).get("disable_live_below_equity", 7.0)
        below_floor_equity = floor * 0.5  # clearly below whatever the floor is

        proposal = _fresh_proposal()
        state = _healthy_state(equity=below_floor_equity, buying_power=below_floor_equity)
        allowed, reason = rm.check(proposal, state)

        assert not allowed
        assert "floor" in reason.lower() or "equity" in reason.lower()
        cfg["mode"] = "paper"


class TestDailyLossLimit:
    def test_blocked_after_daily_loss_limit(self):
        """No new trades after daily loss of $2."""
        proposal = _fresh_proposal()
        state = _healthy_state(daily_realized_pnl=-2.01)
        allowed, reason = rm.check(proposal, state)
        assert not allowed
        assert "daily loss" in reason.lower()

    def test_allowed_just_under_daily_loss_limit(self):
        proposal = _fresh_proposal()
        state = _healthy_state(daily_realized_pnl=-1.99)
        allowed, reason = rm.check(proposal, state)
        # Should still be allowed (other checks must pass too)
        # We verify only the daily loss check doesn't block
        if not allowed:
            assert "daily loss" not in reason.lower(), (
                f"Unexpectedly blocked by daily loss at $1.99: {reason}"
            )


class TestConsecutiveLosses:
    def test_blocked_after_2_consecutive_losses(self):
        """Stop trading after 2 consecutive losing trades."""
        proposal = _fresh_proposal()
        state = _healthy_state(consecutive_losses=2)
        allowed, reason = rm.check(proposal, state)
        assert not allowed
        assert "consecutive" in reason.lower()

    def test_allowed_after_1_consecutive_loss(self):
        proposal = _fresh_proposal()
        state = _healthy_state(consecutive_losses=1)
        allowed, reason = rm.check(proposal, state)
        if not allowed:
            assert "consecutive" not in reason.lower()


class TestMaxTrades:
    def test_blocked_at_max_trades_per_day(self):
        """No more than 5 trades per day."""
        proposal = _fresh_proposal()
        state = _healthy_state(daily_trade_count=5)
        allowed, reason = rm.check(proposal, state)
        assert not allowed
        assert "max trades" in reason.lower() or "trade" in reason.lower()


class TestMaxOpenPositions:
    def test_blocked_at_max_open_positions(self):
        """Blocked when open positions == configured max_open_positions."""
        import utils
        cfg = utils.load_config()
        limit = cfg.get("global_risk", {}).get("max_open_positions", 2)
        # Build a state that is exactly at the limit
        syms = [f"SYM{i}/USD" for i in range(limit)]
        proposal = _fresh_proposal()
        state = _healthy_state(open_positions=limit, open_position_symbols=syms)
        allowed, reason = rm.check(proposal, state)
        assert not allowed
        assert "position" in reason.lower()


class TestMaxNotional:
    def test_blocked_above_max_notional(self):
        """Blocked above max_trade_notional_usd."""
        import utils
        cfg = utils.load_config()
        max_n = cfg.get("crypto", {}).get("max_trade_notional_usd", 2.0)
        proposal = _fresh_proposal(notional=max_n + 0.50)
        state = _healthy_state()
        allowed, reason = rm.check(proposal, state)
        assert not allowed
        assert "notional" in reason.lower() or "max" in reason.lower()

    def test_blocked_below_min_notional(self):
        """Blocked below min_trade_notional_usd."""
        import utils
        cfg = utils.load_config()
        min_n = cfg.get("crypto", {}).get("min_trade_notional_usd", 0.50)
        too_small = round(min_n * 0.5, 2)
        proposal = _fresh_proposal(notional=too_small)
        state = _healthy_state()
        allowed, reason = rm.check(proposal, state)
        assert not allowed
        assert "notional" in reason.lower() or "min" in reason.lower()


class TestAggregateEquityExposure:
    @pytest.fixture(autouse=True)
    def _inside_equity_entry_window(self, monkeypatch):
        monkeypatch.setattr(
            "risk_manager.now_local",
            lambda: datetime(2026, 5, 26, 13, 0, tzinfo=timezone.utc),
        )

    def _equity_proposal(self, **overrides):
        base = dict(
            symbol="SPY",
            asset_class="equity",
            strategy="starter_movement",
            side="buy",
            order_type="limit",
            notional=1.00,
            limit_price=500.0,
            confidence=0.75,
            bid=499.99,
            ask=500.01,
            price=500.0,
            quote_time=datetime.now(timezone.utc),
            stop_loss_price=496.25,
            take_profit_price=506.0,
            meta={"spread_pct": 0.004},
        )
        base.update(overrides)
        return TradeProposal(**base)

    def _state(self, **overrides):
        base = dict(
            crypto_enabled=False,
            current_equity_position_exposure_usd=3.00,
            pending_equity_order_exposure_usd=1.00,
            recovered_equity_position_exposure_usd=0.00,
            aggregate_exposure_known=True,
        )
        base.update(overrides)
        return _healthy_state(**base)

    def test_aggregate_exposure_below_cap_allows(self):
        proposal = self._equity_proposal(notional=1.00)
        state = self._state(
            current_equity_position_exposure_usd=3.00,
            pending_equity_order_exposure_usd=1.00,
            recovered_equity_position_exposure_usd=0.50,
        )
        allowed, reason = rm.check(proposal, state)
        assert allowed, reason

    def test_aggregate_exposure_at_or_above_cap_blocks(self):
        proposal = self._equity_proposal(notional=1.00)
        state = self._state(
            current_equity_position_exposure_usd=6.00,
            pending_equity_order_exposure_usd=0.00,
            recovered_equity_position_exposure_usd=0.00,
        )
        allowed, reason = rm.check(proposal, state)
        assert not allowed
        assert "global_exposure_cap_exceeded" in reason

    def test_pending_open_orders_count_toward_projected_exposure(self):
        proposal = self._equity_proposal(notional=1.00)
        state = self._state(
            current_equity_position_exposure_usd=4.75,
            pending_equity_order_exposure_usd=0.50,
            recovered_equity_position_exposure_usd=0.00,
        )
        allowed, reason = rm.check(proposal, state)
        assert not allowed
        assert "global_exposure_cap_exceeded" in reason
        assert "pending=$0.50" in reason

    def test_unknown_aggregate_exposure_fails_closed(self):
        proposal = self._equity_proposal(notional=1.00)
        state = self._state(
            aggregate_exposure_known=False,
            current_equity_position_exposure_usd=None,
        )
        allowed, reason = rm.check(proposal, state)
        assert not allowed
        assert reason == "ENTRY_BLOCKED reason=aggregate_exposure_unknown"

    def test_starter_movement_cannot_exceed_six_dollar_global_cap(self):
        proposal = self._equity_proposal(strategy="starter_movement", notional=1.00)
        state = self._state(
            current_equity_position_exposure_usd=5.50,
            pending_equity_order_exposure_usd=0.00,
            recovered_equity_position_exposure_usd=0.00,
        )
        allowed, reason = rm.check(proposal, state)
        assert not allowed
        assert "global_exposure_cap_exceeded" in reason
        assert "cap=$6.00" in reason


# ---------------------------------------------------------------------------
# Asset class restrictions
# ---------------------------------------------------------------------------

class TestShortSellingRestrictions:
    def test_short_blocked_below_2000_equity(self):
        """Short selling requires $2,000+ equity."""
        proposal = _fresh_proposal(
            asset_class="short", side="short",
            symbol="SPY",
        )
        state = _healthy_state(equity=10.0, short_selling_enabled=False)
        allowed, reason = rm.check(proposal, state)
        assert not allowed
        assert "2000" in reason or "short" in reason.lower()

    def test_short_blocked_even_with_flag_but_low_equity(self):
        """Even if short_selling_enabled somehow, low equity must block."""
        proposal = _fresh_proposal(
            asset_class="short", side="short", symbol="SPY",
        )
        state = _healthy_state(equity=500.0, short_selling_enabled=True)
        allowed, reason = rm.check(proposal, state)
        assert not allowed
        assert "2000" in reason or "equity" in reason.lower()


class TestMarginRestrictions:
    def test_margin_blocked_below_2000_equity(self):
        proposal = _fresh_proposal(asset_class="margin", symbol="SPY")
        state = _healthy_state(equity=10.0, margin_enabled=False)
        allowed, reason = rm.check(proposal, state)
        assert not allowed


class TestOptionsRestrictions:
    def test_options_blocked_without_broker_approval(self):
        """Options require broker approval."""
        proposal = _fresh_proposal(
            asset_class="option", symbol="SPY",
            options_strategy="long_call", notional=2.0,
        )
        state = _healthy_state(options_enabled=False, options_level=0)
        allowed, reason = rm.check(proposal, state)
        assert not allowed
        assert "option" in reason.lower() or "approv" in reason.lower()


class TestCryptoRestrictions:
    def test_crypto_blocked_when_not_enabled(self):
        proposal = _fresh_proposal()
        state = _healthy_state(crypto_enabled=False)
        allowed, reason = rm.check(proposal, state)
        assert not allowed
        assert "crypto" in reason.lower()

    def test_crypto_blocked_for_unlisted_symbol(self):
        proposal = _fresh_proposal(symbol="XRP/USD")
        state = _healthy_state()
        allowed, reason = rm.check(proposal, state)
        assert not allowed
        assert "symbol" in reason.lower() or "allowed" in reason.lower()


class TestCryptoManualReviewGate:
    def test_manual_review_open_position_blocks_new_crypto_entry(self):
        proposal = _fresh_proposal()
        state = _healthy_state(
            tracked_crypto_exposure_usd=0.50,
            manual_review_crypto_position_count=1,
            non_controllable_crypto_position_count=0,
        )

        allowed, reason = rm.check(proposal, state)

        assert not allowed
        assert reason == "ENTRY_BLOCKED reason=manual_review_position_open"

    def test_non_controllable_open_position_blocks_new_crypto_entry(self):
        proposal = _fresh_proposal()
        state = _healthy_state(
            tracked_crypto_exposure_usd=0.50,
            manual_review_crypto_position_count=0,
            non_controllable_crypto_position_count=1,
        )

        allowed, reason = rm.check(proposal, state)

        assert not allowed
        assert reason == "ENTRY_BLOCKED reason=non_controllable_position_open"

    def test_normal_bot_controlled_position_follows_existing_exposure_cap(self):
        proposal = _fresh_proposal()
        below_cap = _healthy_state(
            tracked_crypto_exposure_usd=3.50,
            broker_recovered_crypto_exposure_usd=0.00,
            manual_review_crypto_position_count=0,
            non_controllable_crypto_position_count=0,
        )
        at_cap = _healthy_state(
            tracked_crypto_exposure_usd=4.00,
            broker_recovered_crypto_exposure_usd=0.00,
            manual_review_crypto_position_count=0,
            non_controllable_crypto_position_count=0,
        )

        allowed, reason = rm.check(proposal, below_cap)
        assert allowed, reason

        allowed, reason = rm.check(proposal, at_cap)
        assert not allowed
        assert "total crypto exposure" in reason

    def test_excluded_exposure_does_not_bypass_manual_review_gate(self):
        proposal = _fresh_proposal()
        state = _healthy_state(
            tracked_crypto_exposure_usd=0.00,
            broker_recovered_crypto_exposure_usd=0.00,
            manual_review_crypto_position_count=1,
            non_controllable_crypto_position_count=1,
        )

        allowed, reason = rm.check(proposal, state)

        assert not allowed
        assert reason == "ENTRY_BLOCKED reason=manual_review_position_open"


# ---------------------------------------------------------------------------
# Data quality checks
# ---------------------------------------------------------------------------

class TestStaleData:
    def test_blocked_on_stale_quote(self):
        """Stale data must block the trade when older than configured stale_data_seconds."""
        import utils
        cfg = utils.load_config()
        max_sec = cfg.get("crypto", {}).get("stale_data_seconds", 60)
        # Use twice the configured threshold so it's unambiguously stale
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=max_sec * 2)
        proposal = _fresh_proposal(quote_time=stale_time)
        state = _healthy_state()
        allowed, reason = rm.check(proposal, state)
        assert not allowed
        assert "stale" in reason.lower() or "old" in reason.lower()

    def test_blocked_on_none_quote_time(self):
        proposal = _fresh_proposal(quote_time=None)
        state = _healthy_state()
        allowed, reason = rm.check(proposal, state)
        assert not allowed
        assert "quote_time" in reason or "data" in reason.lower()


class TestSpreadCheck:
    def test_blocked_on_wide_spread(self):
        """Wide spread (>0.5%) must block the trade."""
        proposal = _fresh_proposal(bid=100.0, ask=102.0)  # 2% spread
        state = _healthy_state()
        allowed, reason = rm.check(proposal, state)
        assert not allowed
        assert "spread" in reason.lower()

    def test_blocked_on_invalid_bid_ask(self):
        proposal = _fresh_proposal(bid=0.0, ask=0.0)
        state = _healthy_state()
        allowed, reason = rm.check(proposal, state)
        assert not allowed


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_blocked_when_position_already_open(self):
        proposal = _fresh_proposal(symbol="BTC/USD")
        state = _healthy_state(
            open_positions=1,
            open_position_symbols=["BTC/USD"],
        )
        allowed, reason = rm.check(proposal, state)
        assert not allowed
        assert "position" in reason.lower() or "already" in reason.lower()

    def test_blocked_when_order_already_open(self):
        proposal = _fresh_proposal(symbol="BTC/USD")
        state = _healthy_state(
            open_orders=1,
            open_order_symbols=["BTC/USD"],
        )
        allowed, reason = rm.check(proposal, state)
        assert not allowed
        assert "order" in reason.lower() or "already" in reason.lower()


# ---------------------------------------------------------------------------
# Exit plan requirement
# ---------------------------------------------------------------------------

class TestExitPlan:
    def test_blocked_without_exit_plan(self):
        """Every trade must have stop-loss or take-profit set."""
        proposal = _fresh_proposal(stop_loss_price=0.0, take_profit_price=0.0)
        state = _healthy_state()
        allowed, reason = rm.check(proposal, state)
        assert not allowed
        assert "exit" in reason.lower() or "fee_edge_gate" in reason.lower()


# ---------------------------------------------------------------------------
# Account health
# ---------------------------------------------------------------------------

class TestAccountHealth:
    def test_blocked_when_account_blocked(self):
        proposal = _fresh_proposal()
        state = _healthy_state(account_blocked=True)
        allowed, reason = rm.check(proposal, state)
        assert not allowed
        assert "block" in reason.lower()

    def test_blocked_when_trading_blocked(self):
        proposal = _fresh_proposal()
        state = _healthy_state(trading_blocked=True)
        allowed, reason = rm.check(proposal, state)
        assert not allowed
        assert "block" in reason.lower()


# ---------------------------------------------------------------------------
# API error rate
# ---------------------------------------------------------------------------

class TestApiErrorHalt:
    def test_blocked_when_api_error_count_high(self):
        proposal = _fresh_proposal()
        state = _healthy_state(api_error_count=10)
        allowed, reason = rm.check(proposal, state)
        assert not allowed
        assert "error" in reason.lower() or "halt" in reason.lower()


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------

class TestConfidence:
    def test_blocked_on_low_confidence(self):
        proposal = _fresh_proposal(confidence=0.40)
        state = _healthy_state()
        allowed, reason = rm.check(proposal, state)
        assert not allowed
        assert "confidence" in reason.lower()


# ---------------------------------------------------------------------------
# Happy path — a valid proposal should pass
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_valid_paper_proposal_passes(self):
        """A well-formed paper-mode proposal should clear all risk checks."""
        proposal = _fresh_proposal()
        state = _healthy_state()
        allowed, reason = rm.check(proposal, state)
        assert allowed, f"Expected approval but got: {reason}"
        assert reason == "ok"
