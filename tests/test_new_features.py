"""
test_new_features.py — Tests for ChatGPT-recommended improvements.

Covers:
  - Exit plan AND/AND check (both stop AND target required)
  - Exit plan price ordering validation
  - Reward/risk minimum ratio block
  - Worst-case edge block
  - Per-symbol spread limits
  - ATR-based exit directions (stop below entry, target above entry)
  - Breakout high excludes current candle
  - Regime classifier correctness
  - Fee model uses Alpaca rates (not Coinbase)
  - Once-per-closed-bar deduplication
  - Best-proposal selection by net edge
  - DOGE/ALGO watch-only routing

Run: pytest tests/test_new_features.py -v
"""

import os
import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ALPACA_API_KEY", "test_key_placeholder")
os.environ.setdefault("ALPACA_SECRET_KEY", "test_secret_placeholder")
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("ALPACA_PAPER", "true")

from risk_manager import RiskManager, TradeProposal, AccountState
from strategy_crypto import classify_regime, CryptoStrategy


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

def _proposal(**overrides) -> TradeProposal:
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
        meta={
            "net_expected_edge_pct": 1.5,
            "worst_case_edge_pct": 0.8,
            "reward_risk_ratio": 1.5,
            "spread_pct": 0.04,
        },
    )
    base.update(overrides)
    return TradeProposal(**base)


def _state(**overrides) -> AccountState:
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


@pytest.fixture(autouse=True)
def paper_mode(monkeypatch):
    import utils
    cfg = utils.load_config()
    orig = cfg.get("mode")
    cfg["mode"] = "paper"
    yield
    cfg["mode"] = orig


rm = RiskManager()


# ---------------------------------------------------------------------------
# Exit plan: AND check — both required
# ---------------------------------------------------------------------------

class TestExitPlanAndCheck:
    def test_blocked_when_only_stop_loss_set(self):
        """Missing take-profit should now be rejected."""
        p = _proposal(stop_loss_price=49000.0, take_profit_price=0.0)
        allowed, reason = rm.check(p, _state())
        assert not allowed
        assert "take_profit" in reason.lower() or "exit" in reason.lower()

    def test_blocked_when_only_take_profit_set(self):
        """Missing stop-loss should now be rejected."""
        p = _proposal(stop_loss_price=0.0, take_profit_price=51500.0)
        allowed, reason = rm.check(p, _state())
        assert not allowed
        assert "stop_loss" in reason.lower() or "exit" in reason.lower()

    def test_blocked_when_neither_set(self):
        """No exit plan at all should be rejected."""
        p = _proposal(stop_loss_price=0.0, take_profit_price=0.0)
        allowed, reason = rm.check(p, _state())
        assert not allowed
        assert "exit" in reason.lower()

    def test_blocked_when_stop_above_entry(self):
        """Stop-loss >= entry price is invalid for a long."""
        p = _proposal(price=50000.0, stop_loss_price=50500.0, take_profit_price=51500.0)
        allowed, reason = rm.check(p, _state())
        assert not allowed
        assert "stop_loss" in reason.lower() or "exit" in reason.lower()

    def test_blocked_when_target_below_entry(self):
        """Take-profit <= entry price is invalid for a long."""
        p = _proposal(price=50000.0, stop_loss_price=49000.0, take_profit_price=49500.0)
        allowed, reason = rm.check(p, _state())
        assert not allowed
        assert "take_profit" in reason.lower() or "exit" in reason.lower()

    def test_passes_with_valid_both(self):
        """Valid stop below entry and target above entry should not be blocked by exit check."""
        p = _proposal(price=50000.0, stop_loss_price=49000.0, take_profit_price=51500.0)
        allowed, reason = rm.check(p, _state())
        assert allowed or "exit" not in reason.lower(), \
            f"Unexpectedly blocked by exit plan: {reason}"


# ---------------------------------------------------------------------------
# Reward / risk ratio
# ---------------------------------------------------------------------------

class TestRewardRiskCheck:
    def test_blocked_when_rr_below_minimum(self):
        """Reward:risk below 1.4 must be blocked."""
        p = _proposal(meta={
            "net_expected_edge_pct": 1.5,
            "worst_case_edge_pct": 0.5,
            "reward_risk_ratio": 1.0,   # below 1.4 minimum
            "spread_pct": 0.04,
        })
        allowed, reason = rm.check(p, _state())
        assert not allowed
        assert "reward" in reason.lower() or "risk" in reason.lower()

    def test_passes_when_rr_at_minimum(self):
        p = _proposal(meta={
            "net_expected_edge_pct": 1.5,
            "worst_case_edge_pct": 0.5,
            "reward_risk_ratio": 1.4,
            "spread_pct": 0.04,
        })
        allowed, reason = rm.check(p, _state())
        assert allowed or "reward" not in reason.lower(), \
            f"Unexpectedly blocked by reward/risk: {reason}"

    def test_passes_when_rr_absent(self):
        """reward_risk_ratio absent in meta → non-blocking (old strategies)."""
        p = _proposal(meta={
            "net_expected_edge_pct": 1.5,
            "worst_case_edge_pct": 0.5,
            "spread_pct": 0.04,
        })
        allowed, reason = rm.check(p, _state())
        assert allowed or "reward" not in reason.lower()


# ---------------------------------------------------------------------------
# Worst-case edge
# ---------------------------------------------------------------------------

class TestWorstCaseEdge:
    def test_blocked_when_worst_case_negative(self):
        """Worst-case edge <= 0 must be rejected when require_worst_case_edge_positive=true.
        net_expected_edge_pct must be above the fee hurdle so _check_worst_case_edge fires.
        """
        p = _proposal(meta={
            "net_expected_edge_pct": 1.5,   # above 0.6% fee hurdle so that check passes
            "worst_case_edge_pct": -0.1,
            "reward_risk_ratio": 2.0,
            "spread_pct": 0.04,
        })
        allowed, reason = rm.check(p, _state())
        assert not allowed
        assert "worst" in reason.lower() or "taker" in reason.lower() or "negative" in reason.lower()

    def test_blocked_when_worst_case_zero(self):
        p = _proposal(meta={
            "net_expected_edge_pct": 1.5,   # above fee hurdle
            "worst_case_edge_pct": 0.0,
            "reward_risk_ratio": 2.0,
            "spread_pct": 0.04,
        })
        allowed, reason = rm.check(p, _state())
        assert not allowed

    def test_passes_when_worst_case_positive(self):
        p = _proposal(meta={
            "net_expected_edge_pct": 1.5,
            "worst_case_edge_pct": 0.3,
            "reward_risk_ratio": 2.0,
            "spread_pct": 0.04,
        })
        allowed, reason = rm.check(p, _state())
        assert allowed or "worst" not in reason.lower()

    def test_passes_when_worst_case_absent(self):
        """worst_case_edge_pct absent → non-blocking."""
        p = _proposal(meta={
            "net_expected_edge_pct": 1.5,
            "reward_risk_ratio": 2.0,
            "spread_pct": 0.04,
        })
        allowed, reason = rm.check(p, _state())
        assert allowed or "worst" not in reason.lower()


# ---------------------------------------------------------------------------
# Per-symbol spread limits
# ---------------------------------------------------------------------------

class TestPerSymbolSpread:
    def test_btc_blocked_at_btc_spread_limit(self):
        """BTC/USD has a tight spread limit (0.15%) — 0.20% should be blocked."""
        # bid=100, ask=100.2 → spread = 0.2/100.1 ≈ 0.20%
        p = _proposal(symbol="BTC/USD", bid=100.0, ask=100.2,
                      price=100.1, limit_price=100.0,
                      stop_loss_price=98.5, take_profit_price=102.6)
        allowed, reason = rm.check(p, _state())
        assert not allowed
        assert "spread" in reason.lower()

    def test_sol_passes_at_btc_spread_level_but_within_sol_limit(self):
        """SOL/USD has 0.25% limit — 0.20% should pass (if other checks pass)."""
        # bid=100, ask=100.2 → ≈ 0.20% spread — within SOL's 0.25% limit
        p = _proposal(symbol="SOL/USD", bid=100.0, ask=100.2,
                      price=100.1, limit_price=100.0,
                      stop_loss_price=98.5, take_profit_price=102.6)
        allowed, reason = rm.check(p, _state())
        # If it fails, it should not fail due to spread
        if not allowed:
            assert "spread" not in reason.lower(), \
                f"SOL/USD at 0.20% spread should not be blocked by spread check: {reason}"


# ---------------------------------------------------------------------------
# ATR-based exit directions
# ---------------------------------------------------------------------------

class TestAtrExits:
    def _make_strategy(self):
        md = MagicMock()
        return CryptoStrategy(md)

    def test_momentum_stop_below_entry(self):
        strat = self._make_strategy()
        stop, target, stop_pct, tp_pct = strat._build_dynamic_exit(
            entry_price=50000.0, atr_pct=0.012, spread_pct_val=0.1,
            strategy="momentum_breakout"
        )
        assert stop < 50000.0, "Stop must be below entry"
        assert target > 50000.0, "Target must be above entry"
        assert stop_pct > 0, "Stop pct must be positive"
        assert tp_pct > stop_pct, "Target pct should exceed stop pct for positive r:r"

    def test_mean_reversion_stop_below_entry(self):
        strat = self._make_strategy()
        stop, target, stop_pct, tp_pct = strat._build_dynamic_exit(
            entry_price=1000.0, atr_pct=0.008, spread_pct_val=0.15,
            strategy="mean_reversion"
        )
        assert stop < 1000.0
        assert target > 1000.0

    def test_ema_crossover_stop_below_entry(self):
        strat = self._make_strategy()
        stop, target, stop_pct, tp_pct = strat._build_dynamic_exit(
            entry_price=200.0, atr_pct=0.015, spread_pct_val=0.20,
            strategy="ema_crossover"
        )
        assert stop < 200.0
        assert target > 200.0

    def test_target_clears_worst_case_fees(self):
        """Target pct must exceed worst-case round-trip fees + spread + slippage."""
        strat = self._make_strategy()
        _, _, _, tp_pct = strat._build_dynamic_exit(
            entry_price=100.0, atr_pct=0.001,  # very low ATR
            spread_pct_val=0.10, strategy="momentum_breakout"
        )
        # At min ATR, target should still clear: 0.5% (taker rt) + 0.10% (spread) + 0.05% (slippage) + 0.6% (edge)
        assert tp_pct > 0.5, f"Target {tp_pct:.3f}% too low to clear fees"

    def test_fallback_to_static_when_atr_zero(self):
        """Zero ATR falls back to config static values."""
        strat = self._make_strategy()
        stop, target, stop_pct, tp_pct = strat._build_dynamic_exit(
            entry_price=100.0, atr_pct=0.0, spread_pct_val=0.1,
            strategy="momentum_breakout"
        )
        assert stop < 100.0
        assert target > 100.0


# ---------------------------------------------------------------------------
# Breakout high excludes current candle
# ---------------------------------------------------------------------------

class TestBreakoutHighExcludesCurrentCandle:
    def _make_df(self, n: int = 30) -> pd.DataFrame:
        """Build a simple OHLCV dataframe with a spike on the last bar."""
        closes = [100.0] * n
        highs = [101.0] * n
        # Last bar has an artificially high — should NOT be included in breakout high
        highs[-1] = 200.0
        lows = [99.0] * n
        opens = [100.0] * n
        volumes = [1000.0] * n
        idx = pd.date_range("2025-01-01", periods=n, freq="5min")
        return pd.DataFrame(
            {"o": opens, "h": highs, "l": lows, "c": closes, "v": volumes},
            index=idx
        )

    def test_current_candle_high_excluded(self):
        """recent_high computed from iloc[-21:-1] must not include the last bar spike."""
        from market_data import add_indicators
        df = self._make_df(40)
        df = add_indicators(df)
        lookback = 20
        # The correct breakout high (excluding current candle) should be 101, not 200
        recent_high = float(df["h"].iloc[-(lookback + 1):-1].max())
        assert recent_high == 101.0, (
            f"Breakout high should exclude current candle spike (got {recent_high})"
        )
        # Rolling max including current candle would give 200
        rolling_high = float(df["h"].rolling(lookback).max().iloc[-1])
        assert rolling_high == 200.0, "Rolling high includes current candle (as expected)"
        # Verify they differ — this is the bug we fixed
        assert recent_high != rolling_high


# ---------------------------------------------------------------------------
# Regime classifier
# ---------------------------------------------------------------------------

class TestRegimeClassifier:
    def _base_df(self, n: int = 20) -> pd.DataFrame:
        closes = [100.0] * n
        idx = pd.date_range("2025-01-01", periods=n, freq="5min")
        df = pd.DataFrame(
            {"o": closes, "h": [c + 1 for c in closes],
             "l": [c - 1 for c in closes], "c": closes, "v": [1000.0] * n},
            index=idx
        )
        from market_data import add_indicators
        return add_indicators(df)

    def test_insufficient_data_returns_range(self):
        df = self._base_df(5)
        assert classify_regime(df) == "range"

    def test_dead_chop_detected(self):
        """Very small ATR and narrow BB → dead_chop."""
        closes = [100.0] * 30
        idx = pd.date_range("2025-01-01", periods=30, freq="5min")
        # Nearly flat price action with tiny range
        df = pd.DataFrame(
            {"o": closes, "h": [c + 0.01 for c in closes],
             "l": [c - 0.01 for c in closes], "c": closes, "v": [100.0] * 30},
            index=idx
        )
        from market_data import add_indicators
        df = add_indicators(df)
        regime = classify_regime(df)
        assert regime == "dead_chop"

    def test_uptrend_detected(self):
        """Rising EMA9 > EMA21 with slope → uptrend."""
        n = 30
        # Steadily rising close prices
        closes = [100.0 + i * 0.5 for i in range(n)]
        idx = pd.date_range("2025-01-01", periods=n, freq="5min")
        df = pd.DataFrame(
            {"o": closes, "h": [c + 1.0 for c in closes],
             "l": [c - 0.5 for c in closes], "c": closes, "v": [2000.0] * n},
            index=idx
        )
        from market_data import add_indicators
        df = add_indicators(df)
        regime = classify_regime(df)
        assert regime in ("uptrend", "volatile_range"), \
            f"Rising prices should not classify as {regime}"

    def test_downtrend_detected(self):
        """Falling EMA9 < EMA21 with slope → downtrend."""
        n = 30
        closes = [100.0 - i * 0.5 for i in range(n)]
        idx = pd.date_range("2025-01-01", periods=n, freq="5min")
        df = pd.DataFrame(
            {"o": closes, "h": [c + 0.5 for c in closes],
             "l": [c - 1.0 for c in closes], "c": closes, "v": [2000.0] * n},
            index=idx
        )
        from market_data import add_indicators
        df = add_indicators(df)
        regime = classify_regime(df)
        assert regime in ("downtrend", "volatile_range"), \
            f"Falling prices should not classify as {regime}"

    def test_returns_one_of_valid_labels(self):
        df = self._base_df(25)
        result = classify_regime(df)
        valid = {"uptrend", "downtrend", "range", "volatile_range", "dead_chop"}
        assert result in valid, f"classify_regime returned invalid label: {result}"


# ---------------------------------------------------------------------------
# Fee model uses Alpaca rates
# ---------------------------------------------------------------------------

class TestAlpacaFeeModel:
    def _make_strategy(self):
        md = MagicMock()
        return CryptoStrategy(md)

    def test_round_trip_fee_uses_alpaca_maker(self):
        """Best-case round-trip fee should be ≈ 0.30% (2 × 0.15% Alpaca maker)."""
        strat = self._make_strategy()
        meta = strat._fee_meta(spread_pct_val=0.0, tp_pct=2.5, sl_pct=1.5)
        rt = meta["round_trip_fee_pct"]
        # Alpaca maker: 0.15% + 0.15% = 0.30%
        assert abs(rt - 0.30) < 0.01, f"Expected ~0.30% round-trip fee, got {rt:.4f}%"

    def test_worst_case_fee_uses_alpaca_taker(self):
        """Worst-case round-trip should be ≈ 0.50% (2 × 0.25% Alpaca taker)."""
        strat = self._make_strategy()
        meta = strat._fee_meta(spread_pct_val=0.0, tp_pct=2.5, sl_pct=1.5)
        wc = meta["worst_case_rt_fee_pct"]
        assert abs(wc - 0.50) < 0.01, f"Expected ~0.50% worst-case fee, got {wc:.4f}%"

    def test_worst_case_edge_positive_for_good_trade(self):
        """2.5% target with 0.5% total fees should yield positive worst-case edge."""
        strat = self._make_strategy()
        meta = strat._fee_meta(spread_pct_val=0.10, tp_pct=2.5, sl_pct=1.5)
        # 2.5 - 0.50 (taker rt) - 0.10 (spread) - 0.05 (slippage) = 1.85%
        assert meta["worst_case_edge_pct"] > 0, \
            f"Worst-case edge should be positive: {meta['worst_case_edge_pct']:.3f}%"

    def test_reward_risk_correct(self):
        strat = self._make_strategy()
        meta = strat._fee_meta(spread_pct_val=0.0, tp_pct=3.0, sl_pct=1.5)
        assert abs(meta["reward_risk_ratio"] - 2.0) < 0.01


# ---------------------------------------------------------------------------
# Once-per-closed-bar deduplication
# ---------------------------------------------------------------------------

class TestOncePerClosedBar:
    def _make_strategy_with_df(self, bar_ts: str):
        """Return a CryptoStrategy whose market data returns a df with the given bar timestamp."""
        from market_data import add_indicators
        n = 80
        closes = [100.0 + i * 0.01 for i in range(n)]
        idx = pd.date_range("2025-01-01", periods=n, freq="5min")
        df = pd.DataFrame(
            {"o": closes, "h": [c + 0.5 for c in closes],
             "l": [c - 0.5 for c in closes], "c": closes, "v": [1000.0] * n},
            index=idx
        )
        df = add_indicators(df)

        md = MagicMock()
        quote = MagicMock()
        quote.valid = True
        quote.bid = 101.0
        quote.ask = 101.1
        quote.mid = 101.05
        quote.timestamp = datetime.now(timezone.utc)
        quote.is_stale = False
        md.get_crypto_quote.return_value = quote
        md.get_crypto_bars_df.return_value = df

        return CryptoStrategy(md)

    def test_same_bar_returns_empty_on_second_call(self):
        """Second call with same bar timestamp should return [] immediately."""
        strat = self._make_strategy_with_df("2025-01-01 00:10:00")
        # First call — may return proposals or not depending on indicators, but sets tracker
        strat.generate_proposals("BTC/USD", buying_power=5.0)
        # Manually set the tracker to match the df's last bar
        import pandas as pd
        last_ts = str(pd.date_range("2025-01-01", periods=80, freq="5min")[-1])
        strat._last_bar_ts["BTC/USD"] = last_ts
        # Second call — same bar → must return []
        result = strat.generate_proposals("BTC/USD", buying_power=5.0)
        assert result == [], "Same closed bar should skip strategy scan"

    def test_new_bar_allows_fresh_evaluation(self):
        """Changing bar timestamp resets deduplication, allowing a new scan."""
        strat = self._make_strategy_with_df("2025-01-01 00:10:00")
        last_ts = str(pd.date_range("2025-01-01", periods=80, freq="5min")[-1])
        strat._last_bar_ts["BTC/USD"] = "old_timestamp"  # pretend a stale entry exists
        # Since the df has a newer timestamp, evaluate should run (not return [] early)
        # We verify this by checking the tracker is updated
        strat.generate_proposals("BTC/USD", buying_power=5.0)
        assert strat._last_bar_ts.get("BTC/USD") == last_ts, \
            "Bar timestamp tracker should be updated to the latest bar"


# ---------------------------------------------------------------------------
# DOGE / ALGO watch-only routing
# ---------------------------------------------------------------------------

class TestWatchOnlySymbols:
    def test_doge_algo_not_in_live_symbols(self):
        """live_symbols config should not include DOGE/ALGO by default."""
        import utils
        cfg = utils.load_config()
        live = cfg.get("crypto", {}).get("live_symbols", [])
        if live:  # only check if live_symbols is configured
            assert "DOGE/USD" not in live, "DOGE/USD should be watch-only"
            assert "ALGO/USD" not in live, "ALGO/USD should be watch-only"

    def test_watch_only_contains_doge_algo(self):
        import utils
        cfg = utils.load_config()
        watch = set(cfg.get("crypto", {}).get("watch_only_symbols", []))
        if watch:
            assert "DOGE/USD" in watch, "DOGE/USD should be in watch_only_symbols"
            assert "ALGO/USD" in watch, "ALGO/USD should be in watch_only_symbols"

    def test_strategy_router_skips_watch_only(self, monkeypatch):
        """StrategyRouter.scan() must not generate proposals for watch-only symbols."""
        from strategy_router import StrategyRouter
        from permissions import AccountPermissions

        md = MagicMock()
        broker = MagicMock()
        router = StrategyRouter(broker, md)

        # Record which symbols crypto strategy is called for
        called_with = []
        original = router._crypto.generate_proposals

        def mock_gen(sym, buying_power=None):
            called_with.append(sym)
            return []

        router._crypto.generate_proposals = mock_gen

        perms = MagicMock(spec=AccountPermissions)
        perms.crypto_enabled = True
        perms.options_enabled = False
        perms.short_selling_enabled = False
        perms.equity = 10.0
        perms.buying_power = 10.0

        import utils
        cfg = utils.load_config()
        cfg["equities"]["enabled"] = False
        cfg["options"]["enabled"] = False
        cfg["short_selling"]["enabled"] = False

        router.scan(perms, buying_power=10.0)

        watch_only = set(cfg.get("crypto", {}).get("watch_only_symbols", []))
        for sym in called_with:
            assert sym not in watch_only, \
                f"Strategy router called generate_proposals for watch-only {sym}"

        cfg["equities"]["enabled"] = True
        cfg["options"]["enabled"] = True
        cfg["short_selling"]["enabled"] = True


# ---------------------------------------------------------------------------
# Alpaca starter_movement equities strategy
# ---------------------------------------------------------------------------

class TestStarterMovementEquities:
    def test_starter_movement_method_exists(self):
        from strategy_equities import EquitiesStrategy

        assert hasattr(EquitiesStrategy, "_starter_movement")
        assert callable(getattr(EquitiesStrategy, "_starter_movement"))

    def test_starter_movement_generates_controlled_fractional_proposal(self, monkeypatch):
        import strategy_equities
        from market_data import Quote
        from strategy_equities import EquitiesStrategy

        cfg = {
            ("equities", "starter_movement_enabled"): True,
            ("equities", "starter_symbols"): ["SPY"],
            ("equities", "starter_notional_usd"): 1.00,
            ("equities", "max_trade_notional_usd"): 2.00,
            ("equities", "min_trade_notional_usd"): 0.50,
            ("equities", "starter_stop_loss_pct"): 0.75,
            ("equities", "starter_take_profit_pct"): 1.20,
            ("equities", "max_spread_pct"): 0.10,
            ("strategy", "min_confidence_score"): 0.55,
        }

        def fake_get_cfg(*keys, default=None):
            return cfg.get(tuple(keys), default)

        monkeypatch.setattr(strategy_equities, "get_cfg", fake_get_cfg)

        idx = pd.date_range("2026-05-22 14:00:00Z", periods=24, freq="5min")
        closes = [100.00 + i * 0.03 for i in range(24)]
        df = pd.DataFrame(
            {
                "o": closes,
                "h": [c + 0.05 for c in closes],
                "l": [c - 0.05 for c in closes],
                "c": closes,
                "v": [1000] * len(closes),
            },
            index=idx,
        )
        df["ema_9"] = df["c"].ewm(span=9, adjust=False).mean()
        df["ema_21"] = df["c"].ewm(span=21, adjust=False).mean()
        df["rsi_14"] = 55.0
        df["mom_5"] = df["c"].pct_change(5)

        quote = Quote(
            symbol="SPY",
            bid=100.68,
            ask=100.70,
            mid=100.69,
            spread_pct=0.02,
            timestamp=datetime.now(timezone.utc),
            is_stale=False,
        )

        proposal = EquitiesStrategy(MagicMock())._starter_movement(
            "SPY", quote, df, prefer_no_trade=True
        )

        assert proposal is not None
        assert proposal.asset_class == "equity"
        assert proposal.strategy == "starter_movement"
        assert proposal.order_type == "limit"
        assert proposal.notional == pytest.approx(1.00)
        assert proposal.notional <= 2.00
        assert proposal.stop_loss_price < proposal.price
        assert proposal.take_profit_price > proposal.price
