"""Tests for the mandatory fee-edge gate in risk_manager.py.

The gate must reject ALL crypto entries where expected gross move
< worst-case round-trip fees + spread + slippage + safety margin,
regardless of whether the strategy attaches fee metadata or not.

Rates/margins are config-driven — tests patch get_cfg to verify.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from risk_manager import AccountState, RiskManager, TradeProposal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_state(**overrides) -> AccountState:
    defaults = dict(
        equity=60.0,
        buying_power=55.0,
        open_positions=0,
        open_position_symbols=[],
        open_orders=0,
        open_order_symbols=[],
        daily_realized_pnl=0.0,
        daily_trade_count=0,
        consecutive_losses=0,
        crypto_enabled=True,
        account_blocked=False,
        trading_blocked=False,
        api_error_count=0,
        tracked_crypto_exposure_usd=0.0,
        broker_recovered_crypto_exposure_usd=0.0,
        manual_review_crypto_position_count=0,
        non_controllable_crypto_position_count=0,
    )
    defaults.update(overrides)
    return AccountState(**defaults)


def _crypto_proposal(
    *,
    entry: float = 100_000.0,
    tp: float = 103_500.0,
    sl: float = 98_500.0,
    notional: float = 5.0,
    bid: float = 99_990.0,
    ask: float = 100_010.0,
    strategy: str = "momentum_breakout",
    side: str = "buy",
    meta: dict | None = None,
) -> TradeProposal:
    """Build a crypto proposal with realistic defaults."""
    from utils import now_utc

    return TradeProposal(
        symbol="BTC/USD",
        asset_class="crypto",
        strategy=strategy,
        side=side,
        order_type="limit",
        notional=notional,
        limit_price=entry,
        confidence=0.75,
        bid=bid,
        ask=ask,
        price=(bid + ask) / 2,
        quote_time=now_utc(),
        stop_loss_price=sl,
        take_profit_price=tp,
        meta=meta or {},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMandatoryFeeEdgeGate:
    """Test the _check_mandatory_fee_edge_gate method directly."""

    def setup_method(self):
        self.rm = RiskManager()

    def test_fee_negative_entry_rejected(self):
        """A proposal where TP barely clears entry should be rejected
        because the expected move can't cover fees+spread+slippage+margin."""
        # entry=100000, tp=100500 → 0.50% move
        # Coinbase taker=1.2% → rt=2.4%, spread~0.02%, slip=0.05%, margin=0.50%
        # Total cost ≈ 2.97%.  0.50% < 2.97% → REJECT
        p = _crypto_proposal(
            entry=100_000.0,
            tp=100_500.0,    # only 0.50% above entry
            sl=99_000.0,
        )
        allowed, reason = self.rm._check_mandatory_fee_edge_gate(
            p, _base_state(), "live"
        )
        assert not allowed, f"Expected rejection but got allowed; reason={reason}"
        assert "fee_edge_gate" in reason
        assert "expected_move" in reason

    def test_fee_positive_entry_passes(self):
        """A proposal with a healthy TP should pass the fee gate."""
        # entry=100000, tp=104000 → 4.0% move
        # Total cost ≈ 2.97%.  4.0% > 2.97% → PASS
        p = _crypto_proposal(
            entry=100_000.0,
            tp=104_000.0,    # 4.0% above entry
            sl=98_500.0,
        )
        allowed, reason = self.rm._check_mandatory_fee_edge_gate(
            p, _base_state(), "live"
        )
        assert allowed, f"Expected pass but got rejected; reason={reason}"

    def test_config_driven_rates(self):
        """Verify the gate reads fee rates from config, not hardcoded."""
        # With very low fees (0.1% maker/taker), even a small TP should pass
        p = _crypto_proposal(
            entry=100_000.0,
            tp=100_800.0,    # 0.80% move
            sl=99_500.0,
        )

        def low_fee_cfg(*keys, default=None):
            lookup = {
                ("fees", "taker_fee_pct"): 0.001,  # 0.10%
                ("crypto", "slippage_estimate_pct"): 0.01,  # 0.01%
                ("crypto", "fee_edge_safety_margin_pct"): 0.001,  # 0.10%
            }
            return lookup.get(keys, default)

        with patch.object(self.rm, "_c", side_effect=low_fee_cfg):
            allowed, reason = self.rm._check_mandatory_fee_edge_gate(
                p, _base_state(), "live"
            )
        # rt_fee=0.2% + spread~0.02% + slip=0.01% + margin=0.1% = ~0.33%
        # 0.80% > 0.33% → PASS
        assert allowed, f"Expected pass with low fees; reason={reason}"

    def test_config_driven_high_rates_reject(self):
        """With high config fees, even a decent TP gets rejected."""
        p = _crypto_proposal(
            entry=100_000.0,
            tp=103_000.0,    # 3.0% move
            sl=98_500.0,
        )

        def high_fee_cfg(*keys, default=None):
            lookup = {
                ("fees", "taker_fee_pct"): 0.020,   # 2.0% taker
                ("crypto", "slippage_estimate_pct"): 0.10,  # 0.10%
                ("crypto", "fee_edge_safety_margin_pct"): 0.005,  # 0.50%
            }
            return lookup.get(keys, default)

        with patch.object(self.rm, "_c", side_effect=high_fee_cfg):
            allowed, reason = self.rm._check_mandatory_fee_edge_gate(
                p, _base_state(), "live"
            )
        # rt_fee=4.0% + spread~0.02% + slip=0.10% + margin=0.50% = ~4.62%
        # 3.0% < 4.62% → REJECT
        assert not allowed, f"Expected rejection with high fees; reason={reason}"
        assert "fee_edge_gate" in reason

    def test_non_crypto_skipped(self):
        """Equity proposals bypass the fee gate entirely."""
        from utils import now_utc

        p = TradeProposal(
            symbol="AAPL",
            asset_class="equity",
            strategy="momentum_breakout",
            side="buy",
            order_type="limit",
            notional=5.0,
            limit_price=150.0,
            confidence=0.75,
            bid=149.90,
            ask=150.10,
            price=150.0,
            quote_time=now_utc(),
            stop_loss_price=148.0,
            take_profit_price=151.0,  # only 0.67% — would fail for crypto
            meta={},
        )
        allowed, reason = self.rm._check_mandatory_fee_edge_gate(
            p, _base_state(), "live"
        )
        assert allowed, "Equity proposals should bypass fee gate"

    def test_missing_take_profit_rejected(self):
        """If take_profit_price <= 0, the gate rejects (can't compute edge)."""
        p = _crypto_proposal(
            entry=100_000.0,
            tp=0.0,          # missing
            sl=98_500.0,
        )
        allowed, reason = self.rm._check_mandatory_fee_edge_gate(
            p, _base_state(), "live"
        )
        assert not allowed
        assert "fee_edge_gate" in reason
        assert "take_profit" in reason

    def test_tp_below_entry_rejected(self):
        """If take_profit <= entry, expected move is negative — reject."""
        p = _crypto_proposal(
            entry=100_000.0,
            tp=99_000.0,     # below entry
            sl=98_500.0,
        )
        allowed, reason = self.rm._check_mandatory_fee_edge_gate(
            p, _base_state(), "live"
        )
        assert not allowed
        assert "fee_edge_gate" in reason

    def test_sell_side_skipped(self):
        """Exit/sell proposals skip the fee gate (only entries are gated)."""
        p = _crypto_proposal(side="sell")
        allowed, reason = self.rm._check_mandatory_fee_edge_gate(
            p, _base_state(), "live"
        )
        assert allowed, "Sell-side should bypass fee gate"

    def test_log_output_contains_entry_skipped(self, caplog):
        """Verify the ENTRY_SKIPPED log line is emitted on rejection."""
        import logging

        p = _crypto_proposal(
            entry=100_000.0,
            tp=100_100.0,    # tiny 0.10% move
            sl=99_000.0,
        )
        with caplog.at_level(logging.WARNING, logger="risk_manager"):
            self.rm._check_mandatory_fee_edge_gate(p, _base_state(), "live")

        assert any("ENTRY_SKIPPED fee_edge_gate" in r.message for r in caplog.records), (
            "Expected ENTRY_SKIPPED log line"
        )

    def test_gate_cannot_silently_allow_fee_negative_trade(self):
        """Comprehensive check: a proposal with NO fee metadata at all
        (simulating a strategy that skips fee-awareness) must still be
        caught by the mandatory gate if the TP doesn't clear costs."""
        p = _crypto_proposal(
            entry=100_000.0,
            tp=101_000.0,    # 1.0% — below ~2.97% cost
            sl=99_000.0,
            strategy="some_new_strategy_without_fee_meta",
            meta={},         # no fee metadata at all
        )
        allowed, reason = self.rm._check_mandatory_fee_edge_gate(
            p, _base_state(), "live"
        )
        assert not allowed, (
            "Gate must reject fee-negative trade even without strategy fee metadata"
        )
        assert "fee_edge_gate" in reason
