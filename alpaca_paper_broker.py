#!/usr/bin/env python3
"""
alpaca_paper_broker.py — P2-046H: the bridge to REAL Alpaca PAPER execution (dormant/gated).

Translates the engine's Orders into Alpaca paper-account market orders. This is the M4 step
("paper reproduces the offline result") — the graduation from simulated fills to a real (but
fake-money) Alpaca paper account.

SAFETY / GOVERNANCE — read this:
- This adapter is DORMANT by default. `paper_executor` only calls it when ALL hold: STOP_TRADING
  absent AND `config.live_paper=True` AND an explicit operator approval AND a broker instance is
  supplied. None of those are set in the repo, so nothing here runs unattended.
- It targets the Alpaca **paper** endpoint (`paper=True`) — fake money — never a live account.
- The `trading_client` is dependency-injected so this is fully unit-tested with a fake client and
  NEVER touches the network in tests. `from_env()` builds a real paper client on the operator's Mac
  only when they choose to enable it.
- Keys load from `.env`, are never printed, never committed.
"""

from __future__ import annotations

from typing import Any, Dict, List

from allocator_engine import BUY, Order


class AlpacaPaperBroker:
    """Submits the plan's orders to an Alpaca PAPER account. Client is injected."""

    def __init__(self, trading_client: Any) -> None:
        self._client = trading_client

    @classmethod
    def from_env(cls) -> "AlpacaPaperBroker":
        """Build a real paper TradingClient from env/.env keys. Mac-only; not used in tests."""
        import os

        from fetch_alpaca_bars import load_keys  # reuse existing env/.env loader (never prints)
        try:
            from alpaca.trading.client import TradingClient
        except ImportError as e:  # pragma: no cover - only on the Mac
            raise RuntimeError("alpaca-py not installed; pip install alpaca-py") from e

        key, secret = load_keys()
        client = TradingClient(key, secret, paper=True)  # ALWAYS paper here
        return cls(client)

    def _build_request(self, order: Order) -> Any:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        side = OrderSide.BUY if order.side == BUY else OrderSide.SELL
        # crypto symbols (BTC/USD) need GTC; equities use DAY
        tif = TimeInForce.GTC if "/" in order.symbol else TimeInForce.DAY
        return MarketOrderRequest(symbol=order.symbol, notional=round(order.dollars, 2),
                                  side=side, time_in_force=tif)

    def submit_orders(self, orders: List[Order]) -> List[Dict[str, Any]]:
        """Submit each order to the paper account. Returns fill summaries."""
        fills: List[Dict[str, Any]] = []
        for o in orders:
            req = self._build_request(o)
            resp = self._client.submit_order(req)
            fills.append({
                "symbol": o.symbol, "side": o.side, "dollars": o.dollars,
                "order_id": getattr(resp, "id", None),
                "status": str(getattr(resp, "status", "submitted")),
            })
        return fills
