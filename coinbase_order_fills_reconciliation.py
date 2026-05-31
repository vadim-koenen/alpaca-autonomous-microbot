"""
P2-011F — Coinbase Order + Historical Fills Reconciliation (pure helper only).

This module provides a pure, side-effect-free reconciliation function
for combining an order status payload with a historical fills list.

It is intended **only** for proof and future capture seam evaluation.
It must never be imported or called from live trading paths, position_manager,
journal, runtime, or launchd code in this patch.

All functions are pure. No file I/O, no logging of fills, no P/L estimation
in the output (diagnostics only, clearly marked).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class FieldClassification:
    value: Any
    classification: str  # "direct_broker_fact" | "locally_derived" | "unavailable" | "unsafe_estimate"
    notes: str = ""


@dataclass
class ReconciliationResult:
    account_mode: str
    leg_type: str  # "entry" or "exit"
    product_id: Optional[str]
    side: Optional[str]
    order_id: Optional[str]
    order_status: Optional[str]
    filled_size: FieldClassification
    average_filled_price: FieldClassification
    total_fees: FieldClassification
    filled_value: FieldClassification
    sells_proceeds: FieldClassification
    fills_count: int
    fills: List[Dict[str, Any]]
    idempotency_keys: List[str]
    raw_order_payload: Dict[str, Any]
    raw_fills_payload: List[Dict[str, Any]]
    logger_ready: bool
    blocking_reasons: List[str] = field(default_factory=list)
    diagnostics: Dict[str, Any] = field(default_factory=dict)


def _classify(value: Any, is_direct: bool = False, notes: str = "") -> FieldClassification:
    if value in (None, "", 0, "0", 0.0):
        return FieldClassification(value, "unavailable", notes or "Value missing or zero in payload")
    if is_direct:
        return FieldClassification(value, "direct_broker_fact", notes)
    return FieldClassification(value, "locally_derived", notes)


def _get_fill_id(f: Dict[str, Any]) -> Optional[str]:
    """Preferred stable per-fill identifier."""
    return f.get("trade_id") or f.get("entry_id") or f.get("fill_id")


def reconcile_order_with_fills(
    order_status: Dict[str, Any],
    historical_fills: List[Dict[str, Any]],
    *,
    account_mode: str = "live",
    leg_type: str = "entry",
) -> ReconciliationResult:
    """
    Pure reconciliation of order status + historical fills.

    Returns a structured result with classifications and logger readiness.
    Never estimates P/L for output. Diagnostics only.
    """
    order = order_status.get("order", order_status)  # support both wrapped and flat

    product_id = order.get("product_id")
    side = order.get("side", "").upper()
    order_id = order.get("order_id")
    order_status_str = order.get("status") or order.get("normalized_status")

    filled_size = _classify(
        order.get("filled_size"),
        is_direct=True,
        notes="Direct from Coinbase order object"
    )
    average_filled_price = _classify(
        order.get("average_filled_price"),
        is_direct=True,
        notes="Direct from Coinbase order object"
    )
    total_fees = _classify(
        order.get("total_fees"),
        is_direct=True,
        notes="Direct from Coinbase order object (order-level total)"
    )

    # For exit legs, prefer filled_value as direct sell proceeds
    filled_value = _classify(
        order.get("filled_value"),
        is_direct=True,
        notes="Direct quote value from Coinbase (key for exit proceeds)"
    )

    # Diagnostics only — never treat as direct fact for logging
    gross_quote_value: Optional[float] = None
    try:
        if filled_size.value and average_filled_price.value:
            gross_quote_value = float(filled_size.value) * float(average_filled_price.value)
    except Exception:
        pass

    sells_proceeds = _classify(
        filled_value.value if side == "SELL" else None,
        is_direct=(side == "SELL"),
        notes="Direct sell proceeds only available when leg is SELL and filled_value present"
    )

    fills_count = len(historical_fills)
    processed_fills: List[Dict[str, Any]] = []
    idempotency_keys: List[str] = []
    blocking_reasons: List[str] = []

    for f in historical_fills:
        fill_id = _get_fill_id(f)
        per_fill_fee = f.get("fee") or f.get("commission")

        if not fill_id:
            blocking_reasons.append("Missing stable fill ID (trade_id or entry_id) on at least one fill")

        if per_fill_fee in (None, "", 0, "0"):
            blocking_reasons.append("Missing per-fill fee on at least one fill — net P/L cannot be direct fact")

        processed_fills.append({
            "trade_id": f.get("trade_id"),
            "entry_id": f.get("entry_id"),
            "trade_time": f.get("trade_time") or f.get("time"),
            "price": f.get("price"),
            "size": f.get("size"),
            "fee": per_fill_fee,
            "fee_currency": f.get("fee_currency"),
            "liquidity_indicator": f.get("liquidity_indicator"),
            "raw_fill": f,
        })

        if fill_id:
            key = f"{account_mode}:{product_id}:{order_id}:{fill_id}"
            idempotency_keys.append(key)

    # Blocking rules
    if leg_type == "exit" and not sells_proceeds.value:
        blocking_reasons.append("Exit leg missing direct sell proceeds (filled_value on SELL order)")

    if fills_count == 0:
        blocking_reasons.append("No fills returned for order — cannot prove per-fill facts")

    if not idempotency_keys:
        blocking_reasons.append("No stable per-fill idempotency keys could be generated")

    # logger_ready only if no blocking reasons
    logger_ready = len(blocking_reasons) == 0

    # Diagnostics (clearly marked, not for logging decisions)
    diagnostics = {}
    if gross_quote_value is not None:
        diagnostics["gross_quote_value_diagnostic"] = gross_quote_value
        diagnostics["gross_quote_value_classification"] = "locally_derived"

    return ReconciliationResult(
        account_mode=account_mode,
        leg_type=leg_type,
        product_id=product_id,
        side=side,
        order_id=order_id,
        order_status=order_status_str,
        filled_size=filled_size,
        average_filled_price=average_filled_price,
        total_fees=total_fees,
        filled_value=filled_value,
        sells_proceeds=sells_proceeds,
        fills_count=fills_count,
        fills=processed_fills,
        idempotency_keys=idempotency_keys,
        raw_order_payload=dict(order_status),
        raw_fills_payload=list(historical_fills),
        logger_ready=logger_ready,
        blocking_reasons=blocking_reasons,
        diagnostics=diagnostics,
    )
