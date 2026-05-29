"""Retrospective advisory directional baselines for shadow snapshots.

These generators are intentionally read-only with respect to live trading:
they read only shadow learner snapshots, price points, and existing prediction
rows, then write advisory predictions back to shadow_predictions.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .price_coverage import since_to_utc
from .schema import bool_to_int, connect, init_db, json_dumps, utc_now

MODEL_MOMENTUM = "retrospective_momentum_v0"
MODEL_MEAN_REVERSION = "retrospective_mean_reversion_v0"
MODEL_RANDOM = "retrospective_random_baseline_v0"
MODEL_VERSION = "0.1.0"
FEATURE_VERSION = "retrospective_price_context_v0"
HORIZON_TYPES = {
    15: "return_direction_15m",
    30: "return_direction_30m",
    60: "return_direction_60m",
    90: "return_direction_90m",
}
LOOKBACK_MINUTES = 60


@dataclass(frozen=True)
class PriorPrice:
    timestamp_utc: str
    close: float
    source: str
    timeframe: str


@dataclass(frozen=True)
class PriceContext:
    anchor_price: float
    anchor_source: str
    prior_price: float | None
    recent_return_pct: float | None
    lookback_points: int
    max_price_timestamp_used: str | None
    feature_source: str
    insufficient_features_reason: str | None = None


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _clamp_probability(value: float) -> float:
    return _clamp(value, 0.0, 1.0)


def _stable_prediction_id(
    *,
    snapshot_id: str,
    symbol: str,
    horizon_minutes: int,
    model_name: str,
    model_version: str,
) -> str:
    digest = hashlib.sha256(
        f"{snapshot_id}|{symbol}|{horizon_minutes}|{model_name}|{model_version}".encode("utf-8")
    ).hexdigest()[:32]
    return f"pred_retro_{digest}"


def _snapshot_features(snapshot: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = json.loads(snapshot.get("features_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _load_snapshots(
    conn,
    *,
    since_utc: str | None,
    broker: str | None,
    symbol: str | None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if since_utc:
        clauses.append("created_at_utc >= ?")
        params.append(since_utc)
    if broker:
        clauses.append("broker = ?")
        params.append(broker)
    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol.upper())
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    rows = conn.execute(
        f"""
        SELECT *
        FROM shadow_feature_snapshots
        {where}
        ORDER BY created_at_utc, snapshot_id
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def _prior_prices_for_snapshot(
    conn,
    *,
    symbol: str,
    t0: datetime,
    lookback_minutes: int = LOOKBACK_MINUTES,
) -> list[PriorPrice]:
    lookback_start = (t0 - timedelta(minutes=lookback_minutes)).isoformat().replace("+00:00", "Z")
    t0_utc = t0.isoformat().replace("+00:00", "Z")
    rows = conn.execute(
        """
        SELECT timestamp_utc, close, source, timeframe
        FROM shadow_price_points
        WHERE symbol = ?
          AND timestamp_utc <= ?
          AND timestamp_utc >= ?
        ORDER BY timestamp_utc
        """,
        (symbol, t0_utc, lookback_start),
    ).fetchall()
    prices: list[PriorPrice] = []
    for row in rows:
        close = _safe_float(row["close"])
        if close is None:
            continue
        prices.append(
            PriorPrice(
                timestamp_utc=row["timestamp_utc"],
                close=close,
                source=row["source"],
                timeframe=row["timeframe"],
            )
        )
    return prices


def build_price_context(snapshot: dict[str, Any], prior_prices: list[PriorPrice]) -> PriceContext | None:
    """Build a t0/prior-only feature context for one snapshot."""
    snapshot_price = _safe_float(snapshot.get("price"))
    features = _snapshot_features(snapshot)
    feature_momentum = _safe_float(
        features.get("momentum_pct", features.get("momentum_15m_pct"))
    )

    anchor_price = snapshot_price
    anchor_source = "snapshot_price"
    if anchor_price is None and prior_prices:
        anchor_price = prior_prices[-1].close
        anchor_source = "shadow_price_points"
    if anchor_price is None:
        return None

    prior_price: float | None = None
    recent_return_pct: float | None = None
    insufficient_reason: str | None = None
    if len(prior_prices) >= 2:
        prior_price = prior_prices[0].close
        recent_return_pct = ((anchor_price - prior_price) / prior_price) * 100.0
        feature_source = f"{anchor_source}+shadow_price_points"
    elif feature_momentum is not None:
        recent_return_pct = feature_momentum
        feature_source = f"{anchor_source}+snapshot_features"
        insufficient_reason = "price_point_lookback_sparse_used_snapshot_momentum"
    else:
        feature_source = anchor_source
        insufficient_reason = "no_prior_price_momentum_context"

    max_timestamp = prior_prices[-1].timestamp_utc if prior_prices else None
    return PriceContext(
        anchor_price=anchor_price,
        anchor_source=anchor_source,
        prior_price=prior_price,
        recent_return_pct=recent_return_pct,
        lookback_points=len(prior_prices),
        max_price_timestamp_used=max_timestamp,
        feature_source=feature_source,
        insufficient_features_reason=insufficient_reason,
    )


def _confidence(probability: float, *, context: PriceContext) -> float:
    base = abs(probability - 0.5) * 2.0
    if context.lookback_points >= 10:
        return min(0.35, base)
    if context.lookback_points >= 2:
        return min(0.25, base)
    return min(0.08, base)


def _model_probability(model_name: str, context: PriceContext) -> tuple[float, dict[str, Any]]:
    recent_return = context.recent_return_pct
    reason: dict[str, Any] = {
        "recent_return_pct": recent_return,
        "anchor_price": context.anchor_price,
        "anchor_source": context.anchor_source,
        "prior_price": context.prior_price,
        "lookback_points": context.lookback_points,
        "max_price_timestamp_used": context.max_price_timestamp_used,
        "lookback_minutes": LOOKBACK_MINUTES,
        "model_name": model_name,
    }
    if context.insufficient_features_reason:
        reason["insufficient_features_reason"] = context.insufficient_features_reason

    if model_name == MODEL_RANDOM:
        reason["baseline_role"] = "calibration_control"
        return 0.5, reason

    if recent_return is None:
        reason["insufficient_features_reason"] = (
            context.insufficient_features_reason or "no_recent_return_context"
        )
        return 0.5, reason

    if model_name == MODEL_MOMENTUM:
        adjustment = _clamp(recent_return * 0.08, -0.12, 0.12)
        return _clamp_probability(0.5 + adjustment), reason

    if model_name == MODEL_MEAN_REVERSION:
        if abs(recent_return) < 0.20:
            reason["weak_signal"] = "recent_return_below_reversion_threshold"
            return 0.5, reason
        adjustment = _clamp(abs(recent_return) * 0.06, 0.02, 0.10)
        value = 0.5 - adjustment if recent_return > 0 else 0.5 + adjustment
        return _clamp_probability(value), reason

    raise ValueError(f"unsupported retrospective model: {model_name}")


def _existing_prediction(
    conn,
    *,
    snapshot_id: str,
    symbol: str,
    horizon_minutes: int,
    model_name: str,
    model_version: str,
) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM shadow_predictions
        WHERE snapshot_id = ?
          AND symbol = ?
          AND horizon_minutes = ?
          AND model_name = ?
          AND model_version = ?
          AND prediction_type LIKE 'return_direction_%'
        LIMIT 1
        """,
        (snapshot_id, symbol, horizon_minutes, model_name, model_version),
    ).fetchone()
    return row is not None


def _prediction_rows_for_snapshot(
    *,
    snapshot: dict[str, Any],
    context: PriceContext,
    generated_at_utc: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for model_name in (MODEL_MOMENTUM, MODEL_MEAN_REVERSION, MODEL_RANDOM):
        probability, model_reason = _model_probability(model_name, context)
        confidence = 0.0 if model_name == MODEL_RANDOM else _confidence(probability, context=context)
        for horizon, prediction_type in HORIZON_TYPES.items():
            prediction_id = _stable_prediction_id(
                snapshot_id=snapshot["snapshot_id"],
                symbol=snapshot["symbol"],
                horizon_minutes=horizon,
                model_name=model_name,
                model_version=MODEL_VERSION,
            )
            reason = {
                **model_reason,
                "retrospective_generated": True,
                "generated_at_utc": generated_at_utc,
                "uses_only_t0_or_prior_data": True,
                "feature_source": context.feature_source,
                "snapshot_created_at_utc": snapshot["created_at_utc"],
                "prediction_horizon_minutes": horizon,
            }
            rows.append(
                {
                    "prediction_id": prediction_id,
                    "snapshot_id": snapshot["snapshot_id"],
                    "created_at_utc": snapshot["created_at_utc"],
                    "broker": snapshot["broker"],
                    "asset_class": snapshot["asset_class"],
                    "symbol": snapshot["symbol"],
                    "strategy": snapshot["strategy"],
                    "prediction_type": prediction_type,
                    "prediction_value": probability,
                    "confidence": confidence,
                    "horizon_minutes": horizon,
                    "model_name": model_name,
                    "model_version": MODEL_VERSION,
                    "feature_version": FEATURE_VERSION,
                    "would_trade": 0,
                    "live_trade_taken": 0,
                    "reason_json": json_dumps(reason),
                }
            )
    return rows


def generate_retrospective_predictions(
    *,
    db_path: str | Path | None = None,
    since: str | None = None,
    broker: str | None = None,
    symbol: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Generate advisory-only retrospective directional baseline predictions."""
    since_utc = since_to_utc(since)
    target_symbol = symbol.upper() if symbol else None
    generated_at_utc = utc_now()
    init_db(db_path)
    summary: dict[str, Any] = {
        "dry_run": dry_run,
        "since_utc": since_utc,
        "broker": broker or "all",
        "symbol": target_symbol or "all",
        "snapshots_seen": 0,
        "snapshots_with_context": 0,
        "snapshots_skipped": 0,
        "skipped_no_price_context": 0,
        "predictions_planned": 0,
        "inserted": 0,
        "existing": 0,
        "by_model": Counter(),
        "by_symbol": Counter(),
        "by_horizon": Counter(),
        "skip_reasons": Counter(),
    }

    with connect(db_path) as conn:
        snapshots = _load_snapshots(
            conn,
            since_utc=since_utc,
            broker=broker,
            symbol=target_symbol,
        )
        summary["snapshots_seen"] = len(snapshots)
        for snapshot in snapshots:
            try:
                t0 = _parse_utc(snapshot["created_at_utc"])
            except (TypeError, ValueError):
                summary["snapshots_skipped"] += 1
                summary["skip_reasons"]["invalid_snapshot_timestamp"] += 1
                continue
            prior_prices = _prior_prices_for_snapshot(
                conn,
                symbol=snapshot["symbol"],
                t0=t0,
            )
            context = build_price_context(snapshot, prior_prices)
            if context is None:
                summary["snapshots_skipped"] += 1
                summary["skipped_no_price_context"] += 1
                summary["skip_reasons"]["no_usable_t0_or_prior_price_context"] += 1
                continue

            summary["snapshots_with_context"] += 1
            rows = _prediction_rows_for_snapshot(
                snapshot=snapshot,
                context=context,
                generated_at_utc=generated_at_utc,
            )
            for row in rows:
                exists = _existing_prediction(
                    conn,
                    snapshot_id=row["snapshot_id"],
                    symbol=row["symbol"],
                    horizon_minutes=int(row["horizon_minutes"]),
                    model_name=row["model_name"],
                    model_version=row["model_version"],
                )
                summary["by_model"][row["model_name"]] += 1
                summary["by_symbol"][row["symbol"]] += 1
                summary["by_horizon"][str(row["horizon_minutes"])] += 1
                if exists:
                    summary["existing"] += 1
                    continue
                summary["predictions_planned"] += 1
                if dry_run:
                    continue
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO shadow_predictions (
                        prediction_id, snapshot_id, created_at_utc, broker,
                        asset_class, symbol, strategy, prediction_type,
                        prediction_value, confidence, horizon_minutes,
                        model_name, model_version, feature_version, would_trade,
                        live_trade_taken, reason_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["prediction_id"],
                        row["snapshot_id"],
                        row["created_at_utc"],
                        row["broker"],
                        row["asset_class"],
                        row["symbol"],
                        row["strategy"],
                        row["prediction_type"],
                        row["prediction_value"],
                        row["confidence"],
                        row["horizon_minutes"],
                        row["model_name"],
                        row["model_version"],
                        row["feature_version"],
                        bool_to_int(False),
                        bool_to_int(False),
                        row["reason_json"],
                    ),
                )
                if cursor.rowcount:
                    summary["inserted"] += 1

    return summary


def compact_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-friendly copy of a generation summary."""
    result = dict(summary)
    for key in ("by_model", "by_symbol", "by_horizon", "skip_reasons"):
        result[key] = dict(summary.get(key, {}))
    return result
