#!/usr/bin/env python3
"""
alpaca_live_broker.py — P2-046J: REAL-MONEY Alpaca live broker (heavily gated).

Same order/snapshot logic as the paper broker, bound to the LIVE account (real money) using the
live keys (`ALPACA_API_KEY/SECRET`, paper=False). This is ONLY reachable through
`paper_executor.execute_plan(mode="live", ...)`, which itself requires multiple explicit gates
(config.live_trading_enabled, confirm_live token, a per-contribution dollar cap, no
runtime/ACCUMULATOR_STOP). Nothing here runs unattended; the operator triggers it deliberately.

GOVERNANCE: real money. Default OFF. Keys from `.env`, never printed, never committed.
"""

from __future__ import annotations

from alpaca_paper_broker import AlpacaBrokerBase, _read_keys


class AlpacaLiveBroker(AlpacaBrokerBase):
    """Binds the broker to the LIVE account (REAL money). Use only behind execute_plan's gates."""

    is_paper = False

    @classmethod
    def from_env(cls) -> "AlpacaLiveBroker":
        try:
            from alpaca.trading.client import TradingClient
        except ImportError as e:  # pragma: no cover - only on the Mac
            raise RuntimeError("alpaca-py not installed; pip install alpaca-py") from e
        keys = _read_keys("ALPACA_API_KEY", "ALPACA_SECRET_KEY")  # the LIVE keys
        client = TradingClient(keys["key"], keys["secret"], paper=False)  # REAL money
        return cls(client)
