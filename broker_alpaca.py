"""
broker_alpaca.py — Alpaca API wrapper.

Handles:
- Account queries
- Asset queries
- Order placement (respects dry_run/paper/live mode)
- Order cancellation
- Position queries
- Market status queries

NEVER logs API keys. NEVER exposes credentials.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    GetAssetsRequest,
    LimitOrderRequest,
    MarketOrderRequest,
    GetOrdersRequest,
    ClosePositionRequest,
)
from alpaca.trading.enums import (
    AssetClass,
    AssetStatus,
    OrderSide,
    OrderType,
    TimeInForce,
    QueryOrderStatus,
)
from alpaca.data.historical import CryptoHistoricalDataClient, StockHistoricalDataClient
from alpaca.data.requests import (
    CryptoBarsRequest,
    CryptoLatestQuoteRequest,
    StockLatestQuoteRequest,
    StockBarsRequest,
)
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

import socket

from utils import (
    build_client_order_id,
    get_alpaca_keys,
    get_cfg,
    get_mode,
    is_live_trading_enabled,
    is_paper,
)

logger = logging.getLogger("broker")

# Apply a global socket timeout so no Alpaca HTTP call can hang indefinitely.
# 30 seconds is generous enough for normal API latency while still preventing
# infinite hangs. First requests after a cold-start or network blip can be slow.
socket.setdefaulttimeout(30)


class BrokerAlpaca:
    """
    Thin wrapper around alpaca-py.
    All state-modifying calls (orders) are silently no-op in dry_run mode.
    """

    def __init__(self) -> None:
        api_key, secret_key = get_alpaca_keys()
        self.is_paper = is_paper()
        self._mode = get_mode()

        # Trading client
        self._client = TradingClient(
            api_key=api_key,
            secret_key=secret_key,
            paper=self.is_paper,
        )

        # Data clients
        self._crypto_data = CryptoHistoricalDataClient(
            api_key=api_key,
            secret_key=secret_key,
        )
        self._stock_data = StockHistoricalDataClient(
            api_key=api_key,
            secret_key=secret_key,
        )

        # Circuit breaker: set to True if Alpaca rejects crypto orders with
        # 40010001 ("crypto orders not allowed for account"). Once tripped,
        # all crypto orders are skipped for the session to avoid log spam.
        self._crypto_account_blocked: bool = False
        self.last_open_orders_error: str = ""

        logger.info(
            f"BrokerAlpaca initialised | mode={self._mode} | paper={self.is_paper} | "
            f"socket_timeout=30s"
        )

    # -----------------------------------------------------------------------
    # Account
    # -----------------------------------------------------------------------

    def get_account(self) -> Any:
        """Return raw alpaca-py Account object."""
        try:
            return self._client.get_account()
        except Exception as e:
            logger.error(f"get_account error: {e}")
            return None

    # -----------------------------------------------------------------------
    # Assets
    # -----------------------------------------------------------------------

    def get_asset(self, symbol: str) -> Any:
        """Return asset object or None."""
        try:
            return self._client.get_asset(symbol)
        except Exception as e:
            logger.warning(f"get_asset({symbol}) error: {e}")
            return None

    def is_tradable(self, symbol: str) -> bool:
        asset = self.get_asset(symbol)
        if asset is None:
            return False
        return bool(getattr(asset, "tradable", False))

    def is_fractionable(self, symbol: str) -> bool:
        asset = self.get_asset(symbol)
        if asset is None:
            return False
        return bool(getattr(asset, "fractionable", False))

    def is_shortable(self, symbol: str) -> bool:
        asset = self.get_asset(symbol)
        if asset is None:
            return False
        return bool(getattr(asset, "shortable", False)) and bool(
            getattr(asset, "easy_to_borrow", False)
        )

    # -----------------------------------------------------------------------
    # Market data
    # -----------------------------------------------------------------------

    def get_crypto_latest_quote(self, symbol: str) -> Any:
        """Return latest crypto quote or None."""
        try:
            # Alpaca crypto symbol format: BTC/USD
            req = CryptoLatestQuoteRequest(symbol_or_symbols=symbol)
            result = self._crypto_data.get_crypto_latest_quote(req)
            return result.get(symbol)
        except Exception as e:
            logger.warning(f"get_crypto_latest_quote({symbol}) error: {e}")
            return None

    def get_crypto_bars(
        self,
        symbol: str,
        timeframe: str = "5Min",
        limit: int = 50,
    ) -> Any:
        """Return list of bars or empty list.

        Always pass an explicit start time so the Alpaca API knows what window
        to return. Without start, some endpoints return 0 bars despite limit>0.
        Window = limit × bar_width × 2 (generous buffer for gaps / weekends).
        """
        try:
            tf = _parse_timeframe(timeframe)
            # Infer bar width in minutes from the timeframe string
            minutes_map = {
                "1Min": 1, "3Min": 3, "5Min": 5, "15Min": 15,
                "30Min": 30, "1Hour": 60, "4Hour": 240, "1Day": 1440,
            }
            bar_minutes = minutes_map.get(timeframe, 5)
            # Request a window 3× what we need so gaps and quiet periods don't
            # leave us short on bars.
            start = datetime.now(timezone.utc) - timedelta(
                minutes=bar_minutes * limit * 3
            )
            req = CryptoBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=tf,
                start=start,
                limit=limit,
            )
            bars = self._crypto_data.get_crypto_bars(req)
            # alpaca-py BarSet: `symbol in bars` uses __contains__ which iterates
            # attribute names, not symbol keys — always returns False even when data
            # exists. Use direct subscript access and catch missing key instead.
            try:
                result = list(bars[symbol])
            except (KeyError, TypeError):
                result = []
            logger.debug(f"get_crypto_bars({symbol}): {len(result)} bars returned")
            return result
        except Exception as e:
            logger.warning(f"get_crypto_bars({symbol}) error: {e}")
            return []

    def get_stock_latest_quote(self, symbol: str) -> Any:
        try:
            req = StockLatestQuoteRequest(symbol_or_symbols=symbol)
            result = self._stock_data.get_stock_latest_quote(req)
            return result.get(symbol)
        except Exception as e:
            logger.warning(f"get_stock_latest_quote({symbol}) error: {e}")
            return None

    def get_stock_bars(
        self,
        symbol: str,
        timeframe: str = "5Min",
        limit: int = 50,
    ) -> Any:
        try:
            tf = _parse_timeframe(timeframe)
            req = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=tf,
                limit=limit,
            )
            bars = self._stock_data.get_stock_bars(req)
            return bars[symbol] if symbol in bars else []
        except Exception as e:
            logger.warning(f"get_stock_bars({symbol}) error: {e}")
            return []

    # -----------------------------------------------------------------------
    # Positions
    # -----------------------------------------------------------------------

    def get_all_positions(self) -> list[Any]:
        try:
            return self._client.get_all_positions()
        except Exception as e:
            logger.error(f"get_all_positions error: {e}")
            return []

    def get_position(self, symbol: str) -> Any:
        try:
            return self._client.get_open_position(symbol)
        except Exception as e:
            return None

    def close_position(self, symbol: str) -> Any:
        """Close position at market. Respects dry_run."""
        if self._mode == "dry_run":
            logger.info(f"DRY_RUN: would close position {symbol}")
            return None
        try:
            return self._client.close_position(symbol)
        except Exception as e:
            logger.error(f"close_position({symbol}) error: {e}")
            return None

    def close_all_positions(self) -> None:
        """Emergency: close everything."""
        if self._mode == "dry_run":
            logger.info("DRY_RUN: would close all positions")
            return
        try:
            self._client.close_all_positions(cancel_orders=True)
            logger.warning("CLOSE ALL POSITIONS executed")
        except Exception as e:
            logger.error(f"close_all_positions error: {e}")

    # -----------------------------------------------------------------------
    # Orders
    # -----------------------------------------------------------------------

    def get_open_orders(self) -> list[Any]:
        try:
            req = GetOrdersRequest(status=QueryOrderStatus.OPEN)
            orders = self._client.get_orders(req)
            self.last_open_orders_error = ""
            return orders
        except Exception as e:
            self.last_open_orders_error = str(e)
            logger.error(f"get_open_orders error: {e}")
            return []

    def cancel_order(self, order_id: str) -> bool:
        if self._mode == "dry_run":
            logger.info(f"DRY_RUN: would cancel order {order_id}")
            return True
        try:
            self._client.cancel_order_by_id(order_id)
            return True
        except Exception as e:
            logger.error(f"cancel_order({order_id}) error: {e}")
            return False

    def place_limit_order(
        self,
        *,
        symbol: str,
        side: str,           # "buy" or "sell"
        qty: float,
        limit_price: float,
        time_in_force: str = "gtc",
        asset_class: str = "crypto",
        client_order_id: Optional[str] = None,
    ) -> Optional[Any]:
        """
        Place a limit order. Returns order object or None.
        No-op in dry_run mode.
        """
        client_order_id = client_order_id or build_client_order_id(
            broker="alpaca",
            strategy="direct",
            symbol=symbol,
            side=side,
            purpose="order",
        )
        if self._mode == "dry_run":
            logger.info(
                f"DRY_RUN: limit {side.upper()} {qty} {symbol} @ {limit_price} "
                f"client_order_id={client_order_id}"
            )
            return _DryRunOrder(
                symbol=symbol,
                side=side,
                qty=qty,
                limit_price=limit_price,
                client_order_id=client_order_id,
            )

        if not self._can_place_live():
            logger.error("Live trading not enabled — order blocked")
            return None

        # Circuit breaker: if Alpaca has already told us crypto is not allowed
        # for this account, stop trying immediately instead of spamming errors.
        if self._crypto_account_blocked and asset_class == "crypto":
            logger.warning(
                f"CRYPTO BLOCKED (40010001): skipping {side} {symbol} — "
                "crypto agreement not active on this account. "
                "Sign the agreement at app.alpaca.markets or contact support@alpaca.markets."
            )
            return None

        try:
            order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
            tif = _parse_tif(time_in_force)
            req = LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=order_side,
                time_in_force=tif,
                limit_price=round(limit_price, 8),
                client_order_id=client_order_id,
            )
            order = self._client.submit_order(req)
            logger.info(
                f"ORDER PLACED: broker_order_id={order.id} "
                f"client_order_id={client_order_id} | "
                f"{side} {qty} {symbol} limit={limit_price}"
            )
            return order
        except Exception as e:
            err_str = str(e)
            if "40010001" in err_str or "crypto orders not allowed" in err_str.lower():
                self._crypto_account_blocked = True
                logger.critical(
                    f"CRYPTO ACCOUNT BLOCKED: Alpaca rejected {symbol} with 40010001 "
                    "'crypto orders not allowed for account'. "
                    "Circuit breaker tripped — no further crypto orders this session. "
                    "Fix: sign the crypto agreement at app.alpaca.markets or email support@alpaca.markets."
                )
            else:
                logger.error(f"place_limit_order({symbol}) error: {e}")
            return None

    def place_market_order(
        self,
        *,
        symbol: str,
        side: str,
        notional: Optional[float] = None,
        qty: Optional[float] = None,
        time_in_force: str = "gtc",
        client_order_id: Optional[str] = None,
    ) -> Optional[Any]:
        """
        Place a market order by notional or qty. Returns order or None.
        Only used when config explicitly allows market orders.
        """
        client_order_id = client_order_id or build_client_order_id(
            broker="alpaca",
            strategy="direct",
            symbol=symbol,
            side=side,
            purpose="order",
        )
        if self._mode == "dry_run":
            logger.info(
                f"DRY_RUN: market {side.upper()} {symbol} notional={notional} "
                f"qty={qty} client_order_id={client_order_id}"
            )
            return _DryRunOrder(
                symbol=symbol,
                side=side,
                qty=qty or 0,
                notional=notional,
                client_order_id=client_order_id,
            )

        if not self._can_place_live():
            logger.error("Live trading not enabled — market order blocked")
            return None

        if self._crypto_account_blocked:
            logger.warning(
                f"CRYPTO BLOCKED (40010001): skipping market {side} {symbol} — "
                "crypto agreement not active on this account."
            )
            return None

        try:
            order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
            tif = _parse_tif(time_in_force)
            if notional is not None:
                req = MarketOrderRequest(
                    symbol=symbol,
                    notional=round(notional, 2),
                    side=order_side,
                    time_in_force=tif,
                    client_order_id=client_order_id,
                )
            else:
                req = MarketOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=order_side,
                    time_in_force=tif,
                    client_order_id=client_order_id,
                )
            order = self._client.submit_order(req)
            logger.info(
                f"MARKET ORDER PLACED: broker_order_id={order.id} "
                f"client_order_id={client_order_id} | {side} {symbol}"
            )
            return order
        except Exception as e:
            logger.error(f"place_market_order({symbol}) error: {e}")
            return None

    # -----------------------------------------------------------------------
    # Internal
    # -----------------------------------------------------------------------

    def _can_place_live(self) -> bool:
        """Double-check live mode gates before any order submission."""
        if self._mode == "dry_run":
            return False
        if self._mode == "live":
            if not is_live_trading_enabled():
                logger.critical("LIVE_TRADING env var is not true — blocking order")
                return False
            cfg_live = get_cfg("live_trading", "enabled")
            if not cfg_live:
                logger.critical("live_trading.enabled is false in config — blocking order")
                return False
        return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_timeframe(tf_str: str) -> TimeFrame:
    """Parse '5Min', '1Hour', '1Day' etc. to TimeFrame."""
    tf_map = {
        "1Min": TimeFrame(1, TimeFrameUnit.Minute),
        "3Min": TimeFrame(3, TimeFrameUnit.Minute),
        "5Min": TimeFrame(5, TimeFrameUnit.Minute),
        "15Min": TimeFrame(15, TimeFrameUnit.Minute),
        "30Min": TimeFrame(30, TimeFrameUnit.Minute),
        "1Hour": TimeFrame(1, TimeFrameUnit.Hour),
        "4Hour": TimeFrame(4, TimeFrameUnit.Hour),
        "1Day": TimeFrame(1, TimeFrameUnit.Day),
    }
    return tf_map.get(tf_str, TimeFrame(5, TimeFrameUnit.Minute))


def _parse_tif(tif_str: str) -> TimeInForce:
    tif_map = {
        "gtc": TimeInForce.GTC,
        "ioc": TimeInForce.IOC,
        "day": TimeInForce.DAY,
        "fok": TimeInForce.FOK,
        "opg": TimeInForce.OPG,
        "cls": TimeInForce.CLS,
    }
    return tif_map.get(tif_str.lower(), TimeInForce.GTC)


class _DryRunOrder:
    """Mimics an order object for dry_run mode so callers don't crash."""
    def __init__(self, symbol: str, side: str, qty: float,
                 limit_price: float = 0.0, notional: Optional[float] = None,
                 client_order_id: Optional[str] = None):
        import uuid
        self.id = f"DRY-{uuid.uuid4().hex[:8]}"
        self.client_order_id = client_order_id or self.id
        self.symbol = symbol
        self.side = side
        self.qty = qty
        self.limit_price = limit_price
        self.notional = notional
        self.status = "dry_run_simulated"
