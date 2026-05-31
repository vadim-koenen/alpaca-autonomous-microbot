"""
P2-011G — Inert Coinbase Entry/Exit Capture Wiring (proof only).

ADVISORY ONLY — This module exists solely to prove the narrow capture seam
for combining Coinbase order status + historical fills for entry and exit legs.

It is deliberately inert:
- It is never called from main.py, position_manager.py, order_manager.py,
  strategy_*.py, journal.py, or any runtime/launchd path.
- It performs no I/O, no logging of fills, and no writes to coinbase_fills.csv.
- It does not modify any live trading behavior.

This is a Class 1 advisory/read-only patch per ACTIVE_HANDOFF rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from coinbase_order_fills_reconciliation import (
    ReconciliationResult,
    reconcile_order_with_fills,
)


@dataclass
class CaptureResult:
    """Structured result from an inert entry or exit capture attempt."""

    leg_type: str  # "entry" or "exit"
    symbol: str
    order_id: Optional[str]
    client_order_id: Optional[str]
    account_mode: str

    # Reconciliation facts (direct broker facts preserved)
    reconciliation: ReconciliationResult

    # Capture metadata (for future wiring diagnostics)
    capture_time_utc: str
    has_fills: bool
    has_direct_fees: bool
    has_direct_sell_proceeds: bool
    has_stable_fill_ids: bool

    # Readiness
    logger_ready: bool
    blocking_reasons: List[str] = field(default_factory=list)

    # Optional diagnostics (never used for actual logging decisions)
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    # Raw payloads for future auditing (must come after fields with defaults)
    raw_order_payload: Dict[str, Any] = field(default_factory=dict)
    raw_fills_payload: List[Dict[str, Any]] = field(default_factory=list)


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def capture_leg(
    order_status: Dict[str, Any],
    historical_fills: List[Dict[str, Any]],
    *,
    leg_type: str,
    symbol: str,
    account_mode: str = "live",
    client_order_id: Optional[str] = None,
) -> CaptureResult:
    """
    Inert capture of entry or exit leg facts using order status + fills.

    This function is pure and side-effect free. It is intended to be called
    only from test code or future narrow, guarded capture points (not yet written).

    It reuses the P2-011F reconciliation logic and adds entry/exit-specific
    capture metadata and readiness assessment.
    """
    if leg_type not in ("entry", "exit"):
        raise ValueError("leg_type must be 'entry' or 'exit'")

    rec = reconcile_order_with_fills(
        order_status,
        historical_fills,
        account_mode=account_mode,
        leg_type=leg_type,
    )

    order = order_status.get("order", order_status)
    order_id = order.get("order_id")

    has_fills = rec.fills_count > 0
    has_direct_fees = bool(rec.total_fees.value) or any(
        f.get("fee") for f in rec.fills
    )
    has_direct_sell_proceeds = rec.sells_proceeds.classification == "direct_broker_fact"
    has_stable_fill_ids = len(rec.idempotency_keys) > 0

    blocking = list(rec.blocking_reasons)

    # Additional capture-level blocking (even if reconciliation is internally happy)
    if leg_type == "exit" and not has_direct_sell_proceeds:
        if "Exit leg missing direct sell proceeds (filled_value on SELL order)" not in blocking:
            blocking.append("Exit leg missing direct sell proceeds (filled_value on SELL order)")

    logger_ready = len(blocking) == 0 and rec.logger_ready

    return CaptureResult(
        leg_type=leg_type,
        symbol=symbol,
        order_id=order_id,
        client_order_id=client_order_id,
        account_mode=account_mode,
        reconciliation=rec,
        capture_time_utc=_now_utc(),
        has_fills=has_fills,
        has_direct_fees=has_direct_fees,
        has_direct_sell_proceeds=has_direct_sell_proceeds,
        has_stable_fill_ids=has_stable_fill_ids,
        logger_ready=logger_ready,
        blocking_reasons=blocking,
        raw_order_payload=dict(order_status),
        raw_fills_payload=list(historical_fills),
        diagnostics=rec.diagnostics,
    )


def capture_entry(
    order_status: Dict[str, Any],
    historical_fills: List[Dict[str, Any]],
    *,
    symbol: str,
    account_mode: str = "live",
    client_order_id: Optional[str] = None,
) -> CaptureResult:
    """Convenience wrapper for entry leg capture (inert)."""
    return capture_leg(
        order_status,
        historical_fills,
        leg_type="entry",
        symbol=symbol,
        account_mode=account_mode,
        client_order_id=client_order_id,
    )


def capture_exit(
    order_status: Dict[str, Any],
    historical_fills: List[Dict[str, Any]],
    *,
    symbol: str,
    account_mode: str = "live",
    client_order_id: Optional[str] = None,
) -> CaptureResult:
    """Convenience wrapper for exit leg capture (inert)."""
    return capture_leg(
        order_status,
        historical_fills,
        leg_type="exit",
        symbol=symbol,
        account_mode=account_mode,
        client_order_id=client_order_id,
    )
