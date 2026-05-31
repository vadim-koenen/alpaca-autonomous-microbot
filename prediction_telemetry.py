"""
P2-012A — Prediction Telemetry (append-only, schema-versioned, no production logger writes).

This module provides:
- Deterministic derivative-style feature calculations from price series (no trading).
- A safe append-only writer for proposal / signal telemetry to a dedicated file
  (logs/prediction_telemetry.jsonl by default — never touches coinbase_fills.csv).

All functions are side-effect free except the explicit telemetry writer.
The writer is append-only and creates its own directory/file if needed.

This is scaffolding for future measurement of every candidate (skipped or placed).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# Dedicated telemetry file (separate from fill logger)
TELEMETRY_DIR = Path("logs")
TELEMETRY_FILE = TELEMETRY_DIR / "prediction_telemetry.jsonl"
SCHEMA_VERSION = "p2_012a_v1"


def _ensure_dir() -> None:
    TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# Derivative-style feature helpers (pure, fixture-friendly)
# =============================================================================

def _safe_slope(x: Sequence[float], y: Sequence[float]) -> Optional[float]:
    n = len(x)
    if n < 2:
        return None
    sx = sum(x)
    sy = sum(y)
    sxy = sum(xi * yi for xi, yi in zip(x, y))
    sxx = sum(xi * xi for xi in x)
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-12:
        return None
    return (n * sxy - sx * sy) / denom


def compute_short_slope(prices: Sequence[float], window: int = 8) -> Optional[float]:
    """Linear slope over a short recent window."""
    n = len(prices)
    if n < 3:
        return None
    w = min(window, n)
    y = list(prices[-w:])
    x = list(range(w))
    return _safe_slope(x, y)


def compute_medium_slope(prices: Sequence[float], window: int = 20) -> Optional[float]:
    """Linear slope over a medium window."""
    n = len(prices)
    if n < 5:
        return None
    w = min(window, n)
    y = list(prices[-w:])
    x = list(range(w))
    return _safe_slope(x, y)


def compute_acceleration(prices: Sequence[float]) -> Optional[float]:
    s = compute_short_slope(prices)
    m = compute_medium_slope(prices)
    if s is None or m is None:
        return None
    return s - m


def compute_volatility(prices: Sequence[float], window: int = 20) -> Optional[float]:
    n = len(prices)
    if n < 3:
        return None
    w = min(window, n - 1)
    rets = []
    for i in range(1, w + 1):
        p0, p1 = prices[-i-1], prices[-i]
        if p0 > 0 and p1 > 0:
            rets.append(math.log(p1 / p0))
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(1, len(rets) - 1)
    return math.sqrt(var)


def compute_spread_bps(bid: Optional[float], ask: Optional[float]) -> Optional[float]:
    if not bid or not ask or bid <= 0 or ask <= 0:
        return None
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return None
    return ((ask - bid) / mid) * 10000.0


def compute_range_position(prices: Sequence[float], current: Optional[float] = None) -> Optional[float]:
    if not prices:
        return None
    vals = list(prices[-30:])
    lo, hi = min(vals), max(vals)
    if hi <= lo:
        return None
    ref = current if current is not None else vals[-1]
    return (ref - lo) / (hi - lo)


def compute_derivative_features(
    prices: Sequence[float],
    *,
    bid: Optional[float] = None,
    ask: Optional[float] = None,
    current_price: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Compute a standard basket of derivative-style features.

    Returns dict with:
      short_slope, medium_slope, acceleration, volatility, spread_bps, range_position
    All values may be None if data is insufficient.
    """
    return {
        "short_slope": compute_short_slope(prices),
        "medium_slope": compute_medium_slope(prices),
        "acceleration": compute_acceleration(prices),
        "volatility": compute_volatility(prices),
        "spread_bps": compute_spread_bps(bid, ask),
        "range_position": compute_range_position(prices, current_price or (prices[-1] if prices else None)),
    }


# =============================================================================
# Telemetry row + safe writer
# =============================================================================

@dataclass
class PredictionTelemetryRow:
    timestamp: str
    schema_version: str
    symbol: str
    product_id: str
    product_type: str
    strategy: str
    regime: Optional[str]
    side: Optional[str]
    confidence: Optional[float]
    proposed_notional: Optional[float]
    reference_price: Optional[float]
    bid: Optional[float]
    ask: Optional[float]
    spread_bps: Optional[float]
    decision_status: str                 # candidate / skipped / placed / filled / exited / unknown
    reason: Optional[str]
    horizon_15m_outcome: Optional[Any]
    horizon_30m_outcome: Optional[Any]
    horizon_60m_outcome: Optional[Any]
    horizon_90m_outcome: Optional[Any]
    features: Dict[str, Any]
    source: str
    raw_payload: Dict[str, Any]          # original proposal / status snapshot (may be redacted upstream)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_row(row: Dict[str, Any]) -> None:
    """Append-only write with schema header on first creation."""
    _ensure_dir()
    is_new = not TELEMETRY_FILE.exists()

    with open(TELEMETRY_FILE, "a", encoding="utf-8") as f:
        if is_new:
            header = {
                "schema_version": SCHEMA_VERSION,
                "created_at": _utc_now_iso(),
                "note": "P2-012A prediction telemetry. Separate from fill logger. Append-only.",
            }
            f.write("# " + json.dumps(header) + "\n")
        f.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")


def log_prediction_telemetry(
    *,
    symbol: str,
    product_id: str = "",
    product_type: str = "unknown",
    strategy: str,
    regime: Optional[str] = None,
    side: Optional[str] = None,
    confidence: Optional[float] = None,
    proposed_notional: Optional[float] = None,
    reference_price: Optional[float] = None,
    bid: Optional[float] = None,
    ask: Optional[float] = None,
    decision_status: str = "candidate",
    reason: Optional[str] = None,
    features: Optional[Dict[str, Any]] = None,
    source: str = "unknown",
    raw_payload: Optional[Dict[str, Any]] = None,
    horizons: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Log one prediction / proposal event.

    This is the primary entry point. Safe, append-only, never blocks.
    """
    row = PredictionTelemetryRow(
        timestamp=_utc_now_iso(),
        schema_version=SCHEMA_VERSION,
        symbol=symbol,
        product_id=product_id or symbol,
        product_type=product_type,
        strategy=strategy,
        regime=regime,
        side=side,
        confidence=confidence,
        proposed_notional=proposed_notional,
        reference_price=reference_price,
        bid=bid,
        ask=ask,
        spread_bps=compute_spread_bps(bid, ask),
        decision_status=decision_status,
        reason=reason,
        horizon_15m_outcome=(horizons or {}).get("15m"),
        horizon_30m_outcome=(horizons or {}).get("30m"),
        horizon_60m_outcome=(horizons or {}).get("60m"),
        horizon_90m_outcome=(horizons or {}).get("90m"),
        features=features or compute_derivative_features([]),  # empty -> all None
        source=source,
        raw_payload=raw_payload or {},
    )

    row_dict = asdict(row)
    _write_row(row_dict)
    return row_dict


# Convenience wrappers used by strategy / risk code
def log_proposal_candidate(proposal: Any, *, regime: Optional[str] = None, source: str = "strategy_router") -> Dict[str, Any]:
    if hasattr(proposal, "symbol"):
        p = proposal
    else:
        p = type("P", (), proposal if isinstance(proposal, dict) else {})()

    return log_prediction_telemetry(
        symbol=getattr(p, "symbol", "UNKNOWN"),
        product_id=getattr(p, "product_id", getattr(p, "symbol", "UNKNOWN")),
        product_type=getattr(p, "product_type", "unknown"),
        strategy=getattr(p, "strategy", "unknown"),
        regime=regime,
        side=getattr(p, "side", None),
        confidence=getattr(p, "confidence", None),
        proposed_notional=getattr(p, "notional", None),
        reference_price=getattr(p, "price", None),
        bid=getattr(p, "bid", None),
        ask=getattr(p, "ask", None),
        decision_status="candidate",
        source=source,
        raw_payload=getattr(p, "__dict__", dict(proposal) if isinstance(proposal, dict) else {}),
    )


def log_skipped_proposal(proposal: Any, reason: str, *, regime: Optional[str] = None, source: str = "risk_manager") -> Dict[str, Any]:
    if hasattr(proposal, "symbol"):
        p = proposal
    else:
        p = type("P", (), proposal if isinstance(proposal, dict) else {})()

    return log_prediction_telemetry(
        symbol=getattr(p, "symbol", "UNKNOWN"),
        product_id=getattr(p, "product_id", getattr(p, "symbol", "UNKNOWN")),
        product_type=getattr(p, "product_type", "unknown"),
        strategy=getattr(p, "strategy", "unknown"),
        regime=regime,
        side=getattr(p, "side", None),
        confidence=getattr(p, "confidence", None),
        proposed_notional=getattr(p, "notional", None),
        decision_status="skipped",
        reason=reason,
        source=source,
        raw_payload=getattr(p, "__dict__", dict(proposal) if isinstance(proposal, dict) else {}),
    )
