"""
P2-012A — Prediction Telemetry (pure helpers + append-only writer).

This module provides:
- Deterministic derivative-style feature calculations from price series.
- A safe append-only writer for proposal/prediction telemetry rows.
- Pure functions for tests and the status script.

It is deliberately non-intrusive:
- Writing is append-only to prediction_telemetry/prediction_telemetry.jsonl
- No effect on order decisions.
- All functions are safe with missing/insufficient data (they degrade gracefully).

Schema version is included in every row for future evolution.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# =============================================================================
# Configuration (safe defaults)
# =============================================================================

TELEMETRY_DIR = Path("prediction_telemetry")
TELEMETRY_FILE = TELEMETRY_DIR / "prediction_telemetry.jsonl"
SCHEMA_VERSION = "p2_012a_v1"


def _ensure_dir() -> None:
    TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# Derivative-style feature helpers (pure, deterministic)
# =============================================================================

def compute_short_slope(prices: Sequence[float]) -> Optional[float]:
    """Simple linear slope over the most recent ~5-10 points (short horizon)."""
    n = len(prices)
    if n < 3:
        return None
    # Use last min(8, n) points
    window = min(8, n)
    y = list(prices[-window:])
    x = list(range(window))
    return _linear_slope(x, y)


def compute_medium_slope(prices: Sequence[float]) -> Optional[float]:
    """Linear slope over a medium window (~15-30 points)."""
    n = len(prices)
    if n < 5:
        return None
    window = min(20, n)
    y = list(prices[-window:])
    x = list(range(window))
    return _linear_slope(x, y)


def compute_acceleration(short_slope: Optional[float], medium_slope: Optional[float]) -> Optional[float]:
    if short_slope is None or medium_slope is None:
        return None
    return short_slope - medium_slope


def compute_volatility(prices: Sequence[float], window: int = 20) -> Optional[float]:
    """Simple realized volatility proxy: std of log returns over window."""
    n = len(prices)
    if n < 3:
        return None
    w = min(window, n - 1)
    rets = []
    for i in range(1, w + 1):
        if prices[-i] > 0 and prices[-i-1] > 0:
            rets.append(math.log(prices[-i] / prices[-i-1]))
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var)


def compute_spread_bps(bid: Optional[float], ask: Optional[float]) -> Optional[float]:
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    mid = (bid + ask) / 2
    if mid <= 0:
        return None
    return ((ask - bid) / mid) * 10000.0


def compute_range_position(prices: Sequence[float], current: float) -> Optional[float]:
    """Position of current price within recent min/max (0 = low, 1 = high)."""
    if not prices or current is None:
        return None
    recent = list(prices[-30:])  # reasonable window
    lo, hi = min(recent), max(recent)
    if hi <= lo:
        return None
    return (current - lo) / (hi - lo)


def _linear_slope(x: Sequence[float], y: Sequence[float]) -> Optional[float]:
    n = len(x)
    if n < 2:
        return None
    sum_x = sum(x)
    sum_y = sum(y)
    sum_xy = sum(xi * yi for xi, yi in zip(x, y))
    sum_xx = sum(xi * xi for xi in x)
    denom = n * sum_xx - sum_x * sum_x
    if abs(denom) < 1e-12:
        return None
    return (n * sum_xy - sum_x * sum_y) / denom


def compute_derivative_features(
    prices: Sequence[float],
    *,
    bid: Optional[float] = None,
    ask: Optional[float] = None,
    current_price: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Compute a standard set of derivative-style features from a recent price series.

    Returns a dict with keys:
      short_slope, medium_slope, acceleration, volatility, spread_bps, range_position
    All values can be None if insufficient data.
    """
    if not prices or len(prices) < 3:
        return {
            "short_slope": None,
            "medium_slope": None,
            "acceleration": None,
            "volatility": None,
            "spread_bps": compute_spread_bps(bid, ask),
            "range_position": None,
        }

    short = compute_short_slope(prices)
    medium = compute_medium_slope(prices)
    accel = compute_acceleration(short, medium)
    vol = compute_volatility(prices)
    spread = compute_spread_bps(bid, ask)
    rng = compute_range_position(prices, current_price or prices[-1])

    return {
        "short_slope": round(short, 8) if short is not None else None,
        "medium_slope": round(medium, 8) if medium is not None else None,
        "acceleration": round(accel, 8) if accel is not None else None,
        "volatility": round(vol, 8) if vol is not None else None,
        "spread_bps": round(spread, 2) if spread is not None else None,
        "range_position": round(rng, 4) if rng is not None else None,
    }


# =============================================================================
# Telemetry row + writer
# =============================================================================

@dataclass
class PredictionTelemetryRow:
    timestamp: str
    schema_version: str
    symbol: str
    strategy: str
    regime: Optional[str]
    side: Optional[str]
    confidence: Optional[float]
    proposed_notional: Optional[float]
    entry_price: Optional[float]
    bid: Optional[float]
    ask: Optional[float]
    spread_pct: Optional[float]
    decision_status: str          # "candidate", "skipped", "placed", "filled", "exited"
    skip_reason: Optional[str]
    prediction_horizons: Dict[str, Any]   # e.g. {"15m": {...}, "30m": {...}, ...}
    features: Dict[str, Any]
    outcome: Dict[str, Any]               # placeholders for future evaluation
    source: str                           # e.g. "strategy_router", "risk_manager", "position_manager"
    raw_payload: Dict[str, Any]           # original proposal/state snapshot (redacted if needed)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _ensure_header_and_append(row: Dict[str, Any]) -> None:
    """Append a row to the telemetry file. Writes header on first creation."""
    _ensure_dir()
    is_new = not TELEMETRY_FILE.exists()

    with open(TELEMETRY_FILE, "a", encoding="utf-8") as f:
        if is_new:
            # Write a one-line header comment for humans + tools
            header = {
                "schema_version": SCHEMA_VERSION,
                "description": "Prediction telemetry for P2-012A. Append-only.",
                "generated_at": _utc_now(),
            }
            f.write("# " + json.dumps(header) + "\n")
        f.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")


def log_prediction_telemetry(
    *,
    symbol: str,
    strategy: str,
    regime: Optional[str] = None,
    side: Optional[str] = None,
    confidence: Optional[float] = None,
    proposed_notional: Optional[float] = None,
    entry_price: Optional[float] = None,
    bid: Optional[float] = None,
    ask: Optional[float] = None,
    spread_pct: Optional[float] = None,
    decision_status: str = "candidate",
    skip_reason: Optional[str] = None,
    features: Optional[Dict[str, Any]] = None,
    outcome: Optional[Dict[str, Any]] = None,
    source: str = "unknown",
    raw_payload: Optional[Dict[str, Any]] = None,
    horizons: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Log one prediction/proposal event.

    This is the main entry point used by the rest of the system.
    It is safe, append-only, and never blocks.
    """
    row = PredictionTelemetryRow(
        timestamp=_utc_now(),
        schema_version=SCHEMA_VERSION,
        symbol=symbol,
        strategy=strategy,
        regime=regime,
        side=side,
        confidence=confidence,
        proposed_notional=proposed_notional,
        entry_price=entry_price,
        bid=bid,
        ask=ask,
        spread_pct=spread_pct,
        decision_status=decision_status,
        skip_reason=skip_reason,
        prediction_horizons=horizons or {"15m": None, "30m": None, "60m": None, "90m": None},
        features=features or {},
        outcome=outcome or {"15m": None, "30m": None, "60m": None, "90m": None},
        source=source,
        raw_payload=raw_payload or {},
    )

    row_dict = asdict(row)
    _ensure_header_and_append(row_dict)
    return row_dict


# =============================================================================
# Convenience helpers for common callers
# =============================================================================

def log_proposal_candidate(
    proposal: Any,  # TradeProposal or dict-like
    *,
    regime: Optional[str] = None,
    source: str = "strategy_router",
    features: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Log a fresh proposal as a 'candidate'."""
    if hasattr(proposal, "symbol"):
        p = proposal
    else:
        p = type("obj", (object,), proposal)()

    return log_prediction_telemetry(
        symbol=getattr(p, "symbol", "UNKNOWN"),
        strategy=getattr(p, "strategy", "unknown"),
        regime=regime,
        side=getattr(p, "side", None),
        confidence=getattr(p, "confidence", None),
        proposed_notional=getattr(p, "notional", None),
        entry_price=getattr(p, "price", None),
        bid=getattr(p, "bid", None),
        ask=getattr(p, "ask", None),
        spread_pct=getattr(p, "spread_pct", None),
        decision_status="candidate",
        source=source,
        features=features or {},
        raw_payload=getattr(p, "__dict__", dict(proposal) if isinstance(proposal, dict) else {}),
    )


def log_skipped_proposal(
    proposal: Any,
    reason: str,
    *,
    regime: Optional[str] = None,
    source: str = "risk_manager",
) -> Dict[str, Any]:
    """Log a proposal that was skipped, with reason."""
    if hasattr(proposal, "symbol"):
        p = proposal
    else:
        p = type("obj", (object,), proposal)()

    return log_prediction_telemetry(
        symbol=getattr(p, "symbol", "UNKNOWN"),
        strategy=getattr(p, "strategy", "unknown"),
        regime=regime,
        side=getattr(p, "side", None),
        confidence=getattr(p, "confidence", None),
        proposed_notional=getattr(p, "notional", None),
        entry_price=getattr(p, "price", None),
        decision_status="skipped",
        skip_reason=reason,
        source=source,
        features={"skip_reason": reason},
        raw_payload=getattr(p, "__dict__", dict(proposal) if isinstance(proposal, dict) else {}),
    )
