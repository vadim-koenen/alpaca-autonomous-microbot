"""
strategy_options.py — Long-only options strategy module.

GATED: This module only produces live proposals if:
  1. Alpaca confirms options approval (level >= 1)
  2. config options.live_enabled = true
  3. config live_trading.allow_long_options = true
  4. The premium fits within the account's max_premium_per_trade_usd

Allowed strategies: long_call, long_put
Disallowed: everything else (naked short, undefined-risk spreads, etc.)

With a ~$10 account, options are almost certainly not viable live.
This module is built for correctness, not immediate live use.
"""

from __future__ import annotations

import logging
from typing import Optional

from risk_manager import TradeProposal
from utils import get_cfg

logger = logging.getLogger("strategy.options")


class OptionsStrategy:
    def __init__(self, market_data, broker) -> None:
        self._md = market_data
        self._broker = broker

    def generate_proposals(self, symbol: str, permissions) -> list[TradeProposal]:
        """
        Generate options proposals only if account is approved and config permits.
        Returns empty list otherwise (silent fail-closed, not a crash).
        """
        # Permission gate — fail closed
        if not permissions.options_enabled:
            logger.debug(f"Options skipped for {symbol}: broker options approval required")
            return []

        if permissions.options_level < 1:
            logger.debug(f"Options skipped for {symbol}: options_level={permissions.options_level} < 1")
            return []

        if not get_cfg("options", "live_enabled", default=False):
            logger.debug(f"Options skipped for {symbol}: options.live_enabled is false")
            return []

        max_premium = get_cfg("options", "max_premium_per_trade_usd", default=5.0)
        if permissions.equity < max_premium * 2:
            logger.debug(
                f"Options skipped for {symbol}: equity ${permissions.equity:.2f} "
                f"too low for options premium ${max_premium:.2f}"
            )
            return []

        # Module is built but live signals require further implementation
        # when options chain data is accessible via Alpaca options API.
        # For now: return empty — clean skip, not a crash.
        logger.debug(
            f"Options module active but no live signal generated for {symbol}. "
            "Options chain scanning not yet implemented for this account size."
        )
        return []

    def validate_strategy(self, strategy_name: str) -> bool:
        """Confirm strategy is in the allowed list and not in the disallowed list."""
        allowed = get_cfg("options", "allowed_live_strategies", default=[])
        disallowed = get_cfg("options", "disallowed_strategies", default=[])
        if strategy_name in disallowed:
            logger.warning(f"Options strategy '{strategy_name}' is explicitly disallowed")
            return False
        if strategy_name not in allowed:
            logger.warning(f"Options strategy '{strategy_name}' not in allowed list")
            return False
        return True

    def max_loss_known(self, proposal: TradeProposal) -> bool:
        """
        For long options: max loss = premium paid. Always known.
        For any undefined-risk strategy: return False to block it.
        """
        if proposal.options_strategy in ("long_call", "long_put"):
            return True  # max loss = notional (premium)
        # All other strategies have undefined or complex loss profiles
        logger.warning(
            f"Cannot confirm max loss for options strategy '{proposal.options_strategy}' — rejecting"
        )
        return False
