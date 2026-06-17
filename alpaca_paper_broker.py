#!/usr/bin/env python3
"""
alpaca_paper_broker.py — P2-046H: the bridge to REAL Alpaca PAPER execution.

Translates the engine's Orders into Alpaca paper-account market orders, and reads the paper
account back as the source of truth. This is the M4 step — graduation from simulated fills to
a real (fake-money) Alpaca paper account.

SAFETY / GOVERNANCE — read this:
- Uses DEDICATED PAPER KEYS ONLY (`ALPACA_PAPER_API_KEY` / `ALPACA_PAPER_SECRET_KEY`). It refuses
  to use the live trading keys (`ALPACA_API_KEY`) — so this can NEVER hit a live account.
- `paper_executor` only calls it when STOP_TRADING is absent AND `config.live_paper=True` AND a
  broker is supplied AND the operator approved. Dormant by default.
- The `trading_client` is dependency-injected, so this is fully unit-tested with a fake client and
  NEVER touches the network in tests. `from_env()` builds a real paper client on the Mac only.
- Keys load from `.env`, are never printed, never committed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from allocator_engine import BUY, Order

# Roots we trade as crypto on Alpaca (need "<ROOT>/USD" symbols + GTC). Our basket: BTC.
CRYPTO_ROOTS = {"BTC", "ETH", "SOL", "LTC", "DOGE", "AVAX", "LINK", "DOT", "MATIC", "ADA"}


def _to_alpaca_symbol(sym: str) -> str:
    """Map our config symbol to Alpaca's trading symbol. 'BTC' -> 'BTC/USD'; 'SPY' -> 'SPY'."""
    s = sym.upper()
    if "/" in s:
        return s
    return f"{s}/USD" if s in CRYPTO_ROOTS else s


def _from_alpaca_symbol(sym: str) -> str:
    """Map an Alpaca position symbol back to our root. 'BTC/USD'|'BTCUSD' -> 'BTC'; 'SPY' -> 'SPY'."""
    s = sym.upper().replace("/", "")
    if s.endswith("USD") and s[:-3] in CRYPTO_ROOTS:
        return s[:-3]
    return s


def _load_paper_keys(env_path: str = ".env") -> Dict[str, str]:
    """Read DEDICATED paper keys (never the live ALPACA_API_KEY). Raises a clear error if absent."""
    key = os.getenv("ALPACA_PAPER_API_KEY")
    secret = os.getenv("ALPACA_PAPER_SECRET_KEY")
    if (not key or not secret) and Path(env_path).exists():
        for line in Path(env_path).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k == "ALPACA_PAPER_API_KEY" and not key:
                key = v
            elif k == "ALPACA_PAPER_SECRET_KEY" and not secret:
                secret = v
    if not key or not secret:
        raise RuntimeError(
            "Paper keys not found. Generate PAPER keys at app.alpaca.markets (Paper Trading → "
            "API Keys) and add ALPACA_PAPER_API_KEY / ALPACA_PAPER_SECRET_KEY to .env. "
            "Your live ALPACA_API_KEY is intentionally NOT used for paper.")
    return {"key": key, "secret": secret}


class AlpacaPaperBroker:
    """Submits the plan's orders to an Alpaca PAPER account and reads it back. Client injected."""

    def __init__(self, trading_client: Any) -> None:
        self._client = trading_client

    @classmethod
    def from_env(cls) -> "AlpacaPaperBroker":
        """Build a real paper TradingClient from DEDICATED paper keys. Mac-only; not used in tests."""
        try:
            from alpaca.trading.client import TradingClient
        except ImportError as e:  # pragma: no cover - only on the Mac
            raise RuntimeError("alpaca-py not installed; pip install alpaca-py") from e
        keys = _load_paper_keys()
        client = TradingClient(keys["key"], keys["secret"], paper=True)  # ALWAYS paper
        return cls(client)

    def _build_request(self, order: Order) -> Any:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        symbol = _to_alpaca_symbol(order.symbol)
        side = OrderSide.BUY if order.side == BUY else OrderSide.SELL
        tif = TimeInForce.GTC if "/" in symbol else TimeInForce.DAY  # crypto GTC, equities DAY
        return MarketOrderRequest(symbol=symbol, notional=round(order.dollars, 2),
                                  side=side, time_in_force=tif)

    def submit_orders(self, orders: List[Order]) -> List[Dict[str, Any]]:
        fills: List[Dict[str, Any]] = []
        for o in orders:
            resp = self._client.submit_order(self._build_request(o))
            fills.append({
                "symbol": o.symbol, "side": o.side, "dollars": o.dollars,
                "order_id": str(getattr(resp, "id", "")) or None,
                "status": str(getattr(resp, "status", "submitted")),
            })
        return fills

    def account_snapshot(self) -> Dict[str, Any]:
        """Read the paper account as source of truth: cash, equity, and per-root holdings (units)."""
        acct = self._client.get_account()
        positions = self._client.get_all_positions()
        holdings: Dict[str, float] = {}
        for p in positions:
            root = _from_alpaca_symbol(str(getattr(p, "symbol", "")))
            holdings[root] = holdings.get(root, 0.0) + float(getattr(p, "qty", 0.0))
        return {
            "cash": float(getattr(acct, "cash", 0.0)),
            "equity": float(getattr(acct, "equity", 0.0)),
            "holdings": holdings,
        }
