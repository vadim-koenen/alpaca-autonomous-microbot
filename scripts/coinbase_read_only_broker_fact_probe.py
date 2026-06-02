#!/usr/bin/env python3
"""
P2-011J — Read-Only Coinbase Broker-Fact Discovery Probe (proof / instrumentation only).

ADVISORY ONLY

This script is a controlled, read-only discovery tool. Its purpose is to inspect
what direct broker facts are available from Coinbase read surfaces (Get Order,
List Fills / historical fills, etc.) so the team can evaluate whether the
requirements for trustworthy fill logging are met.

Strict safety guarantees in this patch:
- Default mode performs ZERO live network calls.
- Any live read requires the explicit --live-read-only flag.
- No writes of any kind (no fill-log CSV writes, no fill-row appender activation).
- No order submission, cancel, or modify actions are ever performed.
- When producing output from live data, sensitive values are redacted.
- The probe never marks the logger as production-ready.

It builds on the pure helpers from P2-011F/G and the opt-in dry-run seam from
P2-011H/I, but remains completely independent for discovery purposes.

Usage:
    # Pure synthetic / fixture mode (safe, default)
    python3 scripts/coinbase_read_only_broker_fact_probe.py

    # Optional controlled live read (only if you have credentials and explicitly want it)
    python3 scripts/coinbase_read_only_broker_fact_probe.py --live-read-only --order-id <id> --symbol BTC-USD --output json

This is a Class 1 advisory/read-only patch.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

# Make runnable from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# We reuse the existing pure reconciliation logic for consistency (no writes)
try:
    from coinbase_order_fills_reconciliation import reconcile_order_with_fills
except ImportError:
    reconcile_order_with_fills = None  # graceful degradation if not present


# =============================================================================
# Redaction helpers (never leak secrets or raw account identifiers in output)
# =============================================================================

SENSITIVE_KEYS = {
    "api_key", "secret", "token", "bearer", "authorization",
    "account_id", "account_uuid", "portfolio_id", "user_id",
    "client_order_id",  # can contain strategy hints + timestamps; redact in live mode
}

ORDER_NUMERIC_PNL_FIELDS = (
    "filled_value",
    "total_fees",
    "filled_size",
    "average_filled_price",
)

ORDER_CONTEXT_FIELDS = (
    "settled",
    "status",
    "normalized_status",
    "side",
    "product_id",
)

FILL_NUMERIC_PNL_FIELDS = (
    "price",
    "size",
    "fee",
    "commission",
    "commission_detail_total",
    "size_in_quote",
)

FILL_CONTEXT_FIELDS = (
    "product_id",
    "side",
)

ORDER_IDENTIFIER_FIELDS = (
    "order_id",
    "client_order_id",
    "retail_portfolio_id",
    "account_id",
    "user_id",
)

FILL_IDENTIFIER_FIELDS = (
    "order_id",
    "trade_id",
    "entry_id",
    "fill_id",
)

SECRET_KEY_FRAGMENTS = (
    "api_key",
    "auth",
    "authorization",
    "bearer",
    "key",
    "password",
    "secret",
    "signature",
    "token",
)

def _redact_value(key: str, value: Any) -> Any:
    if isinstance(value, str) and any(s in key.lower() for s in SENSITIVE_KEYS):
        return "<REDACTED>"
    if isinstance(value, dict):
        return {k: _redact_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(key, item) for item in value]
    return value


def redact_payload(payload: Any) -> Any:
    """Recursively redact obviously sensitive fields from a payload for safe logging/output."""
    if isinstance(payload, dict):
        return {k: _redact_value(k, v) for k, v in payload.items()}
    if isinstance(payload, list):
        return [redact_payload(item) for item in payload]
    return payload


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def _string_value(value: Any) -> Any:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return value
    if value is None:
        return value
    return str(value)


def _redacted_identifier(label: str) -> str:
    return f"<REDACTED_{label.upper()}>"


def _secret_like_key(key: str) -> bool:
    lower = key.lower()
    return any(fragment in lower for fragment in SECRET_KEY_FRAGMENTS)


def _select_order_numeric_fields(order: Dict[str, Any]) -> Dict[str, Any]:
    selected: Dict[str, Any] = {}
    for key in ORDER_NUMERIC_PNL_FIELDS + ORDER_CONTEXT_FIELDS:
        if key in order and _present(order.get(key)):
            selected[key] = _string_value(order.get(key))
    for key in ORDER_IDENTIFIER_FIELDS:
        if key in order and _present(order.get(key)):
            selected[key] = _redacted_identifier(key)
    for key in order:
        if _secret_like_key(key):
            selected[key] = "<REDACTED_SECRET>"
    return selected


def _select_fill_numeric_fields(fill: Dict[str, Any]) -> Dict[str, Any]:
    selected: Dict[str, Any] = {}
    for key in FILL_NUMERIC_PNL_FIELDS + FILL_CONTEXT_FIELDS:
        if key in fill and _present(fill.get(key)):
            selected[key] = _string_value(fill.get(key))
    for key in FILL_IDENTIFIER_FIELDS:
        if key in fill and _present(fill.get(key)):
            selected[key] = _redacted_identifier(key)
    for key in fill:
        if _secret_like_key(key):
            selected[key] = "<REDACTED_SECRET>"
    return selected


# =============================================================================
# Field presence classification (core of the discovery)
# =============================================================================

@dataclass
class FieldPresence:
    name: str
    present: bool
    classification: str  # "direct_broker_fact" | "missing" | "unsafe_to_infer"
    notes: str = ""


@dataclass
class FillFactSummary:
    has_stable_id: bool = False          # trade_id or entry_id
    has_price: bool = False
    has_size: bool = False
    has_fee: bool = False
    has_liquidity_indicator: bool = False
    stable_id_value: Optional[str] = None  # redacted in live output


@dataclass
class OrderFactSummary:
    has_filled_size: bool = False
    has_average_filled_price: bool = False
    has_total_fees: bool = False
    has_filled_value: bool = False       # critical for direct sell proceeds on exits
    has_settled: bool = False
    side: Optional[str] = None


@dataclass
class BrokerFactDiscoveryReport:
    """Structured, redaction-safe report of what broker facts are available."""
    leg_type: str  # "entry" or "exit" or "unknown"
    symbol: str
    order_id: Optional[str]

    order_facts: OrderFactSummary
    fill_facts: List[FillFactSummary]

    direct_sell_proceeds_present: bool
    stable_per_fill_ids_present: bool
    per_fill_fees_present: bool

    logger_readiness_blocked: bool
    blocking_reasons: List[str] = field(default_factory=list)

    # Raw shapes preserved internally (for proof/audit), redacted in human output
    raw_order_shape_keys: List[str] = field(default_factory=list)
    raw_fills_count: int = 0
    raw_fills_shape_keys_sample: List[str] = field(default_factory=list)
    numeric_order_fields: Dict[str, Any] = field(default_factory=dict)
    numeric_fill_fields: List[Dict[str, Any]] = field(default_factory=list)

    read_only_only: bool = True
    live_read_only_requested: bool = False
    broker_methods_attempted: List[str] = field(default_factory=list)
    broker_calls_made: bool = False
    order_mutation_methods_attempted: bool = False

    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def _classify_order_fields(order: Dict[str, Any]) -> OrderFactSummary:
    return OrderFactSummary(
        has_filled_size=bool(order.get("filled_size")),
        has_average_filled_price=bool(order.get("average_filled_price")),
        has_total_fees=bool(order.get("total_fees")),
        has_filled_value=bool(order.get("filled_value")),
        has_settled="settled" in order,
        side=order.get("side"),
    )


def _classify_fills(fills: List[Dict[str, Any]]) -> List[FillFactSummary]:
    summaries: List[FillFactSummary] = []
    for f in fills:
        stable_id = f.get("trade_id") or f.get("entry_id") or f.get("fill_id")
        summaries.append(
            FillFactSummary(
                has_stable_id=bool(stable_id),
                has_price=bool(f.get("price")),
                has_size=bool(f.get("size")),
                has_fee=bool(f.get("fee") or f.get("commission")),
                has_liquidity_indicator=bool(f.get("liquidity_indicator")),
                stable_id_value=stable_id,  # will be redacted later if needed
            )
        )
    return summaries


def analyze_broker_facts(
    order_status: Dict[str, Any],
    historical_fills: List[Dict[str, Any]],
    *,
    leg_type: str = "unknown",
    symbol: str = "UNKNOWN",
    order_id: Optional[str] = None,
    live_read_only_requested: bool = False,
    broker_methods_attempted: Optional[List[str]] = None,
    broker_calls_made: bool = False,
) -> BrokerFactDiscoveryReport:
    """
    Pure analysis of broker payloads.

    Returns a redaction-safe report that makes field presence and blocking
    conditions explicit. Never infers missing values.
    """
    order = order_status.get("order", order_status)  # tolerate both shapes
    order_facts = _classify_order_fields(order)

    fill_summaries = _classify_fills(historical_fills)

    has_any_stable_id = any(f.has_stable_id for f in fill_summaries)
    has_any_per_fill_fee = any(f.has_fee for f in fill_summaries)

    blocking: List[str] = []

    if leg_type == "exit" and not order_facts.has_filled_value:
        blocking.append("Missing direct sell proceeds (filled_value on SELL order status)")

    if len(historical_fills) > 0 and not has_any_stable_id:
        blocking.append("No stable per-fill ID (trade_id/entry_id) present on any fill")

    if len(historical_fills) > 0 and not has_any_per_fill_fee:
        blocking.append("No per-fill fee present on any fill")

    if len(historical_fills) == 0:
        blocking.append("No fills returned from historical fills surface")

    logger_blocked = len(blocking) > 0

    # Raw shape for proof (we keep the keys, not the values)
    raw_order_keys = sorted(order.keys())
    raw_fills_keys = sorted({k for f in historical_fills for k in f.keys()}) if historical_fills else []
    numeric_order_fields = _select_order_numeric_fields(order)
    numeric_fill_fields = [_select_fill_numeric_fields(fill) for fill in historical_fills]

    return BrokerFactDiscoveryReport(
        leg_type=leg_type,
        symbol=symbol,
        order_id=order_id,
        order_facts=order_facts,
        fill_facts=fill_summaries,
        direct_sell_proceeds_present=(leg_type == "exit" and order_facts.has_filled_value),
        stable_per_fill_ids_present=has_any_stable_id,
        per_fill_fees_present=has_any_per_fill_fee,
        logger_readiness_blocked=logger_blocked,
        blocking_reasons=blocking,
        raw_order_shape_keys=raw_order_keys,
        raw_fills_count=len(historical_fills),
        raw_fills_shape_keys_sample=raw_fills_keys[:15],  # limit for readability
        numeric_order_fields=numeric_order_fields,
        numeric_fill_fields=numeric_fill_fields,
        read_only_only=True,
        live_read_only_requested=live_read_only_requested,
        broker_methods_attempted=broker_methods_attempted or [],
        broker_calls_made=broker_calls_made,
        order_mutation_methods_attempted=False,
    )


def redact_report_for_output(
    report: BrokerFactDiscoveryReport,
    *,
    include_numeric_pnl_fields: bool = False,
) -> Dict[str, Any]:
    """Produce a safe-for-logging version of the report."""
    d = asdict(report)
    numeric_order_fields = d.pop("numeric_order_fields", {}) or {}
    numeric_fill_fields = d.pop("numeric_fill_fields", []) or []
    # Redact any potential identifiers that might have leaked into the report
    if d.get("order_id"):
        d["order_id"] = "<REDACTED_ORDER_ID>"
    for f in d.get("fill_facts", []):
        if f.get("stable_id_value"):
            f["stable_id_value"] = "<REDACTED_FILL_ID>"
    d["numeric_pnl_fields_included"] = include_numeric_pnl_fields
    if include_numeric_pnl_fields:
        d["order_status"] = numeric_order_fields
        d["fills"] = numeric_fill_fields
    return d


# =============================================================================
# Live read support (explicitly opt-in only)
# =============================================================================

def _get_live_broker(broker_factory: Optional[Callable[[], Any]] = None) -> Any:
    """Lazily import and return a real broker only when --live-read-only is used."""
    if broker_factory is not None:
        return broker_factory()

    try:
        from broker_coinbase import BrokerCoinbase  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "Could not import BrokerCoinbase. Live mode requires the real broker to be importable."
        ) from e

    # The real broker will read its own credentials from the environment at construction time.
    # We do not touch .env here.
    return BrokerCoinbase()


def build_non_live_refusal_report(symbol: str, order_id: Optional[str]) -> BrokerFactDiscoveryReport:
    """Return a structured refusal for order-specific broker facts without live opt-in."""
    return BrokerFactDiscoveryReport(
        leg_type="unknown",
        symbol=symbol,
        order_id=order_id,
        order_facts=OrderFactSummary(),
        fill_facts=[],
        direct_sell_proceeds_present=False,
        stable_per_fill_ids_present=False,
        per_fill_fees_present=False,
        logger_readiness_blocked=True,
        blocking_reasons=[
            "Live read-only broker fact capture requires explicit --live-read-only; "
            "no broker object was constructed and no broker calls were made."
        ],
        raw_order_shape_keys=[],
        raw_fills_count=0,
        raw_fills_shape_keys_sample=[],
        read_only_only=True,
        live_read_only_requested=False,
        broker_methods_attempted=[],
        broker_calls_made=False,
        order_mutation_methods_attempted=False,
    )


def run_live_read_only_discovery(
    symbol: str,
    order_id: Optional[str] = None,
    broker_factory: Optional[Callable[[], Any]] = None,
) -> BrokerFactDiscoveryReport:
    """
    Perform actual (but read-only) broker calls.

    THIS PATH MUST ONLY BE REACHED WHEN THE USER EXPLICITLY PASSES --live-read-only.
    It is intentionally not used by the test suite.
    """
    broker = _get_live_broker(broker_factory=broker_factory)
    broker_methods_attempted: List[str] = []

    status: Dict[str, Any] = {}
    if order_id:
        try:
            broker_methods_attempted.append("get_order_status")
            status = broker.get_order_status(order_id=order_id) or {}
        except Exception as e:
            status = {"error": str(e)}

    fills: List[Dict[str, Any]] = []
    try:
        broker_methods_attempted.append("get_historical_fills")
        fills = broker.get_historical_fills(product_id=symbol, order_id=order_id) or []
    except Exception as e:
        fills = [{"error": str(e)}]

    leg_type = "exit" if status.get("side", "").upper() == "SELL" else "entry"

    report = analyze_broker_facts(
        status,
        fills,
        leg_type=leg_type,
        symbol=symbol,
        order_id=order_id,
        live_read_only_requested=True,
        broker_methods_attempted=broker_methods_attempted,
        broker_calls_made=bool(broker_methods_attempted),
    )

    # Redact before returning for any human-visible output
    return report


# =============================================================================
# CLI
# =============================================================================

def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="P2-011J Read-Only Coinbase Broker-Fact Discovery Probe")
    parser.add_argument("--symbol", default="BTC-USD", help="Product symbol for discovery")
    parser.add_argument("--order-id", default=None, help="Specific order_id to inspect (optional)")
    parser.add_argument(
        "--live-read-only",
        action="store_true",
        help="Enable real (read-only) broker calls. Requires explicit opt-in. Disabled by default.",
    )
    parser.add_argument(
        "--output",
        choices=["pretty", "json"],
        default="pretty",
        help="Output format",
    )
    parser.add_argument(
        "--include-numeric-pnl-fields",
        "--numeric-safe",
        action="store_true",
        help=(
            "Include numeric-safe direct broker P/L fields in output while keeping "
            "identifiers and secret-like fields redacted."
        ),
    )
    args = parser.parse_args(argv)

    if args.live_read_only:
        print("!!! LIVE READ-ONLY MODE ENABLED !!!", file=sys.stderr)
        print("This will make real read-only calls to the Coinbase broker.", file=sys.stderr)
        print("No writes or order actions will be performed.", file=sys.stderr)
        report = run_live_read_only_discovery(args.symbol, args.order_id)
        redacted = redact_report_for_output(
            report,
            include_numeric_pnl_fields=args.include_numeric_pnl_fields,
        )
    else:
        if args.order_id:
            report = build_non_live_refusal_report(args.symbol, args.order_id)
        else:
            # Default: synthetic / controlled mode using the best available static shapes
            # (we reuse some well-known good shapes from previous proof work)
            good_entry = {
                "normalized_status": "filled",
                "side": "BUY",
                "filled_size": "0.00123456",
                "average_filled_price": "65000.50",
                "total_fees": "0.4815",
                "filled_value": "80.25",
            }
            good_fills = [
                {
                    "trade_id": "t-demo-1",
                    "price": "65000.50",
                    "size": "0.00123456",
                    "fee": "0.4815",
                    "fee_currency": "USD",
                    "liquidity_indicator": "MAKER",
                }
            ]
            report = analyze_broker_facts(
                good_entry,
                good_fills,
                leg_type="entry",
                symbol=args.symbol,
                order_id=args.order_id or "demo-order",
            )
        redacted = redact_report_for_output(
            report,
            include_numeric_pnl_fields=args.include_numeric_pnl_fields,
        )

    if args.output == "json":
        print(json.dumps(redacted, indent=2, default=str))
    else:
        print("=== P2-011J Read-Only Broker-Fact Discovery Report ===")
        print(f"Symbol: {redacted.get('symbol')}")
        print(f"Leg: {redacted.get('leg_type')}")
        print(f"Logger readiness blocked: {redacted.get('logger_readiness_blocked')}")
        if redacted.get("blocking_reasons"):
            print("Blocking reasons:")
            for r in redacted["blocking_reasons"]:
                print(f"  - {r}")
        print("\nOrder facts presence:")
        for k, v in redacted.get("order_facts", {}).items():
            print(f"  {k}: {v}")
        print(f"\nRaw order shape keys (proof): {redacted.get('raw_order_shape_keys')}")
        print(f"Raw fills count: {redacted.get('raw_fills_count')}")
        if redacted.get("numeric_pnl_fields_included"):
            print("Numeric-safe direct broker P/L fields included.")
        print("Redacted for safety. No secrets or raw identifiers emitted.")


if __name__ == "__main__":
    main()
