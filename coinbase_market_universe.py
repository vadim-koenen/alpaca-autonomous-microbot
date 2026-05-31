"""
P2-012A — Coinbase Market Universe (read-only classification scaffold).

This module provides a safe, read-only way to ingest Coinbase product metadata
(List Products style payloads) and classify them without enabling any trading
for new or leveraged products.

Key guarantees in this patch:
- All newly discovered products default to allow_live_trading=False.
- GOLD-PERP, SILVER-PERP, XAU, XAG etc. are classified but explicitly not enabled.
- No order placement logic exists here.
- No network calls (callers must pass payloads or use the status script in offline mode).
- Preserves full raw product metadata for future inspection.

This is scaffolding for eventual universal coverage (spot, perps, commodity-linked)
once eligibility and broker facts are proven.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Iterable, List, Optional, Set

# Conservative classification taxonomy for P2-012A
PRODUCT_TYPE_SPOT_CRYPTO = "spot_crypto"
PRODUCT_TYPE_PERPETUAL_FUTURE = "perpetual_future"
PRODUCT_TYPE_EXPIRING_FUTURE = "expiring_future"
PRODUCT_TYPE_COMMODITY_LINKED_DERIVATIVE = "commodity_linked_derivative"
PRODUCT_TYPE_UNKNOWN = "unknown"

# Known commodity-linked product ID patterns (case-insensitive substring match)
COMMODITY_PATTERNS = {"gold", "silver", "xau", "xag", "crude", "oil", "natgas", "copper"}

# Product IDs we know from history are the current live set (do not auto-enable others).
# We store them with the common hyphen format used by Coinbase (BTC-USD).
CURRENT_LIVE_SYMBOLS: Set[str] = {"BTC-USD", "ETH-USD", "SOL-USD"}


@dataclass
class CoinbaseProduct:
    """Normalized view of a Coinbase product with classification and eligibility."""
    product_id: str
    base_currency: str
    quote_currency: str
    product_type: str
    is_trading_disabled: bool = False
    account_eligible: bool = True          # conservative default; real eligibility checked elsewhere
    product_enabled: bool = True
    min_order_size: Optional[float] = None
    price_increment: Optional[float] = None
    size_increment: Optional[float] = None
    leverage_allowed: bool = False
    max_leverage: Optional[float] = None

    # P2-012A: explicit safety flag — never True for newly discovered products in this patch
    allow_live_trading: bool = False

    # Ranking / scoring placeholders (populated by future analysis, not used for orders here)
    liquidity_score: Optional[float] = None
    spread_score: Optional[float] = None
    volatility_score: Optional[float] = None
    prediction_score: Optional[float] = None
    risk_score: Optional[float] = None

    # Raw payload preserved for audit / future feature extraction
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_gold_or_silver_like(self) -> bool:
        pid = self.product_id.upper()
        return any(p in pid for p in ["GOLD", "SILVER", "XAU", "XAG"])


class CoinbaseMarketUniverse:
    """
    In-memory universe of Coinbase products with conservative classification.

    Usage (offline / test):
        universe = CoinbaseMarketUniverse()
        universe.ingest_products(list_products_payload["products"])
        report = universe.summarize()
    """

    def __init__(self) -> None:
        self._products: Dict[str, CoinbaseProduct] = {}

    def ingest_products(self, raw_products: Iterable[Dict[str, Any]]) -> None:
        """Ingest a List Products-style payload (array of product objects)."""
        for raw in raw_products:
            product = self._normalize(raw)
            self._products[product.product_id] = product

    def _normalize(self, raw: Dict[str, Any]) -> CoinbaseProduct:
        product_id = raw.get("product_id") or raw.get("id") or "UNKNOWN"

        # Coinbase sometimes uses "product_type" or infers from contract specs
        raw_type = (raw.get("product_type") or raw.get("type") or "").lower()
        contract_type = (raw.get("contract_type") or "").lower()  # perpetual, expiring, etc.

        product_type = self._classify_product_type(product_id, raw_type, contract_type, raw)

        # Conservative eligibility extraction
        is_trading_disabled = bool(raw.get("trading_disabled", False))
        # Many payloads have "status": "online" / "offline"
        status = (raw.get("status") or "").lower()
        if status and status != "online":
            is_trading_disabled = True

        # Account eligibility is not known from public product list; default conservatively
        account_eligible = bool(raw.get("account_eligible", True))

        product_enabled = not is_trading_disabled and account_eligible

        # Size / price increments (various field names across payloads)
        min_order_size = self._safe_float(
            raw.get("min_order_size") or raw.get("base_min_size") or raw.get("min_size")
        )
        price_increment = self._safe_float(raw.get("price_increment") or raw.get("quote_increment"))
        size_increment = self._safe_float(raw.get("size_increment") or raw.get("base_increment"))

        # Leverage / margin fields (may be absent for spot)
        leverage_allowed = bool(raw.get("margin_enabled", False) or raw.get("leverage_enabled", False))
        max_leverage = self._safe_float(raw.get("max_leverage") or raw.get("max_margin_leverage"))

        # P2-012A safety: only the explicitly configured live symbols are allowed to trade
        # in the current controlled exploration. Everything else stays disabled.
        normalized_pid = product_id.replace("/", "-").upper()
        allow_live = normalized_pid in {s.upper() for s in CURRENT_LIVE_SYMBOLS}

        # If it looks like gold/silver, force allow_live=False even if it somehow matched CURRENT_LIVE
        if any(p in normalized_pid for p in ["GOLD", "SILVER", "XAU", "XAG"]):
            allow_live = False

        return CoinbaseProduct(
            product_id=product_id,
            base_currency=raw.get("base_currency") or raw.get("base_asset") or "",
            quote_currency=raw.get("quote_currency") or raw.get("quote_asset") or "",
            product_type=product_type,
            is_trading_disabled=is_trading_disabled,
            account_eligible=account_eligible,
            product_enabled=product_enabled,
            min_order_size=min_order_size,
            price_increment=price_increment,
            size_increment=size_increment,
            leverage_allowed=leverage_allowed,
            max_leverage=max_leverage,
            allow_live_trading=allow_live,
            raw=raw,
        )

    def _classify_product_type(
        self,
        product_id: str,
        raw_type: str,
        contract_type: str,
        raw: Dict[str, Any],
    ) -> str:
        pid = product_id.upper()

        # Commodity-linked detection (gold, silver, etc.)
        if any(p in pid for p in ["GOLD", "SILVER", "XAU", "XAG", "CRUDE", "OIL"]):
            if "perp" in pid or contract_type in ("perpetual", "perpetual_future"):
                return PRODUCT_TYPE_COMMODITY_LINKED_DERIVATIVE
            return PRODUCT_TYPE_COMMODITY_LINKED_DERIVATIVE

        # Perpetual futures / perps
        if "perp" in pid or contract_type in ("perpetual", "perpetual_future"):
            return PRODUCT_TYPE_PERPETUAL_FUTURE

        # Expiring / dated futures
        if "future" in raw_type or contract_type in ("future", "expiring_future", "dated_future"):
            return PRODUCT_TYPE_EXPIRING_FUTURE

        # Spot crypto (default for most Coinbase spot products)
        if "spot" in raw_type or (raw.get("base_currency") and raw.get("quote_currency")):
            # Classic spot pairs like BTC-USD
            if "-" in product_id and not any(x in pid for x in ["PERP", "FUTURE"]):
                return PRODUCT_TYPE_SPOT_CRYPTO

        return PRODUCT_TYPE_UNKNOWN

    @staticmethod
    def _safe_float(v: Any) -> Optional[float]:
        try:
            if v is None:
                return None
            return float(v)
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Query / reporting helpers (read-only)
    # ------------------------------------------------------------------

    def get_product(self, product_id: str) -> Optional[CoinbaseProduct]:
        return self._products.get(product_id)

    def list_products(self, product_type: Optional[str] = None) -> List[CoinbaseProduct]:
        prods = list(self._products.values())
        if product_type:
            prods = [p for p in prods if p.product_type == product_type]
        return sorted(prods, key=lambda p: p.product_id)

    def summarize(self) -> Dict[str, Any]:
        by_type: Dict[str, int] = {}
        gold_silver_like: List[str] = []
        tradable_count = 0

        for p in self._products.values():
            by_type[p.product_type] = by_type.get(p.product_type, 0) + 1
            if p.is_gold_or_silver_like:
                gold_silver_like.append(p.product_id)
            if p.allow_live_trading:
                tradable_count += 1

        return {
            "total_products": len(self._products),
            "by_type": by_type,
            "gold_silver_like": sorted(gold_silver_like),
            "tradable_under_current_policy": tradable_count,
            "note": "GOLD/SILVER-like products and all newly discovered products have allow_live_trading=False in this scaffold.",
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(
            {
                "products": [asdict(p) for p in self._products.values()],
                "summary": self.summarize(),
            },
            indent=indent,
            default=str,
        )

    # ------------------------------------------------------------------
    # P2-012B: conservative multi-asset spot candidate plumbing (read-only)
    # ------------------------------------------------------------------

    def get_spot_crypto_candidates(
        self,
        configured_symbols: Optional[Iterable[str]] = None,
        supported_quotes: Optional[Set[str]] = None,
    ) -> Dict[str, Any]:
        """
        Controlled multi-asset spot expansion candidate generator.

        - Starts from (or augments with) currently configured live symbols.
        - Filters ingested products to spot_crypto only.
        - Excludes: trading_disabled, non-enabled, unsupported quotes, any leverage,
          perps/futures, gold/silver/commodity-linked (by ID patterns).
        - All *newly discovered* candidates have allow_live_trading=False (policy only).
        - Placeholder ranking scores for future use (not used for orders).
        - Never enables trading; purely advisory/scaffolding for next intentional expansion.
        """
        if supported_quotes is None:
            supported_quotes = {"USD", "USDC", "USDT"}

        configured: Set[str] = {
            (s or "").replace("/", "-").upper() for s in (configured_symbols or [])
        }

        candidates: List[Dict[str, Any]] = []
        excluded: List[Dict[str, Any]] = []

        for p in self._products.values():
            pid = (p.product_id or "").replace("/", "-").upper()
            reason = None

            if p.product_type != PRODUCT_TYPE_SPOT_CRYPTO:
                reason = f"not_spot_crypto:{p.product_type}"
            elif p.is_trading_disabled or not p.product_enabled:
                reason = "trading_disabled_or_not_enabled"
            elif p.quote_currency.upper() not in {q.upper() for q in supported_quotes}:
                reason = f"unsupported_quote:{p.quote_currency}"
            elif p.leverage_allowed or (p.max_leverage and p.max_leverage > 1):
                reason = "leverage_or_margin_enabled"
            elif p.is_gold_or_silver_like or any(x in pid for x in ("PERP", "FUTURE", "FUT", "SWAP")):
                reason = "derivative_or_commodity_linked"
            elif "GOLD" in pid or "SILVER" in pid or "XAU" in pid or "XAG" in pid:
                reason = "gold_silver_like"

            if reason:
                excluded.append(
                    {
                        "product_id": p.product_id,
                        "base": p.base_currency,
                        "quote": p.quote_currency,
                        "product_type": p.product_type,
                        "reason": reason,
                        "allow_live_trading": p.allow_live_trading,
                    }
                )
                continue

            # placeholder scores (future: liquidity/spread/vol from real data)
            is_current_live = pid in configured or p.allow_live_trading
            liquidity = p.liquidity_score if p.liquidity_score is not None else (0.9 if is_current_live else 0.5)
            rec = {
                "product_id": p.product_id,
                "base_currency": p.base_currency,
                "quote_currency": p.quote_currency,
                "min_order_size": p.min_order_size,
                "price_increment": p.price_increment,
                "size_increment": p.size_increment,
                "allow_live_trading": p.allow_live_trading,  # False for anything not in CURRENT_LIVE
                "is_currently_configured_live": is_current_live,
                "liquidity_score": liquidity,
                "spread_score": p.spread_score if p.spread_score is not None else 0.6,
                "volatility_score": p.volatility_score if p.volatility_score is not None else 0.5,
                "prediction_score": p.prediction_score if p.prediction_score is not None else 0.0,
                "risk_score": p.risk_score if p.risk_score is not None else 0.25,
            }
            candidates.append(rec)

        # rank: prefer currently configured, then liquidity placeholder
        candidates.sort(key=lambda r: (-int(r["is_currently_configured_live"]), -r["liquidity_score"]))

        return {
            "candidates": candidates,
            "candidates_count": len(candidates),
            "excluded": excluded,
            "excluded_count": len(excluded),
            "excluded_reasons": sorted({e["reason"] for e in excluded}),
            "configured_live_symbols": sorted(configured),
            "total_products_considered": len(self._products),
            "note": (
                "P2-012B scaffolding only. "
                "Newly discovered spot assets are classified but have allow_live_trading=False. "
                "No live orders or notional changes for any new symbol. "
                "Explicit config + safety review required for expansion."
            ),
        }
