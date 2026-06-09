"""
permissions.py — Account permissions gate.

Queries Alpaca once at startup and constructs a canonical permissions snapshot.
All missing or ambiguous fields fail CLOSED (no trade, log the reason).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("permissions")


@dataclass
class AccountPermissions:
    equity: float = 0.0
    buying_power: float = 0.0
    cash: float = 0.0
    paper: bool = True                     # are we on the paper endpoint?
    crypto_enabled: bool = False
    crypto_status: str = "UNKNOWN"         # Alpaca crypto_status: ACTIVE / INACTIVE / SUBMISSION_FAILED
    options_enabled: bool = False
    options_level: int = 0                 # 1=long only, 2=spreads, 3=naked (never use)
    margin_enabled: bool = False
    short_selling_enabled: bool = False
    pdt_restricted: bool = False           # pattern day trader flag
    pdt_trades_remaining: Optional[int] = None
    account_blocked: bool = True           # fail-closed default
    trading_blocked: bool = True
    transfers_blocked: bool = False
    account_number: str = ""
    account_status: str = "UNKNOWN"
    currency: str = "USD"
    raw: dict = field(default_factory=dict)  # full raw API response

    @property
    def is_healthy(self) -> bool:
        """Returns True only if the account is definitely tradeable."""
        return (
            not self.account_blocked
            and not self.trading_blocked
            and self.account_status in ("ACTIVE",)
            and self.equity > 0
        )

    def summary(self) -> str:
        # Mask account number — never emit full ID in logs
        if self.account_number and len(self.account_number) > 4:
            masked = "****" + self.account_number[-4:]
        else:
            masked = "[REDACTED]"
        return (
            f"Account: {masked} | status={self.account_status} | "
            f"equity=${self.equity:.2f} | bp=${self.buying_power:.2f} | "
            f"paper={self.paper} | crypto={self.crypto_enabled}(status={self.crypto_status}) | "
            f"options={self.options_enabled}(L{self.options_level}) | "
            f"margin={self.margin_enabled} | short={self.short_selling_enabled} | "
            f"blocked={self.account_blocked}/{self.trading_blocked}"
        )


def fetch_permissions(broker) -> AccountPermissions:
    """
    Query Alpaca and build an AccountPermissions snapshot.
    `broker` is the BrokerAlpaca instance from broker_alpaca.py.

    Fails closed on any missing/ambiguous data.
    """
    perms = AccountPermissions()

    try:
        account = broker.get_account()
        if account is None:
            logger.error("PERMISSIONS: get_account() returned None — failing closed")
            return perms

        raw = {}
        # alpaca-py returns an Account object; extract attrs safely
        def _get(attr: str, default: Any = None) -> Any:
            val = getattr(account, attr, default)
            raw[attr] = str(val) if val is not None else None
            return val

        perms.raw = raw
        perms.equity = float(_get("equity") or 0)
        perms.buying_power = float(_get("buying_power") or 0)
        perms.cash = float(_get("cash") or 0)
        perms.account_number = str(_get("account_number") or "")
        perms.currency = str(_get("currency") or "USD")

        # Account status — fail closed unless explicitly ACTIVE
        # Alpaca SDK returns an enum whose str() is e.g. "ACCOUNTSTATUS.ACTIVE"
        # Normalize to just the value portion after the last dot.
        raw_status = str(_get("status") or "UNKNOWN").upper()
        status = raw_status.split(".")[-1]  # "ACCOUNTSTATUS.ACTIVE" → "ACTIVE"
        perms.account_status = status

        # Blocked flags — fail closed (True = blocked = no trade)
        perms.account_blocked = bool(_get("account_blocked") or False)
        perms.trading_blocked = bool(_get("trading_blocked") or False)
        perms.transfers_blocked = bool(_get("transfers_blocked") or False)

        # Paper flag
        perms.paper = broker.is_paper

        # PDT
        pdt = _get("pattern_day_trader")
        perms.pdt_restricted = bool(pdt or False)
        daytrades_remaining = _get("daytrade_count")
        if daytrades_remaining is not None:
            try:
                perms.pdt_trades_remaining = int(daytrades_remaining)
            except (TypeError, ValueError):
                perms.pdt_trades_remaining = None

        # Crypto: two-part check.
        # 1) crypto_status on the account must be ACTIVE (agreement signed).
        # 2) BTC/USD asset must be tradable on this endpoint.
        # Checking only asset tradability is insufficient — it returns True even
        # when the account hasn't signed the crypto agreement, causing 40010001.
        try:
            raw_crypto_status = str(_get("crypto_status") or "UNKNOWN").upper()
            perms.crypto_status = raw_crypto_status.split(".")[-1]  # strip enum prefix
        except Exception:
            perms.crypto_status = "UNKNOWN"

        try:
            asset = broker.get_asset("BTC/USD")
            asset_tradable = asset is not None and bool(getattr(asset, "tradable", False))
        except Exception:
            asset_tradable = False

        if perms.crypto_status == "ACTIVE" and asset_tradable:
            perms.crypto_enabled = True
        else:
            perms.crypto_enabled = False
            if perms.crypto_status != "ACTIVE":
                logger.warning(
                    f"PERMISSIONS: crypto_status={perms.crypto_status} (not ACTIVE) — "
                    "crypto trading disabled. Sign the crypto agreement in the Alpaca dashboard."
                )
            elif not asset_tradable:
                logger.warning("PERMISSIONS: BTC/USD not tradable on this endpoint — crypto disabled")

        # Options: check account's options_approved_level
        try:
            options_level = _get("options_approved_level")
            if options_level is not None:
                level = int(options_level)
                perms.options_level = level
                perms.options_enabled = level >= 1
            else:
                perms.options_level = 0
                perms.options_enabled = False
        except (TypeError, ValueError):
            perms.options_level = 0
            perms.options_enabled = False

        # Margin: Alpaca requires $2000 equity; field is 'multiplier'
        try:
            multiplier = float(_get("multiplier") or 1)
            # If multiplier > 1 AND equity >= 2000, margin is available
            perms.margin_enabled = multiplier > 1 and perms.equity >= 2000.0
        except (TypeError, ValueError):
            perms.margin_enabled = False

        # Short selling: requires margin enabled and equity >= 2000
        perms.short_selling_enabled = perms.margin_enabled and perms.equity >= 2000.0

        logger.info(f"PERMISSIONS: {perms.summary()}")
        return perms

    except Exception as e:
        logger.error(f"PERMISSIONS: fatal error fetching account — failing closed: {e}")
        return AccountPermissions()  # all defaults = blocked/disabled
