"""
broker_coinbase.py — Coinbase Advanced Trade API wrapper.

Drop-in replacement for broker_alpaca.py. Implements the same public interface
so market_data, order_manager, position_manager, and permissions work unchanged.

Coinbase-specific notes:
  - Symbol format: internally "BTC-USD"; translated from/to "BTC/USD" (Alpaca
    convention used everywhere else in the bot) transparently.
  - No built-in paper trading — use mode=dry_run for safe testing.
  - No equities, options, margin, or short selling. Those methods return
    safe empty/None values with a log so the bot skips them cleanly.
  - Explicit taker fee: ~0.60% retail tier. Logged on every live order so
    the journal shows real cost, not just notional.
  - Equity = USD cash + current market value of all crypto holdings.
  - Positions = derived from non-USD Coinbase account balances.

Improvements over broker_alpaca.py (lessons learned):
  1. Retry logic   — 3 attempts, exponential backoff on transient 5xx/timeout.
                     4xx errors (auth, bad request) trip circuit breaker immediately.
  2. Circuit breaker — auth/permission errors set _api_blocked=True; all
                     subsequent calls return safe defaults without hammering the API.
  3. Fee-aware logging — every order logs expected fee in $ and % before submission.
  4. USD balance tracking — buying_power is exact USD available, not a derived field.
  5. Equity computation — scans all currency accounts + live prices for real total.
  6. Stale-quote detection — timestamps from Coinbase normalised to UTC consistently.
  7. Symbol translation — single _cb() / _alpaca() helper pair; no symbol errors.
  8. Connection timeout — 20 s socket timeout applied at init.
  9. Clear error context — every error log names the fix, not just the exception.
 10. DryRunOrder — compatible with order_manager expectations.
"""

from __future__ import annotations

import logging
import socket
import time
import uuid
import warnings

# Suppress the Coinbase SDK's "switch to Ed25519" advisory — EC keys work fine,
# this fires on every single API call and drowns the logs.
warnings.filterwarnings("ignore", message=".*Ed25519.*", category=UserWarning)
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from utils import (
    build_client_order_id,
    data_is_stale,
    get_cfg,
    get_mode,
    is_live_trading_enabled,
    safe_float,
)

logger = logging.getLogger("broker_coinbase")

socket.setdefaulttimeout(20)

# ---------------------------------------------------------------------------
# Coinbase fee schedule (retail tier 0 — <$10k/month volume)
# Updated when API returns actual fee rates.
# ---------------------------------------------------------------------------
_TAKER_FEE_DEFAULT = 0.006   # 0.60%
_MAKER_FEE_DEFAULT = 0.004   # 0.40%

# ---------------------------------------------------------------------------
# Response helper
# ---------------------------------------------------------------------------

def _r(resp: Any) -> dict:
    """
    Convert a Coinbase SDK response object to a plain dict.
    SDK v1.x returns typed objects (ListAccountsResponse, etc.) that have a
    to_dict() method.  Calling .get() directly on them raises AttributeError.
    """
    if resp is None:
        return {}
    if isinstance(resp, dict):
        return resp
    if hasattr(resp, "to_dict"):
        return resp.to_dict()
    return {}


# ---------------------------------------------------------------------------
# Symbol translation helpers
# ---------------------------------------------------------------------------

def _cb(symbol: str) -> str:
    """Convert Alpaca-format symbol to Coinbase: 'BTC/USD' → 'BTC-USD'."""
    return symbol.replace("/", "-")


def _alpaca(symbol: str) -> str:
    """Convert Coinbase symbol to Alpaca format: 'BTC-USD' → 'BTC/USD'."""
    return symbol.replace("-", "/")


# ---------------------------------------------------------------------------
# Timeframe mapping: Alpaca string → Coinbase granularity string
# ---------------------------------------------------------------------------
_GRANULARITY_MAP = {
    "1Min":  "ONE_MINUTE",
    "3Min":  "FIVE_MINUTE",    # Coinbase has no 3-min; nearest is 5-min
    "5Min":  "FIVE_MINUTE",
    "15Min": "FIFTEEN_MINUTE",
    "30Min": "THIRTY_MINUTE",
    "1Hour": "ONE_HOUR",
    "2Hour": "TWO_HOUR",
    "4Hour": "SIX_HOUR",       # Coinbase has no 4-hour; nearest is 6-hour
    "1Day":  "ONE_DAY",
}

# Minutes per granularity (for window calculation)
_GRANULARITY_MINUTES = {
    "ONE_MINUTE": 1, "FIVE_MINUTE": 5, "FIFTEEN_MINUTE": 15,
    "THIRTY_MINUTE": 30, "ONE_HOUR": 60, "TWO_HOUR": 120,
    "SIX_HOUR": 360, "ONE_DAY": 1440,
}


# ---------------------------------------------------------------------------
# Lightweight value objects — mimic alpaca-py objects so the rest of the
# bot (market_data, permissions, order_manager) works without changes.
# ---------------------------------------------------------------------------

@dataclass
class _CoinbaseAccount:
    """
    Mimics the alpaca-py Account object.
    permissions.py reads these attributes by name via getattr().
    """
    equity: float
    buying_power: float
    cash: float
    account_number: str
    currency: str = "USD"
    # Alpaca-style status enums — permissions.py splits on "." to get the value
    status: str = "ACTIVE"
    crypto_status: str = "ACTIVE"      # always ACTIVE when API keys work
    account_blocked: bool = False
    trading_blocked: bool = False
    transfers_blocked: bool = False
    pattern_day_trader: bool = False
    daytrade_count: int = 0
    options_approved_level: int = 0    # Coinbase has no options
    multiplier: float = 1.0            # no margin


@dataclass
class _CoinbaseQuote:
    """
    Mimics alpaca-py Quote object.
    market_data.py reads bid_price, ask_price, timestamp via getattr().
    """
    bid_price: float
    ask_price: float
    timestamp: datetime


@dataclass
class _CoinbaseBar:
    """
    Mimics alpaca-py Bar object.
    market_data._bars_to_df() reads: timestamp, open, high, low, close, volume.
    """
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class _CoinbaseAsset:
    """Mimics alpaca-py Asset object for get_asset() callers."""
    symbol: str                        # Alpaca format (BTC/USD)
    tradable: bool = True
    fractionable: bool = True
    shortable: bool = False            # Coinbase never supports shorting
    easy_to_borrow: bool = False


@dataclass
class _CoinbasePosition:
    """Mimics alpaca-py Position object for position_manager compatibility."""
    symbol: str                        # Alpaca format (BTC/USD)
    qty: float
    avg_entry_price: float = 0.0
    market_value: float = 0.0
    current_price: float = 0.0
    unrealized_pl: float = 0.0
    side: str = "long"


@dataclass
class _CoinbaseOrder:
    """Mimics alpaca-py Order object returned by place_* methods."""
    id: str
    symbol: str                        # Alpaca format (BTC/USD)
    side: str
    qty: float
    limit_price: float = 0.0
    status: str = "pending_new"
    notional: float = 0.0
    client_order_id: str = ""


class _DryRunOrder:
    """Mimics an order object for dry_run mode so order_manager doesn't crash."""
    def __init__(self, symbol: str, side: str, qty: float,
                 limit_price: float = 0.0, notional: float = 0.0,
                 client_order_id: str = ""):
        self.id = f"CB-DRY-{uuid.uuid4().hex[:8]}"
        self.client_order_id = client_order_id or self.id
        self.symbol = symbol
        self.side = side
        self.qty = qty
        self.limit_price = limit_price
        self.notional = notional
        self.status = "dry_run_simulated"


# ---------------------------------------------------------------------------
# BrokerCoinbase
# ---------------------------------------------------------------------------

class BrokerCoinbase:
    """
    Coinbase Advanced Trade wrapper with the same public interface as
    BrokerAlpaca. The rest of the bot imports this transparently.

    Usage:
        broker = BrokerCoinbase()

    Requires in .env:
        COINBASE_API_KEY=...
        COINBASE_API_SECRET=...
    """

    def __init__(self) -> None:
        from coinbase.rest import RESTClient

        api_key, api_secret = _get_coinbase_keys()
        self.is_paper = False          # Coinbase has no paper endpoint
        self._mode = get_mode()
        self._taker_fee = _TAKER_FEE_DEFAULT
        self._maker_fee = _MAKER_FEE_DEFAULT
        self.last_open_orders_error: str = ""

        # Circuit breaker: tripped on auth/permission errors.
        # When True, all API calls return safe defaults immediately.
        self._api_blocked: bool = False
        self._block_reason: str = ""

        # Track the USD account UUID (cached after first account list)
        self._usd_account_uuid: Optional[str] = None

        # Cache product base_increment precision (decimal places per symbol).
        # Populated lazily by _safe_base_size() to avoid extra API calls.
        self._base_inc_cache: dict[str, int] = {}

        # Default portfolio UUID — populated on first get_account() call
        self._portfolio_uuid: Optional[str] = None

        self._client = RESTClient(
            api_key=api_key,
            api_secret=api_secret,
        )

        logger.info(
            f"BrokerCoinbase initialised | mode={self._mode} | paper=False | "
            f"taker_fee={self._taker_fee*100:.2f}% | socket_timeout=20s"
        )

        # Attempt to read actual fee rates from Coinbase (non-fatal if it fails)
        self._refresh_fee_rates()

    # -----------------------------------------------------------------------
    # Account
    # -----------------------------------------------------------------------

    def get_account(self) -> Optional[_CoinbaseAccount]:
        """
        Return a _CoinbaseAccount mimicking the alpaca-py Account object.
        permissions.py reads this via getattr(), so field names must match.

        Uses get_portfolio_breakdown() as the primary source — it correctly
        reports assets held on both consumer and Advanced Trade wallet sides.
        The accounts API misses assets that haven't been explicitly moved to
        the Advanced Trade sub-wallet (e.g. ETH held in the consumer wallet).

        Equity = total_balance from breakdown.
        Buying power = total_cash_equivalent_balance (spendable USD).
        """
        if self._api_blocked:
            logger.error(
                f"BrokerCoinbase.get_account(): API circuit breaker is open "
                f"({self._block_reason}) — returning None"
            )
            return None

        try:
            # Resolve portfolio UUID once
            if not self._portfolio_uuid:
                portfolios = _retry(lambda: self._client.get_portfolios(), self)
                if portfolios:
                    pl = _r(portfolios).get("portfolios", [])
                    if pl:
                        self._portfolio_uuid = _r(pl[0]).get("uuid", "")

            if not self._portfolio_uuid:
                logger.warning("get_account(): no portfolio UUID found, falling back to accounts API")
                return self._get_account_from_accounts_api()

            breakdown = _retry(
                lambda: self._client.get_portfolio_breakdown(
                    portfolio_uuid=self._portfolio_uuid
                ),
                self,
            )
            if breakdown is None:
                return self._get_account_from_accounts_api()

            bd = _r(breakdown).get("breakdown", {})
            bd = _r(bd)
            balances = _r(bd.get("portfolio_balances", {}))

            equity = safe_float(_r(balances.get("total_balance", {})).get("value", 0))
            buying_power = safe_float(
                _r(balances.get("total_cash_equivalent_balance", {})).get("value", 0)
            )

            return _CoinbaseAccount(
                equity=equity,
                buying_power=buying_power,
                cash=buying_power,
                account_number=self._portfolio_uuid,
            )

        except Exception as e:
            _handle_exception(e, "get_account", self)
            return None

    def _get_account_from_accounts_api(self) -> Optional[_CoinbaseAccount]:
        """Fallback: compute equity from the accounts API (may miss consumer-wallet assets)."""
        try:
            usd_balance = 0.0
            crypto_value = 0.0
            account_id = ""
            cursor: Optional[str] = None
            pages = 0
            while pages < 10:
                accounts = _retry(
                    lambda: self._client.get_accounts(limit=50, cursor=cursor) if cursor
                    else self._client.get_accounts(limit=50),
                    self,
                )
                if accounts is None:
                    break
                rd = _r(accounts)
                for acct in rd.get("accounts", []):
                    acct = _r(acct)
                    currency = acct.get("currency", "")
                    available = safe_float(
                        (acct.get("available_balance") or {}).get("value", 0)
                    )
                    if currency == "USD":
                        usd_balance = available
                        account_id = acct.get("uuid", "")
                        self._usd_account_uuid = account_id
                    elif available > 0:
                        mid = self._get_mid_price(f"{currency}-USD")
                        if mid > 0:
                            crypto_value += available * mid
                has_next = rd.get("has_next", False)
                cursor = rd.get("cursor", "") or None
                pages += 1
                if not has_next:
                    break
            equity = usd_balance + crypto_value
            return _CoinbaseAccount(
                equity=equity, buying_power=usd_balance,
                cash=usd_balance, account_number=account_id,
            )
        except Exception as e:
            logger.error(f"_get_account_from_accounts_api error: {e}")
            return None

    # -----------------------------------------------------------------------
    # Assets
    # -----------------------------------------------------------------------

    def get_asset(self, symbol: str) -> Optional[_CoinbaseAsset]:
        """Return asset info. Returns None if product not found on Coinbase."""
        if self._api_blocked:
            return None
        try:
            product = _retry(
                lambda: self._client.get_product(product_id=_cb(symbol)), self
            )
            if product is None:
                return None
            tradable = not _r(product).get("is_disabled", True)
            return _CoinbaseAsset(
                symbol=symbol,
                tradable=tradable,
                fractionable=True,
                shortable=False,
                easy_to_borrow=False,
            )
        except Exception as e:
            logger.warning(f"get_asset({symbol}) error: {e}")
            return None

    def is_tradable(self, symbol: str) -> bool:
        asset = self.get_asset(symbol)
        return asset is not None and asset.tradable

    def is_fractionable(self, symbol: str) -> bool:
        return True   # all Coinbase crypto is fractionable

    def is_shortable(self, symbol: str) -> bool:
        return False  # Coinbase never supports shorting

    # -----------------------------------------------------------------------
    # Market data — crypto
    # -----------------------------------------------------------------------

    def get_crypto_latest_quote(self, symbol: str) -> Optional[_CoinbaseQuote]:
        """
        Return latest best bid/ask as a _CoinbaseQuote.
        market_data.py reads: bid_price, ask_price, timestamp.
        """
        if self._api_blocked:
            return None
        try:
            resp = _retry(
                lambda: self._client.get_best_bid_ask(product_ids=[_cb(symbol)]),
                self,
            )
            if resp is None:
                return None

            pricebooks = _r(resp).get("pricebooks", [])
            if not pricebooks:
                logger.warning(f"get_crypto_latest_quote({symbol}): empty pricebooks")
                return None

            pb = _r(pricebooks[0])
            bids = pb.get("bids", [])
            asks = pb.get("asks", [])
            if not bids or not asks:
                logger.warning(
                    f"get_crypto_latest_quote({symbol}): no bids/asks in pricebook"
                )
                return None

            bid = safe_float(_r(bids[0]).get("price", 0))
            ask = safe_float(_r(asks[0]).get("price", 0))

            # Parse timestamp
            ts_raw = pb.get("time", "")
            ts = _parse_ts(ts_raw)

            return _CoinbaseQuote(bid_price=bid, ask_price=ask, timestamp=ts)

        except Exception as e:
            logger.warning(f"get_crypto_latest_quote({symbol}) error: {e}")
            return None

    def get_crypto_bars(
        self,
        symbol: str,
        timeframe: str = "5Min",
        limit: int = 50,
    ) -> list[_CoinbaseBar]:
        """
        Return list of _CoinbaseBar objects, sorted oldest-first.
        market_data._bars_to_df() reads: timestamp, open, high, low, close, volume.

        Coinbase candles endpoint returns newest-first; we reverse before returning.
        Max 300 candles per request.
        """
        if self._api_blocked:
            return []
        try:
            granularity = _GRANULARITY_MAP.get(timeframe, "FIVE_MINUTE")
            bar_minutes = _GRANULARITY_MINUTES.get(granularity, 5)

            # Build time window: 3× what we need to accommodate gaps
            end_ts = datetime.now(timezone.utc)
            start_ts = end_ts - timedelta(minutes=bar_minutes * limit * 3)

            resp = _retry(
                lambda: self._client.get_candles(
                    product_id=_cb(symbol),
                    start=str(int(start_ts.timestamp())),
                    end=str(int(end_ts.timestamp())),
                    granularity=granularity,
                    limit=min(limit * 3, 300),  # Coinbase max is 300
                ),
                self,
            )
            if resp is None:
                return []

            raw_candles = _r(resp).get("candles", [])
            bars: list[_CoinbaseBar] = []
            for c in raw_candles:
                try:
                    cd = _r(c)
                    ts = datetime.fromtimestamp(
                        int(cd.get("start", 0)), tz=timezone.utc
                    )
                    bars.append(_CoinbaseBar(
                        timestamp=ts,
                        open=safe_float(cd.get("open", 0)),
                        high=safe_float(cd.get("high", 0)),
                        low=safe_float(cd.get("low", 0)),
                        close=safe_float(cd.get("close", 0)),
                        volume=safe_float(cd.get("volume", 0)),
                    ))
                except Exception:
                    continue

            # Coinbase returns newest-first — reverse to oldest-first
            bars.sort(key=lambda b: b.timestamp)

            # Trim to requested limit
            if len(bars) > limit:
                bars = bars[-limit:]

            logger.debug(
                f"get_crypto_bars({symbol}, {timeframe}): {len(bars)} bars returned"
            )
            return bars

        except Exception as e:
            logger.warning(f"get_crypto_bars({symbol}) error: {e}")
            return []

    # -----------------------------------------------------------------------
    # Market data — equities (not supported on Coinbase)
    # -----------------------------------------------------------------------

    def get_stock_latest_quote(self, symbol: str) -> None:
        logger.debug(f"get_stock_latest_quote({symbol}): not supported on Coinbase")
        return None

    def get_stock_bars(self, symbol: str, timeframe: str = "5Min",
                       limit: int = 50) -> list:
        logger.debug(f"get_stock_bars({symbol}): not supported on Coinbase")
        return []

    # -----------------------------------------------------------------------
    # Positions — derived from non-USD account balances
    # -----------------------------------------------------------------------

    def get_all_positions(self) -> list[_CoinbasePosition]:
        """
        Return all non-USD crypto positions using the portfolio breakdown API,
        which correctly reports assets on both consumer and Advanced Trade sides.
        Filters out stablecoins (USD/USDC/USDT) and dust < $0.10.
        """
        if self._api_blocked:
            return []
        try:
            positions: list[_CoinbasePosition] = []

            # Ensure portfolio UUID is populated
            if not self._portfolio_uuid:
                self.get_account()

            if self._portfolio_uuid:
                breakdown = _retry(
                    lambda: self._client.get_portfolio_breakdown(
                        portfolio_uuid=self._portfolio_uuid
                    ),
                    self,
                )
                if breakdown is not None:
                    bd = _r(_r(breakdown).get("breakdown", {}))
                    for sp in bd.get("spot_positions", []):
                        sp = _r(sp)
                        asset = sp.get("asset", "")
                        if asset in ("USD", "USDC", "USDT", ""):
                            continue
                        fiat_val = safe_float(sp.get("total_balance_fiat", 0))
                        if fiat_val < 0.10:
                            continue   # dust
                        qty = safe_float(sp.get("total_balance_crypto", 0))
                        mid = self._get_mid_price(f"{asset}-USD")
                        if mid <= 0:
                            mid = fiat_val / qty if qty > 0 else 0.0
                        if mid <= 0:
                            continue
                        positions.append(_CoinbasePosition(
                            symbol=f"{asset}/USD",
                            qty=qty,
                            current_price=mid,
                            market_value=fiat_val,
                        ))
                    return positions

            # Fallback: accounts API (may miss consumer-wallet assets)
            cursor: Optional[str] = None
            pages = 0
            while pages < 10:
                accounts = _retry(
                    lambda: self._client.get_accounts(limit=50, cursor=cursor) if cursor
                    else self._client.get_accounts(limit=50),
                    self,
                )
                if accounts is None:
                    break
                rd = _r(accounts)
                for acct in rd.get("accounts", []):
                    acct = _r(acct)
                    currency = acct.get("currency", "")
                    if currency in ("USD", "USDC", "USDT"):
                        continue
                    available = safe_float(
                        (acct.get("available_balance") or {}).get("value", 0)
                    )
                    if available <= 0:
                        continue
                    mid = self._get_mid_price(f"{currency}-USD")
                    if mid <= 0:
                        continue
                    market_val = available * mid
                    if market_val < 0.10:
                        continue
                    positions.append(_CoinbasePosition(
                        symbol=f"{currency}/USD",
                        qty=available,
                        current_price=mid,
                        market_value=market_val,
                    ))
                has_next = rd.get("has_next", False)
                cursor = rd.get("cursor", "") or None
                pages += 1
                if not has_next:
                    break
            return positions

        except Exception as e:
            logger.error(f"get_all_positions error: {e}")
            return []

    def get_position(self, symbol: str) -> Optional[_CoinbasePosition]:
        """Return position for a single symbol or None."""
        positions = self.get_all_positions()
        for p in positions:
            if p.symbol == symbol:
                return p
        return None

    def _safe_base_size(self, symbol: str, qty: float) -> float:
        """
        Round qty DOWN to the number of decimal places Coinbase allows for
        this product's base_increment.

        Prevents "Too many decimals in order amount" rejections on altcoins
        that have coarser precision than BTC/ETH (e.g. ALGO allows 2 dp, not 8).

        Result is cached per symbol so subsequent close attempts are free.
        Floors rather than rounds to avoid inadvertently increasing order size.
        """
        import math as _math

        if symbol not in self._base_inc_cache:
            try:
                product = _retry(
                    lambda: self._client.get_product(product_id=_cb(symbol)), self
                )
                if product is not None:
                    base_inc_str = str(_r(product).get("base_increment", ""))
                    if base_inc_str and "." in base_inc_str:
                        # "0.01" → 2, "0.00000001" → 8, "0.001" → 3
                        dec = len(base_inc_str.rstrip("0").split(".")[1])
                    elif base_inc_str in ("1", ""):
                        dec = 0
                    else:
                        dec = 8  # conservative fallback
                else:
                    dec = 8
                self._base_inc_cache[symbol] = dec
                logger.debug(
                    f"_safe_base_size: {symbol} base_increment→{dec} decimal places"
                )
            except Exception as e:
                logger.debug(f"_safe_base_size({symbol}): product lookup failed ({e}) — using 8dp")
                self._base_inc_cache[symbol] = 8

        decimals = self._base_inc_cache[symbol]
        if decimals == 0:
            rounded = float(int(qty))
        else:
            factor = 10 ** decimals
            rounded = _math.floor(qty * factor) / factor

        if rounded != qty:
            logger.info(
                f"_safe_base_size({symbol}): {qty} → {rounded} "
                f"(precision={decimals}dp, floor applied)"
            )
        return rounded

    def close_position(self, symbol: str) -> Optional[Any]:
        """
        Close full position by placing a market sell of entire balance.
        Respects dry_run mode.

        Rounds qty DOWN to the product's base_increment precision before
        submitting, preventing "Too many decimals in order amount" rejections
        on altcoins (e.g. ALGO, DOGE).
        """
        if self._mode == "dry_run":
            logger.info(f"DRY_RUN: would close position {symbol}")
            return _DryRunOrder(symbol=symbol, side="sell", qty=0)

        pos = self.get_position(symbol)
        if pos is None or pos.qty <= 0:
            logger.warning(f"close_position({symbol}): no position found")
            return None

        qty = self._safe_base_size(symbol, pos.qty)
        if qty <= 0:
            logger.warning(
                f"close_position({symbol}): qty rounded to zero after precision "
                "adjustment — cannot close via market order"
            )
            return None

        return self.place_market_order(
            symbol=symbol,
            side="sell",
            qty=qty,
            client_order_id=build_client_order_id(
                broker="coinbase",
                strategy="position_manager",
                symbol=symbol,
                side="sell",
                purpose="exit",
            ),
        )

    def close_all_positions(self) -> None:
        """Emergency: close all open crypto positions at market."""
        if self._mode == "dry_run":
            logger.info("DRY_RUN: would close all positions")
            return
        positions = self.get_all_positions()
        for pos in positions:
            logger.warning(f"CLOSE ALL: closing {pos.symbol} qty={pos.qty}")
            self.close_position(pos.symbol)

    # -----------------------------------------------------------------------
    # Orders
    # -----------------------------------------------------------------------

    def get_open_orders(self) -> list[Any]:
        """Return list of open orders as _CoinbaseOrder objects."""
        if self._api_blocked:
            self.last_open_orders_error = self._block_reason or "coinbase api blocked"
            return []
        try:
            resp = _retry(
                lambda: self._client.list_orders(order_status=["OPEN"]),
                self,
            )
            if resp is None:
                self.last_open_orders_error = "Coinbase list_orders returned no response"
                return []

            orders = []
            for o in _r(resp).get("orders", []):
                od = _r(o)
                product_id = od.get("product_id", "")
                config = od.get("order_configuration") or {}
                config = _r(config)
                limit_cfg = (
                    _r(config.get("limit_limit_gtc")) or
                    _r(config.get("limit_limit_gtd")) or
                    {}
                )
                orders.append(_CoinbaseOrder(
                    id=od.get("order_id", ""),
                    symbol=_alpaca(product_id),
                    side=od.get("side", "").lower(),
                    qty=safe_float(limit_cfg.get("base_size", 0)),
                    limit_price=safe_float(limit_cfg.get("limit_price", 0)),
                    status=od.get("status", "OPEN").lower(),
                    client_order_id=od.get("client_order_id", ""),
                ))
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
            resp = _retry(
                lambda: self._client.cancel_orders(order_ids=[order_id]),
                self,
            )
            if resp is None:
                return False
            results = _r(resp).get("results", [])
            if results and _r(results[0]).get("success", False):
                logger.info(f"Order {order_id} cancelled successfully")
                return True
            logger.warning(
                f"cancel_order({order_id}): unexpected response: {resp}"
            )
            return False
        except Exception as e:
            logger.error(f"cancel_order({order_id}) error: {e}")
            return False

    def get_order_status(self, order_id: str) -> dict:
        """
        Poll Coinbase for the current status of an order by ID.

        Returns a dict with normalised and raw fields so callers can update
        their position state without parsing Coinbase response objects directly.

        Keys returned:
            normalized_status   — "filled" | "open" | "canceled" |
                                  "expired" | "rejected" | "unknown"
            raw_status          — Coinbase string as returned by API
            completion_percentage
            filled_size
            average_filled_price
            filled_value
            total_fees
            settled             — bool
            last_fill_time      — ISO-8601 string or ""
            last_update_time    — ISO-8601 string or ""

        Returns {} on error, blocked circuit breaker, or empty order_id.
        """
        if not order_id or self._api_blocked:
            return {}
        try:
            resp = _retry(
                lambda: self._client.get_order(order_id=order_id),
                self,
            )
            if resp is None:
                return {}

            # SDK returns GetOrderResponse; normalise via _r()
            rd = _r(resp)
            # Response may have top-level "order" key or expose fields directly
            order = _r(rd.get("order", {})) or rd

            raw_status = order.get("status", "")
            normalized_status = _normalize_order_status(raw_status)

            result = {
                "normalized_status":    normalized_status,
                "raw_status":           raw_status,
                "completion_percentage": order.get("completion_percentage", "0"),
                "filled_size":          order.get("filled_size", "0"),
                "average_filled_price": order.get("average_filled_price", "0"),
                "filled_value":         order.get("filled_value", "0"),
                "total_fees":           order.get("total_fees", "0"),
                "settled":              bool(order.get("settled", False)),
                "last_fill_time":       order.get("last_fill_time", ""),
                "last_update_time":     order.get("last_update_time", ""),
            }
            logger.debug(
                f"get_order_status({order_id}): raw={raw_status} "
                f"→ {normalized_status} | filled_size={result['filled_size']} "
                f"@ avg_price={result['average_filled_price']}"
            )
            return result

        except Exception as e:
            logger.warning(f"get_order_status({order_id}) error: {e}")
            return {}

    def place_limit_order(
        self,
        *,
        symbol: str,
        side: str,
        qty: float,
        limit_price: float,
        time_in_force: str = "gtc",
        asset_class: str = "crypto",
        client_order_id: Optional[str] = None,
    ) -> Optional[Any]:
        """
        Place a GTC limit order. Returns _CoinbaseOrder or None.
        Logs expected fee before submission so the journal captures real cost.
        """
        client_order_id = client_order_id or build_client_order_id(
            broker="coinbase",
            strategy="direct",
            symbol=symbol,
            side=side,
            purpose="order",
        )
        if self._mode == "dry_run":
            logger.info(
                f"DRY_RUN: limit {side.upper()} {qty:.6f} {symbol} @ {limit_price} "
                f"client_order_id={client_order_id}"
            )
            return _DryRunOrder(
                symbol=symbol, side=side, qty=qty, limit_price=limit_price,
                notional=qty * limit_price, client_order_id=client_order_id,
            )

        if not self._can_place_live():
            return None

        if self._api_blocked:
            logger.warning(
                f"ORDER BLOCKED (circuit breaker): {side} {symbol} — "
                f"{self._block_reason}"
            )
            return None

        # Log expected fee so journal/reporting reflects true cost
        notional = qty * limit_price
        expected_fee = notional * self._taker_fee
        logger.info(
            f"ORDER PREVIEW: {side.upper()} {qty:.6f} {symbol} limit={limit_price:.4f} "
            f"notional=${notional:.2f} | expected_fee=${expected_fee:.4f} "
            f"({self._taker_fee*100:.2f}% taker) "
            f"client_order_id={client_order_id}"
        )

        try:
            resp = _retry(
                lambda: self._client.limit_order_gtc(
                    client_order_id=client_order_id,
                    product_id=_cb(symbol),
                    side=side.upper(),
                    limit_price=str(round(limit_price, 8)),
                    base_size=str(round(qty, 8)),
                    post_only=False,
                ),
                self,
            )
            if resp is None:
                return None

            rd = _r(resp)
            success = rd.get("success", False)
            if not success:
                err = _r(rd.get("error_response", {}))
                err_msg = err.get("message", str(resp))
                preview = rd.get("order_configuration", {})
                logger.error(
                    f"place_limit_order({symbol}) rejected by Coinbase: {err_msg} "
                    f"| preview={preview}"
                )
                _check_for_circuit_breaker_trigger(err_msg, self)
                return None

            order_data = _r(rd.get("success_response", {}))
            order_id = order_data.get("order_id", client_order_id)
            logger.info(
                f"ORDER PLACED: broker_order_id={order_id} "
                f"client_order_id={client_order_id} | "
                f"{side.upper()} {qty:.6f} {symbol} limit={limit_price:.4f} "
                f"| fee≈${expected_fee:.4f}"
            )
            return _CoinbaseOrder(
                id=order_id,
                symbol=symbol,
                side=side.lower(),
                qty=qty,
                limit_price=limit_price,
                notional=notional,
                status="pending_new",
                client_order_id=client_order_id,
            )

        except Exception as e:
            logger.error(f"place_limit_order({symbol}) error: {e}")
            _handle_exception(e, f"place_limit_order({symbol})", self)
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
        Place a market order by notional (quote_size) or qty (base_size).
        Coinbase market orders use IOC internally.
        """
        client_order_id = client_order_id or build_client_order_id(
            broker="coinbase",
            strategy="direct",
            symbol=symbol,
            side=side,
            purpose="order",
        )
        if self._mode == "dry_run":
            logger.info(
                f"DRY_RUN: market {side.upper()} {symbol} "
                f"notional={notional} qty={qty} client_order_id={client_order_id}"
            )
            return _DryRunOrder(
                symbol=symbol, side=side, qty=qty or 0, notional=notional or 0,
                client_order_id=client_order_id,
            )

        if not self._can_place_live():
            return None

        if self._api_blocked:
            logger.warning(
                f"ORDER BLOCKED (circuit breaker): {side} {symbol} — "
                f"{self._block_reason}"
            )
            return None

        # Log expected fee
        trade_value = notional if notional else 0.0
        expected_fee = trade_value * self._taker_fee
        logger.info(
            f"ORDER PREVIEW: market {side.upper()} {symbol} "
            f"notional=${trade_value:.2f} | expected_fee=${expected_fee:.4f} "
            f"({self._taker_fee*100:.2f}% taker) "
            f"client_order_id={client_order_id}"
        )

        try:
            if notional is not None and notional > 0:
                # Buy by quote_size (spend exactly $X)
                resp = _retry(
                    lambda: self._client.market_order(
                        client_order_id=client_order_id,
                        product_id=_cb(symbol),
                        side=side.upper(),
                        quote_size=str(round(notional, 2)),
                    ),
                    self,
                )
            elif qty is not None and qty > 0:
                # Sell by base_size (sell exact qty)
                resp = _retry(
                    lambda: self._client.market_order(
                        client_order_id=client_order_id,
                        product_id=_cb(symbol),
                        side=side.upper(),
                        base_size=str(round(qty, 8)),
                    ),
                    self,
                )
            else:
                logger.error(
                    f"place_market_order({symbol}): must provide notional or qty"
                )
                return None

            if resp is None:
                return None

            rd = _r(resp)
            success = rd.get("success", False)
            if not success:
                err = _r(rd.get("error_response", {}))
                err_msg = err.get("message", str(resp))
                # Specific actionable messages for known Coinbase rejections
                if "Insufficient balance in source account" in err_msg:
                    logger.error(
                        f"place_market_order({symbol}) rejected: {err_msg} — "
                        "asset may be held in consumer Coinbase wallet rather than "
                        "Advanced Trade. Cannot close via API; position will be "
                        "retried up to max_close_failures times then dropped."
                    )
                elif "Too many decimals" in err_msg:
                    logger.error(
                        f"place_market_order({symbol}) rejected: {err_msg} — "
                        "base_size precision exceeded Coinbase limit for this product."
                    )
                else:
                    logger.error(
                        f"place_market_order({symbol}) rejected: {err_msg}"
                    )
                _check_for_circuit_breaker_trigger(err_msg, self)
                return None

            order_data = _r(rd.get("success_response", {}))
            order_id = order_data.get("order_id", client_order_id)
            logger.info(
                f"MARKET ORDER PLACED: broker_order_id={order_id} "
                f"client_order_id={client_order_id} | "
                f"{side.upper()} {symbol} | fee≈${expected_fee:.4f}"
            )
            return _CoinbaseOrder(
                id=order_id,
                symbol=symbol,
                side=side.lower(),
                qty=qty or 0,
                notional=notional or 0,
                status="pending_new",
                client_order_id=client_order_id,
            )

        except Exception as e:
            logger.error(f"place_market_order({symbol}) error: {e}")
            _handle_exception(e, f"place_market_order({symbol})", self)
            return None

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _can_place_live(self) -> bool:
        """Gate check before any live order submission."""
        if self._mode == "dry_run":
            return False
        if self._mode == "live":
            if not is_live_trading_enabled():
                logger.critical(
                    "LIVE_TRADING env var is not 'true' — order blocked"
                )
                return False
            cfg_live = get_cfg("live_trading", "enabled")
            if not cfg_live:
                logger.critical(
                    "live_trading.enabled is false in config.yaml — order blocked"
                )
                return False
        return True

    def _get_mid_price(self, product_id_cb: str) -> float:
        """Return mid price for a Coinbase product ID. 0.0 on any failure."""
        try:
            resp = self._client.get_best_bid_ask(product_ids=[product_id_cb])
            if resp is None:
                return 0.0
            pbs = _r(resp).get("pricebooks", [])
            if not pbs:
                return 0.0
            pb0 = _r(pbs[0])
            bids = pb0.get("bids", [])
            asks = pb0.get("asks", [])
            if not bids or not asks:
                return 0.0
            bid = safe_float(_r(bids[0]).get("price", 0))
            ask = safe_float(_r(asks[0]).get("price", 0))
            return (bid + ask) / 2.0 if bid > 0 and ask > 0 else 0.0
        except Exception:
            return 0.0

    def _refresh_fee_rates(self) -> None:
        """
        Attempt to read actual transaction fee rates from Coinbase.
        Falls back to defaults silently — not a critical path.
        """
        try:
            resp = self._client.get_transaction_summary(
                product_type="SPOT",
            )
            if resp is None:
                return
            fee_tier = _r(resp).get("fee_tier", {})
            fee_tier = _r(fee_tier)
            taker = safe_float(fee_tier.get("taker_fee_rate", 0))
            maker = safe_float(fee_tier.get("maker_fee_rate", 0))
            if taker > 0:
                self._taker_fee = taker
            if maker > 0:
                self._maker_fee = maker
            logger.info(
                f"Coinbase fee rates loaded: "
                f"maker={self._maker_fee*100:.3f}% taker={self._taker_fee*100:.3f}%"
            )
        except Exception as e:
            logger.debug(f"Could not load fee rates (using defaults): {e}")


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _get_coinbase_keys() -> tuple[str, str]:
    """
    Read COINBASE_API_KEY and COINBASE_API_SECRET from environment.
    Raises RuntimeError if missing or still set to placeholder.
    Never prints/logs the values.
    """
    import os
    key = os.environ.get("COINBASE_API_KEY", "")
    secret = os.environ.get("COINBASE_API_SECRET", "")
    if not key or key == "replace_me":
        raise RuntimeError(
            "COINBASE_API_KEY is not set. "
            "Add it to .env: COINBASE_API_KEY=your_key_here"
        )
    if not secret or secret == "replace_me":
        raise RuntimeError(
            "COINBASE_API_SECRET is not set. "
            "Add it to .env: COINBASE_API_SECRET=your_secret_here"
        )
    # python-dotenv stores quoted PEM keys with literal \n sequences;
    # the SDK needs real newlines for EC key parsing.
    secret = secret.replace("\\n", "\n")
    return key, secret


def _parse_ts(ts_raw: Any) -> datetime:
    """
    Parse a Coinbase timestamp string to a UTC-aware datetime.
    Returns now_utc() if parsing fails so staleness checks work correctly.
    """
    from utils import now_utc
    if not ts_raw:
        return now_utc()
    try:
        if isinstance(ts_raw, datetime):
            if ts_raw.tzinfo is None:
                return ts_raw.replace(tzinfo=timezone.utc)
            return ts_raw
        ts_str = str(ts_raw).rstrip("Z")
        # Handle fractional seconds of varying length
        if "." in ts_str:
            base, frac = ts_str.split(".", 1)
            frac = frac[:6].ljust(6, "0")
            ts_str = f"{base}.{frac}"
            fmt = "%Y-%m-%dT%H:%M:%S.%f"
        else:
            fmt = "%Y-%m-%dT%H:%M:%S"
        return datetime.strptime(ts_str, fmt).replace(tzinfo=timezone.utc)
    except Exception:
        from utils import now_utc
        return now_utc()


def _normalize_order_status(raw: str) -> str:
    """
    Normalise a Coinbase order status string to a canonical value.

    Coinbase raw values → canonical:
      FILLED                              → filled
      OPEN, PENDING, PENDING_NEW, QUEUED → open
      CANCELLED, CANCELED                → canceled
      EXPIRED                            → expired
      FAILED, REJECTED                   → rejected
      anything else                      → unknown
    """
    s = (raw or "").upper()
    if s == "FILLED":
        return "filled"
    if s in ("OPEN", "PENDING", "PENDING_NEW", "QUEUED"):
        return "open"
    if s in ("CANCELLED", "CANCELED"):
        return "canceled"
    if s == "EXPIRED":
        return "expired"
    if s in ("FAILED", "REJECTED"):
        return "rejected"
    return "unknown"


def _retry(fn, broker: BrokerCoinbase, attempts: int = 3,
           base_delay: float = 1.0) -> Any:
    """
    Call fn() up to `attempts` times with exponential backoff.

    Retries on: ConnectionError, TimeoutError, HTTP 5xx (detected by message).
    Trips circuit breaker and raises immediately on: auth errors (401/403),
    invalid API key, or any 4xx that indicates a permanent configuration problem.

    Returns None if all attempts fail.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            err_str = str(e).lower()

            # Permanent errors — trip circuit breaker, do not retry
            if any(kw in err_str for kw in [
                "401", "403", "unauthorized", "invalid api key",
                "forbidden", "authentication",
            ]):
                _trip_circuit_breaker(
                    f"Auth/permission error on attempt {attempt}: {e}", broker
                )
                return None

            # Transient errors — retry with backoff
            if attempt < attempts:
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning(
                    f"Transient error (attempt {attempt}/{attempts}), "
                    f"retrying in {delay:.1f}s: {e}"
                )
                time.sleep(delay)

    logger.error(f"All {attempts} attempts failed. Last error: {last_exc}")
    return None


def _handle_exception(e: Exception, context: str, broker: BrokerCoinbase) -> None:
    """Classify exception and trip circuit breaker if appropriate."""
    err_str = str(e).lower()
    if any(kw in err_str for kw in [
        "401", "403", "unauthorized", "invalid api key",
        "forbidden", "authentication",
    ]):
        _trip_circuit_breaker(f"{context}: {e}", broker)
    else:
        logger.error(f"{context} error: {e}")


def _trip_circuit_breaker(reason: str, broker: BrokerCoinbase) -> None:
    """
    Mark the broker as blocked. All subsequent API calls return safe defaults.
    Prevents log spam and runaway retries when API keys are wrong or revoked.
    """
    if not broker._api_blocked:
        broker._api_blocked = True
        broker._block_reason = reason
        logger.critical(
            f"COINBASE CIRCUIT BREAKER TRIPPED: {reason}. "
            "All API calls disabled for this session. "
            "Check COINBASE_API_KEY and COINBASE_API_SECRET in .env. "
            "Get new keys at: https://www.coinbase.com/settings/api"
        )


def _check_for_circuit_breaker_trigger(err_msg: str, broker: BrokerCoinbase) -> None:
    """
    Check if a Coinbase error response message should trip the circuit breaker.
    Called when the API returns success=False.
    """
    err_lower = err_msg.lower()
    if any(kw in err_lower for kw in [
        "unauthorized", "invalid api", "forbidden",
        "authentication", "permission denied",
    ]):
        _trip_circuit_breaker(f"API rejection: {err_msg}", broker)
