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
import logging
import math
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone, timedelta
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
    features_json: Dict[str, Any]
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
        features_json=features or compute_derivative_features([]),  # empty -> all None
        source=source,
        raw_payload=raw_payload or {},
    )

    row_dict = asdict(row)
    _write_row(row_dict)
    return row_dict


# Convenience wrappers used by strategy / risk code
def log_proposal_candidate(
    proposal: Any,
    *,
    regime: Optional[str] = None,
    source: str = "strategy_router",
    features: Optional[Dict[str, Any]] = None,
    raw_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
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
        features=features,
        raw_payload=raw_payload or getattr(p, "__dict__", dict(proposal) if isinstance(proposal, dict) else {}),
    )


def log_skipped_proposal(
    proposal: Any,
    reason: str,
    *,
    regime: Optional[str] = None,
    source: str = "risk_manager",
    features: Optional[Dict[str, Any]] = None,
    raw_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
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
        features=features,
        raw_payload=raw_payload or getattr(p, "__dict__", dict(proposal) if isinstance(proposal, dict) else {}),
    )


# P2-012B: safe non-fatal wrappers. Telemetry must never break live scan/order paths.
def safe_log_prediction_telemetry(**kwargs) -> Dict[str, Any]:
    """Append telemetry; never raises. Returns the row or error dict."""
    try:
        return log_prediction_telemetry(**kwargs)
    except Exception as e:
        logging.getLogger(__name__).debug("prediction telemetry write non-fatal: %s", e)
        return {"error": str(e), "symbol": kwargs.get("symbol", "UNKNOWN"), "decision_status": kwargs.get("decision_status")}


def safe_log_proposal_candidate(
    proposal: Any,
    *,
    regime: Optional[str] = None,
    source: str = "strategy_router",
    features: Optional[Dict[str, Any]] = None,
    raw_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    try:
        return log_proposal_candidate(
            proposal, regime=regime, source=source, features=features, raw_payload=raw_payload
        )
    except Exception as e:
        logging.getLogger(__name__).debug("prediction telemetry (candidate) non-fatal: %s", e)
        return {"error": str(e), "symbol": getattr(proposal, "symbol", "UNKNOWN")}


def safe_log_skipped_proposal(
    proposal: Any,
    reason: str,
    *,
    regime: Optional[str] = None,
    source: str = "risk_manager",
    features: Optional[Dict[str, Any]] = None,
    raw_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    try:
        return log_skipped_proposal(
            proposal, reason, regime=regime, source=source, features=features, raw_payload=raw_payload
        )
    except Exception as e:
        logging.getLogger(__name__).debug("prediction telemetry (skipped) non-fatal: %s", e)
        return {"error": str(e), "symbol": getattr(proposal, "symbol", "UNKNOWN"), "reason": reason}


# =============================================================================
# P2-013A: Read-only Prediction Outcome Evaluator + Trade Attribution
# =============================================================================

import csv
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Protocol


class PriceSeriesProvider(Protocol):
    """Injectable interface for historical price lookup (fixture or local data)."""

    def get_close_at_or_after(self, symbol: str, ts: str, horizon_minutes: int) -> Optional[float]:
        ...

    def get_mfe_mae_in_window(self, symbol: str, entry_ts: str, horizon_minutes: int, side: str, entry_price: float) -> tuple[Optional[float], Optional[float]]:
        """Return (MFE, MAE) in the horizon window. Side-aware (buy positive good)."""
        ...


def _parse_iso(ts: str) -> Optional[datetime]:
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def load_prediction_telemetry_rows(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Read-only loader for prediction_telemetry.jsonl. Skips headers and bad rows."""
    p = path or TELEMETRY_FILE
    if not p.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    row = json.loads(line)
                    rows.append(row)
                except Exception:
                    continue  # malformed row — safe skip
    except Exception:
        return []
    return rows


def load_journal_rows(journal_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Read-only loader for the trade journal CSV (for attribution)."""
    if journal_path is None:
        try:
            from utils import ROOT, load_config
            cfg = load_config()
            jf = cfg.get("logging", {}).get("journal_file", "journal_coinbase_crypto.csv")
            journal_path = ROOT / jf
        except Exception:
            journal_path = Path("journal_coinbase_crypto.csv")
    if not journal_path.exists():
        return []
    try:
        with open(journal_path, "r", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def _default_price_loader(symbol: str, ref_ts: str, horizon_min: int) -> Optional[float]:
    """Fallback loader using data/manual_prices/sample_prices.jsonl if present."""
    prices_dir = ROOT / "data" / "manual_prices"
    for fname in ("sample_prices.jsonl", "equity_sample_prices.jsonl"):
        p = prices_dir / fname
        if not p.exists():
            continue
        try:
            ref_dt = _parse_iso(ref_ts)
            if not ref_dt:
                return None
            target_dt = ref_dt + timedelta(minutes=horizon_min)
            best = None
            best_delta = None
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        bar = json.loads(line.strip())
                        if bar.get("symbol") != symbol:
                            continue
                        bar_dt = _parse_iso(bar.get("timestamp_utc", ""))
                        if not bar_dt:
                            continue
                        if bar_dt >= target_dt:
                            delta = (bar_dt - target_dt).total_seconds()
                            if best is None or delta < best_delta:
                                best = _safe_float(bar.get("close"))
                                best_delta = delta
                    except Exception:
                        continue
            return best
        except Exception:
            continue
    return None


@dataclass
class OutcomeEvaluation:
    row: Dict[str, Any]
    horizon_min: int
    future_price: Optional[float]
    pct_move: Optional[float]
    direction_outcome: str  # "hit", "miss", "neutral", "insufficient_data"
    mfe: Optional[float]
    mae: Optional[float]
    symbol: str
    strategy: str
    regime: Optional[str]
    decision_status: str


class PredictionOutcomeEvaluator:
    """
    Read-only evaluator. Never writes. Safe on malformed data.
    price_loader(symbol, ref_ts_iso, horizon_min) -> close or None
    """

    def __init__(self, price_loader: Optional[Callable[[str, str, int], Optional[float]]] = None):
        self.price_loader = price_loader or _default_price_loader

    def evaluate_row(self, row: Dict[str, Any], horizons: List[int] = [15, 30, 60, 90]) -> List[OutcomeEvaluation]:
        results: List[OutcomeEvaluation] = []
        if row.get("decision_status") not in ("candidate", "placed", "filled"):
            return results
        symbol = row.get("symbol") or row.get("product_id") or "UNKNOWN"
        ref_price = _safe_float(row.get("reference_price"))
        ref_ts = row.get("timestamp")
        side = (row.get("side") or "").lower()
        regime = row.get("regime")
        strategy = row.get("strategy", "unknown")
        decision = row.get("decision_status", "unknown")

        if not ref_price or not ref_ts:
            return results

        for h in horizons:
            future = self.price_loader(symbol, ref_ts, h)
            if future is None or ref_price <= 0:
                results.append(OutcomeEvaluation(
                    row=row, horizon_min=h, future_price=None, pct_move=None,
                    direction_outcome="insufficient_data", mfe=None, mae=None,
                    symbol=symbol, strategy=strategy, regime=regime, decision_status=decision
                ))
                continue

            pct = (future - ref_price) / ref_price * 100.0
            if side in ("buy", "long"):
                hit = "hit" if pct > 0.1 else ("miss" if pct < -0.1 else "neutral")
            elif side in ("sell", "short"):
                hit = "hit" if pct < -0.1 else ("miss" if pct > 0.1 else "neutral")
            else:
                hit = "neutral"

            # Simple MFE/MAE approximation using only endpoint (full window would require series)
            # For real use with full bars the loader can be upgraded.
            mfe = max(0.0, pct) if side in ("buy", "long") else max(0.0, -pct)
            mae = max(0.0, -pct) if side in ("buy", "long") else max(0.0, pct)

            results.append(OutcomeEvaluation(
                row=row, horizon_min=h, future_price=future, pct_move=round(pct, 4),
                direction_outcome=hit, mfe=round(mfe, 4), mae=round(mae, 4),
                symbol=symbol, strategy=strategy, regime=regime, decision_status=decision
            ))
        return results

    def attribute_to_journal(self, telemetry_rows: List[Dict[str, Any]], journal_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Best-effort join of prediction rows to journal entries/exits."""
        attributed = []
        for trow in telemetry_rows:
            if trow.get("decision_status") not in ("candidate", "placed"):
                continue
            raw_sym = trow.get("symbol") or ""
            sym = raw_sym.replace("-", "/").upper()
            if "/" not in sym and "-" in raw_sym:
                parts = raw_sym.replace("-", "/").upper().split("/")
                sym = f"{parts[0]}/{parts[1]}" if len(parts) == 2 else sym
            strat = trow.get("strategy", "")
            ts = trow.get("timestamp")
            side = (trow.get("side") or "").lower()
            matches = []
            for j in journal_rows:
                jraw = j.get("symbol", "")
                jsym = jraw.replace("-", "/").upper()
                if "/" not in jsym and "-" in jraw:
                    parts = jraw.replace("-", "/").upper().split("/")
                    jsym = f"{parts[0]}/{parts[1]}" if len(parts) == 2 else jsym
                if jsym != sym:
                    continue
                if j.get("strategy", "") != strat:
                    continue
                jts = j.get("timestamp", "")
                # loose time match (±10 min)
                try:
                    dt = _parse_iso(ts)
                    jdt = _parse_iso(jts)
                    if dt and jdt and abs((jdt - dt).total_seconds()) < 600:
                        matches.append(j)
                except Exception:
                    continue
            entry = next((m for m in matches if m.get("action", "").upper() in ("BUY", "SELL", "PLACED")), None)
            exit_row = next((m for m in matches if m.get("action", "").upper() in ("EXIT", "SELL", "COVER")), None)
            attributed.append({
                "telemetry": trow,
                "journal_entry": entry,
                "journal_exit": exit_row,
                "pnl_usd": _safe_float(exit_row.get("pnl_usd")) if exit_row else None,
            })
        return attributed

    def run_evaluation(self, telemetry_path: Optional[Path] = None, journal_path: Optional[Path] = None) -> Dict[str, Any]:
        rows = load_prediction_telemetry_rows(telemetry_path)
        journal = load_journal_rows(journal_path)
        outcomes: List[Dict[str, Any]] = []
        for r in rows:
            evals = self.evaluate_row(r)
            for e in evals:
                outcomes.append(asdict(e))
        attributed = self.attribute_to_journal(rows, journal)
        return {
            "outcomes": outcomes,
            "attributed_trades": attributed,
            "summary": self._compute_summary(outcomes, attributed),
        }

    def _compute_summary(self, outcomes: List[Dict[str, Any]], attributed: List[Dict[str, Any]]) -> Dict[str, Any]:
        by_sym: Dict[str, List] = defaultdict(list)
        by_regime: Dict[str, List] = defaultdict(list)
        by_strat: Dict[str, List] = defaultdict(list)
        for o in outcomes:
            by_sym[o["symbol"]].append(o)
            if o.get("regime"):
                by_regime[o["regime"]].append(o)
            by_strat[o["strategy"]].append(o)

        def hit_rate(lst):
            hits = sum(1 for x in lst if x.get("direction_outcome") == "hit")
            total = sum(1 for x in lst if x.get("direction_outcome") in ("hit", "miss"))
            return round(hits / total, 4) if total else None

        summary = {
            "hit_rate_by_symbol": {s: hit_rate(lst) for s, lst in by_sym.items()},
            "hit_rate_by_regime": {r: hit_rate(lst) for r, lst in by_regime.items()},
            "hit_rate_by_strategy": {s: hit_rate(lst) for s, lst in by_strat.items()},
            "skipped_reasons": {},
            "candidate_to_trade_count": len([a for a in attributed if a.get("journal_entry")]),
            "total_evaluated_outcomes": len(outcomes),
        }

        # Skipped reasons
        skipped = [r for r in load_prediction_telemetry_rows() if r.get("decision_status") == "skipped"]
        reasons = defaultdict(int)
        for s in skipped:
            reasons[s.get("reason") or "unknown"] += 1
        summary["skipped_reasons"] = dict(reasons)

        # Simple P&L attribution where available
        pnl_by_sym = defaultdict(float)
        for a in attributed:
            if a.get("pnl_usd") and a["telemetry"].get("symbol"):
                pnl_by_sym[a["telemetry"]["symbol"]] += a["pnl_usd"]
        summary["pnl_usd_by_symbol"] = dict(pnl_by_sym)
        return summary
