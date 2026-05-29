"""Prospective shadow-only directional baselines for newly ingested snapshots.

These generators are advisory-only. They read shadow learner snapshots and
shadow price points, then write only to shadow_predictions. They are designed
for offline log/state ingestion and have no live trading side effects.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .feature_snapshot import FeatureSnapshot
from .retrospective_predictions import (
    HORIZON_TYPES,
    LOOKBACK_MINUTES,
    PriceContext,
    PriorPrice,
    build_price_context,
)
from .schema import bool_to_int, connect, init_db, json_dumps, utc_now

MODEL_MOMENTUM = "prospective_momentum_v0"
MODEL_MEAN_REVERSION = "prospective_mean_reversion_v0"
MODEL_RANDOM = "prospective_random_baseline_v0"
MODEL_VERSION = "0.1.0"
FEATURE_VERSION = "prospective_price_context_v0"


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
    return f"pred_prosp_{digest}"


def snapshot_row_from_feature_snapshot(
    snapshot: FeatureSnapshot,
    *,
    snapshot_id: str | None = None,
) -> dict[str, Any]:
    """Return the database-shaped snapshot row used by the generator."""
    return {
        "snapshot_id": snapshot_id or snapshot.snapshot_id,
        "created_at_utc": snapshot.created_at_utc,
        "broker": snapshot.broker,
        "asset_class": snapshot.asset_class,
        "symbol": snapshot.symbol,
        "strategy": snapshot.strategy,
        "price": snapshot.price,
        "bid": snapshot.bid,
        "ask": snapshot.ask,
        "spread_pct": snapshot.spread_pct,
        "quote_age_seconds": snapshot.quote_age_seconds,
        "bars_available": snapshot.bars_available,
        "market_session": snapshot.market_session,
        "market_data_status": snapshot.market_data_status,
        "skip_reason": snapshot.skip_reason,
        "risk_block_reason": snapshot.risk_block_reason,
        "features_json": json_dumps(snapshot.features),
    }


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

    raise ValueError(f"unsupported prospective model: {model_name}")


def prediction_rows_for_snapshot(
    *,
    snapshot: dict[str, Any],
    prior_prices: Iterable[PriorPrice] = (),
    generated_at_utc: str | None = None,
    generation_source: str = "shadow_ingest_logs",
) -> tuple[list[dict[str, Any]], str | None]:
    """Build prospective rows for one snapshot without writing them."""
    context = build_price_context(snapshot, list(prior_prices))
    if context is None:
        return [], "no_usable_t0_or_prior_price_context"

    generated_at = generated_at_utc or utc_now()
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
                "prospective_shadow_generated": True,
                "retrospective_generated": False,
                "generated_at_utc": generated_at,
                "uses_only_t0_or_prior_data": True,
                "feature_source": context.feature_source,
                "generation_source": generation_source,
                "snapshot_created_at_utc": snapshot["created_at_utc"],
                "prediction_horizon_minutes": horizon,
                "advisory_only": True,
                "no_live_trading_influence": True,
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
    return rows, None


def prediction_rows_for_snapshot_with_db_context(
    conn,
    *,
    snapshot: dict[str, Any],
    generated_at_utc: str | None = None,
    generation_source: str = "shadow_ingest_logs",
) -> tuple[list[dict[str, Any]], str | None]:
    """Build prospective rows using only DB price points at or before t0."""
    try:
        t0 = _parse_utc(snapshot["created_at_utc"])
    except (TypeError, ValueError):
        return [], "invalid_snapshot_timestamp"
    prior_prices = _prior_prices_for_snapshot(conn, symbol=snapshot["symbol"], t0=t0)
    return prediction_rows_for_snapshot(
        snapshot=snapshot,
        prior_prices=prior_prices,
        generated_at_utc=generated_at_utc,
        generation_source=generation_source,
    )


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


def generate_prospective_predictions_for_snapshot(
    snapshot_id: str,
    *,
    db_path: str | Path | None = None,
    dry_run: bool = False,
    generation_source: str = "shadow_ingest_logs",
) -> dict[str, Any]:
    """Generate prospective shadow-only predictions for one persisted snapshot."""
    generated_at_utc = utc_now()
    summary: dict[str, Any] = {
        "dry_run": dry_run,
        "snapshot_id": snapshot_id,
        "snapshots_seen": 0,
        "snapshots_with_context": 0,
        "snapshots_skipped": 0,
        "skipped_no_price_context": 0,
        "predictions_planned": 0,
        "inserted": 0,
        "existing": 0,
        "by_model": Counter(),
        "by_horizon": Counter(),
        "skip_reasons": Counter(),
    }
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM shadow_feature_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        if row is None:
            summary["snapshots_skipped"] += 1
            summary["skip_reasons"]["snapshot_not_found"] += 1
            return summary

        snapshot = dict(row)
        summary["snapshots_seen"] = 1
        rows, skip_reason = prediction_rows_for_snapshot_with_db_context(
            conn,
            snapshot=snapshot,
            generated_at_utc=generated_at_utc,
            generation_source=generation_source,
        )
        if skip_reason:
            summary["snapshots_skipped"] += 1
            summary["skipped_no_price_context"] += 1
            summary["skip_reasons"][skip_reason] += 1
            return summary

        summary["snapshots_with_context"] = 1
        for prediction in rows:
            summary["by_model"][prediction["model_name"]] += 1
            summary["by_horizon"][str(prediction["horizon_minutes"])] += 1
            exists = _existing_prediction(
                conn,
                snapshot_id=prediction["snapshot_id"],
                symbol=prediction["symbol"],
                horizon_minutes=int(prediction["horizon_minutes"]),
                model_name=prediction["model_name"],
                model_version=prediction["model_version"],
            )
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
                    prediction["prediction_id"],
                    prediction["snapshot_id"],
                    prediction["created_at_utc"],
                    prediction["broker"],
                    prediction["asset_class"],
                    prediction["symbol"],
                    prediction["strategy"],
                    prediction["prediction_type"],
                    prediction["prediction_value"],
                    prediction["confidence"],
                    prediction["horizon_minutes"],
                    prediction["model_name"],
                    prediction["model_version"],
                    prediction["feature_version"],
                    bool_to_int(False),
                    bool_to_int(False),
                    prediction["reason_json"],
                ),
            )
            if cursor.rowcount:
                summary["inserted"] += 1
    return summary


def compact_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-friendly copy of a generation summary."""
    result = dict(summary)
    for key in ("by_model", "by_horizon", "skip_reasons"):
        result[key] = dict(summary.get(key, {}))
    return result
