"""
test_permissions.py — Permissions gate tests.

Tests that the permissions module fails closed on bad/missing data.
Uses a mock broker — no real API calls.

Run: pytest tests/test_permissions.py -v
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ALPACA_API_KEY", "test_key")
os.environ.setdefault("ALPACA_SECRET_KEY", "test_secret")
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("ALPACA_PAPER", "true")

from permissions import AccountPermissions, fetch_permissions


def _mock_broker(
    equity=10.0,
    buying_power=10.0,
    cash=10.0,
    status="ACTIVE",
    account_blocked=False,
    trading_blocked=False,
    transfers_blocked=False,
    account_number="TEST123",
    options_approved_level=None,
    multiplier=1,
    pattern_day_trader=False,
    daytrade_count=None,
    btc_tradable=True,
    is_paper=True,
    raise_on_account=False,
    raise_on_asset=False,
):
    broker = MagicMock()
    broker.is_paper = is_paper

    if raise_on_account:
        broker.get_account.side_effect = Exception("API error")
    else:
        account = MagicMock()
        account.equity = equity
        account.buying_power = buying_power
        account.cash = cash
        account.status = status
        account.account_blocked = account_blocked
        account.trading_blocked = trading_blocked
        account.transfers_blocked = transfers_blocked
        account.account_number = account_number
        account.currency = "USD"
        account.options_approved_level = options_approved_level
        account.multiplier = multiplier
        account.pattern_day_trader = pattern_day_trader
        account.daytrade_count = daytrade_count
        # crypto_status must be "ACTIVE" when btc_tradable=True so that
        # permissions.py's two-factor check (crypto_status AND asset.tradable) passes.
        account.crypto_status = "ACTIVE" if btc_tradable else "INACTIVE"
        broker.get_account.return_value = account

    if raise_on_asset:
        broker.get_asset.side_effect = Exception("Asset not found")
    else:
        asset = MagicMock()
        asset.tradable = btc_tradable
        broker.get_asset.return_value = asset

    return broker


class TestFailClosed:
    def test_api_error_returns_blocked_defaults(self):
        """If get_account() raises, return fail-closed defaults (all blocked)."""
        broker = _mock_broker(raise_on_account=True)
        perms = fetch_permissions(broker)
        assert perms.account_blocked is True
        assert perms.trading_blocked is True
        assert perms.crypto_enabled is False
        assert perms.options_enabled is False
        assert perms.margin_enabled is False
        assert perms.short_selling_enabled is False
        assert perms.equity == 0.0

    def test_missing_permissions_fails_closed(self):
        """None returned from get_account() fails closed."""
        broker = MagicMock()
        broker.is_paper = True
        broker.get_account.return_value = None
        perms = fetch_permissions(broker)
        assert perms.account_blocked is True
        assert perms.equity == 0.0

    def test_asset_error_disables_crypto(self):
        """If asset check raises, crypto should be disabled (fail closed)."""
        broker = _mock_broker(raise_on_asset=True)
        perms = fetch_permissions(broker)
        assert perms.crypto_enabled is False


class TestCryptoPermissions:
    def test_crypto_enabled_when_asset_tradable(self):
        broker = _mock_broker(btc_tradable=True)
        perms = fetch_permissions(broker)
        assert perms.crypto_enabled is True

    def test_crypto_disabled_when_asset_not_tradable(self):
        broker = _mock_broker(btc_tradable=False)
        perms = fetch_permissions(broker)
        assert perms.crypto_enabled is False


class TestOptionsPermissions:
    def test_options_disabled_by_default(self):
        broker = _mock_broker(options_approved_level=None)
        perms = fetch_permissions(broker)
        assert perms.options_enabled is False
        assert perms.options_level == 0

    def test_options_enabled_at_level_1(self):
        broker = _mock_broker(options_approved_level=1)
        perms = fetch_permissions(broker)
        assert perms.options_enabled is True
        assert perms.options_level == 1

    def test_options_disabled_at_level_0(self):
        broker = _mock_broker(options_approved_level=0)
        perms = fetch_permissions(broker)
        assert perms.options_enabled is False


class TestMarginShortPermissions:
    def test_margin_disabled_with_low_equity(self):
        """Margin requires multiplier > 1 AND equity >= $2000."""
        broker = _mock_broker(equity=10.0, multiplier=2)
        perms = fetch_permissions(broker)
        assert perms.margin_enabled is False  # equity too low
        assert perms.short_selling_enabled is False

    def test_margin_disabled_with_multiplier_1(self):
        broker = _mock_broker(equity=5000.0, multiplier=1)
        perms = fetch_permissions(broker)
        assert perms.margin_enabled is False

    def test_margin_enabled_with_high_equity_and_margin(self):
        broker = _mock_broker(equity=2500.0, multiplier=2)
        perms = fetch_permissions(broker)
        assert perms.margin_enabled is True
        assert perms.short_selling_enabled is True

    def test_short_requires_both_margin_and_equity(self):
        """Short selling requires BOTH margin enabled AND equity >= $2000."""
        broker = _mock_broker(equity=1500.0, multiplier=2)
        perms = fetch_permissions(broker)
        assert perms.short_selling_enabled is False


class TestAccountHealth:
    def test_healthy_active_account(self):
        broker = _mock_broker(status="ACTIVE", account_blocked=False, trading_blocked=False)
        perms = fetch_permissions(broker)
        assert perms.is_healthy is True

    def test_unhealthy_when_account_blocked(self):
        broker = _mock_broker(account_blocked=True)
        perms = fetch_permissions(broker)
        assert perms.is_healthy is False

    def test_unhealthy_when_trading_blocked(self):
        broker = _mock_broker(trading_blocked=True)
        perms = fetch_permissions(broker)
        assert perms.is_healthy is False

    def test_unhealthy_with_non_active_status(self):
        broker = _mock_broker(status="ACCOUNT_UPDATED")
        perms = fetch_permissions(broker)
        assert perms.is_healthy is False


class TestPaperFlag:
    def test_paper_flag_propagated(self):
        broker = _mock_broker(is_paper=True)
        perms = fetch_permissions(broker)
        assert perms.paper is True

    def test_live_flag_propagated(self):
        broker = _mock_broker(is_paper=False)
        perms = fetch_permissions(broker)
        assert perms.paper is False


class TestAccountIdMasking:
    """Verify summary() never emits the full account identifier."""

    def test_uuid_is_masked(self):
        """A full UUID-style account number should be masked to ****XXXX."""
        perms = AccountPermissions(
            account_number="d4b97f68-9a92-5fc8-8a7f-b654af62059a",
            account_status="ACTIVE",
            equity=59.96,
            buying_power=53.21,
        )
        s = perms.summary()
        assert "d4b97f68" not in s, "Full UUID prefix must not appear in summary"
        assert "b654af62059a" not in s, "Full UUID suffix must not appear in summary"
        assert "****059a" in s, "Masked form ****XXXX must appear"

    def test_short_account_number_redacted(self):
        """Account numbers <= 4 chars should show [REDACTED]."""
        perms = AccountPermissions(account_number="AB12")
        s = perms.summary()
        assert "AB12" not in s
        assert "[REDACTED]" in s

    def test_empty_account_number_redacted(self):
        """Empty account number should show [REDACTED]."""
        perms = AccountPermissions(account_number="")
        s = perms.summary()
        assert "[REDACTED]" in s

    def test_fetched_permissions_summary_is_masked(self):
        """Integration: fetch_permissions() → summary() must mask."""
        broker = _mock_broker(account_number="11111111-2222-3333-4444-555555555555")
        perms = fetch_permissions(broker)
        s = perms.summary()
        assert "11111111" not in s
        assert "****5555" in s

