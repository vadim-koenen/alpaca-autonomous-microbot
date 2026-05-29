"""Deterministic baseline predictors and prediction journaling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .feature_snapshot import FEATURE_VERSION, fetch_feature_snapshot
from .schema import bool_to_int, connect, init_db, json_dumps, new_id, utc_now

MODEL_MOMENTUM = "baseline_momentum_v0"
MODEL_SPREAD = "baseline_spread_filter_v0"
MODEL_DEAD_CHOP = "baseline_dead_chop_v0"
MODEL_VERSION = "0.1.0"

RETURN_DIRECTION_TYPES = {
    15: "return_direction_15m",
    30: "return_direction_30m",
    60: "return_direction_60m",
    90: "return_direction_90m",
}

SUPPORTED_PREDICTION_TYPES = {
    *RETURN_DIRECTION_TYPES.values(),
    "would_hit_take_profit_before_stop",
    "dead_chop_probability",
    "spread_safe_probability",
    "market_data_valid_probability",
}


def _clamp_probability(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _features_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    raw = snapshot.get("features_json") or "{}"
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        data = {}
    return data if isinstance(data, dict) else {}


def _momentum_probability(snapshot: dict[str, Any], horizon_minutes: int) -> tuple[float, dict[str, Any]]:
    features = _features_from_snapshot(snapshot)
    momentum_pct = _safe_float(
        features.get("momentum_pct", features.get("momentum_15m_pct", 0.0))
    )
    trend_score = _safe_float(features.get("trend_score", 0.0))
    spread_pct = _safe_float(snapshot.get("spread_pct"), 0.0)
    quote_age = _safe_float(snapshot.get("quote_age_seconds"), 0.0)
    bars_available = int(_safe_float(snapshot.get("bars_available"), 0.0))

    raw = 0.50
    raw += max(-0.15, min(0.15, momentum_pct / 10.0))
    raw += max(-0.08, min(0.08, trend_score * 0.05))
    raw -= min(0.06, spread_pct / 100.0)
    if quote_age > 60:
        raw -= 0.05
    if bars_available <= 0:
        raw -= 0.08
    if horizon_minutes >= 60:
        raw *= 0.98

    reason = {
        "momentum_pct": momentum_pct,
        "trend_score": trend_score,
        "spread_pct": spread_pct,
        "quote_age_seconds": quote_age,
        "bars_available": bars_available,
        "baseline": MODEL_MOMENTUM,
    }
    return _clamp_probability(raw), reason


def _spread_safe_probability(snapshot: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    spread_pct = _safe_float(snapshot.get("spread_pct"), 999.0)
    quote_age = _safe_float(snapshot.get("quote_age_seconds"), 999.0)
    bars_available = int(_safe_float(snapshot.get("bars_available"), 0.0))

    probability = 0.90
    if spread_pct > 0.50:
        probability -= min(0.55, (spread_pct - 0.50) / 2.0)
    if quote_age > 30:
        probability -= min(0.25, (quote_age - 30.0) / 240.0)
    if bars_available <= 0:
        probability -= 0.20

    reason = {
        "spread_pct": spread_pct,
        "quote_age_seconds": quote_age,
        "bars_available": bars_available,
        "baseline": MODEL_SPREAD,
    }
    return _clamp_probability(probability), reason


def _data_valid_probability(snapshot: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    status = (snapshot.get("market_data_status") or "").lower()
    quote_age = _safe_float(snapshot.get("quote_age_seconds"), 999.0)
    price = _safe_float(snapshot.get("price"), 0.0)
    bid = _safe_float(snapshot.get("bid"), 0.0)
    ask = _safe_float(snapshot.get("ask"), 0.0)
    bars_available = int(_safe_float(snapshot.get("bars_available"), 0.0))

    probability = 0.85
    if status in {"stale_quote", "invalid_quote", "no_bars", "spread_too_wide"}:
        probability -= 0.45
    if price <= 0 or bid <= 0 or ask <= 0 or ask < bid:
        probability -= 0.30
    if quote_age > 60:
        probability -= 0.15
    if bars_available <= 0:
        probability -= 0.15

    reason = {
        "market_data_status": status,
        "quote_age_seconds": quote_age,
        "price": price,
        "bid": bid,
        "ask": ask,
        "bars_available": bars_available,
        "baseline": MODEL_SPREAD,
    }
    return _clamp_probability(probability), reason


def _dead_chop_probability(snapshot: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    features = _features_from_snapshot(snapshot)
    spread_pct = _safe_float(snapshot.get("spread_pct"), 0.0)
    realized_volatility_pct = _safe_float(features.get("realized_volatility_pct"), 0.0)
    momentum_abs = abs(_safe_float(features.get("momentum_pct", 0.0)))
    bars_available = int(_safe_float(snapshot.get("bars_available"), 0.0))

    probability = 0.40
    if realized_volatility_pct < 0.20:
        probability += 0.20
    if momentum_abs < 0.05:
        probability += 0.15
    if spread_pct > 0.40:
        probability += 0.10
    if bars_available <= 0:
        probability += 0.10

    reason = {
        "realized_volatility_pct": realized_volatility_pct,
        "momentum_abs_pct": momentum_abs,
        "spread_pct": spread_pct,
        "bars_available": bars_available,
        "baseline": MODEL_DEAD_CHOP,
    }
    return _clamp_probability(probability), reason


def generate_baseline_predictions(
    snapshot: dict[str, Any],
    *,
    horizons: tuple[int, ...] = (15, 30, 60, 90),
) -> list[dict[str, Any]]:
    """Return advisory-only baseline predictions for one snapshot."""
    predictions: list[dict[str, Any]] = []

    for horizon in horizons:
        prediction_type = RETURN_DIRECTION_TYPES.get(horizon)
        if prediction_type is None:
            continue
        value, reason = _momentum_probability(snapshot, horizon)
        predictions.append(
            {
                "prediction_type": prediction_type,
                "prediction_value": value,
                "confidence": abs(value - 0.5) * 2.0,
                "horizon_minutes": horizon,
                "model_name": MODEL_MOMENTUM,
                "model_version": MODEL_VERSION,
                "feature_version": FEATURE_VERSION,
                "reason": reason,
            }
        )

    spread_value, spread_reason = _spread_safe_probability(snapshot)
    predictions.append(
        {
            "prediction_type": "spread_safe_probability",
            "prediction_value": spread_value,
            "confidence": abs(spread_value - 0.5) * 2.0,
            "horizon_minutes": 15,
            "model_name": MODEL_SPREAD,
            "model_version": MODEL_VERSION,
            "feature_version": FEATURE_VERSION,
            "reason": spread_reason,
        }
    )

    data_value, data_reason = _data_valid_probability(snapshot)
    predictions.append(
        {
            "prediction_type": "market_data_valid_probability",
            "prediction_value": data_value,
            "confidence": abs(data_value - 0.5) * 2.0,
            "horizon_minutes": 15,
            "model_name": MODEL_SPREAD,
            "model_version": MODEL_VERSION,
            "feature_version": FEATURE_VERSION,
            "reason": data_reason,
        }
    )

    chop_value, chop_reason = _dead_chop_probability(snapshot)
    predictions.append(
        {
            "prediction_type": "dead_chop_probability",
            "prediction_value": chop_value,
            "confidence": abs(chop_value - 0.5) * 2.0,
            "horizon_minutes": 15,
            "model_name": MODEL_DEAD_CHOP,
            "model_version": MODEL_VERSION,
            "feature_version": FEATURE_VERSION,
            "reason": chop_reason,
        }
    )

    tp_value = _clamp_probability((spread_value + data_value + (1.0 - chop_value)) / 3.0)
    predictions.append(
        {
            "prediction_type": "would_hit_take_profit_before_stop",
            "prediction_value": tp_value,
            "confidence": abs(tp_value - 0.5) * 2.0,
            "horizon_minutes": 90,
            "model_name": MODEL_MOMENTUM,
            "model_version": MODEL_VERSION,
            "feature_version": FEATURE_VERSION,
            "reason": {
                "spread_safe_probability": spread_value,
                "market_data_valid_probability": data_value,
                "dead_chop_probability": chop_value,
                "baseline": MODEL_MOMENTUM,
            },
        }
    )

    return predictions


def record_prediction(
    snapshot_id: str,
    prediction: dict[str, Any],
    *,
    db_path: str | Path | None = None,
    would_trade: bool = False,
    live_trade_taken: bool = False,
) -> str:
    """Persist one advisory prediction for an existing snapshot."""
    init_db(db_path)
    snapshot = fetch_feature_snapshot(snapshot_id, db_path=db_path)
    if snapshot is None:
        raise ValueError(f"unknown shadow snapshot_id: {snapshot_id}")
    prediction_type = prediction["prediction_type"]
    if prediction_type not in SUPPORTED_PREDICTION_TYPES:
        raise ValueError(f"unsupported prediction_type: {prediction_type}")

    prediction_id = prediction.get("prediction_id") or new_id("pred")
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO shadow_predictions (
                prediction_id, snapshot_id, created_at_utc, broker, asset_class,
                symbol, strategy, prediction_type, prediction_value, confidence,
                horizon_minutes, model_name, model_version, feature_version,
                would_trade, live_trade_taken, reason_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prediction_id,
                snapshot_id,
                prediction.get("created_at_utc") or snapshot["created_at_utc"] or utc_now(),
                snapshot["broker"],
                snapshot["asset_class"],
                snapshot["symbol"],
                snapshot["strategy"],
                prediction_type,
                _clamp_probability(prediction["prediction_value"]),
                _clamp_probability(prediction.get("confidence", 0.0)),
                int(prediction["horizon_minutes"]),
                prediction["model_name"],
                prediction.get("model_version", MODEL_VERSION),
                prediction.get("feature_version", FEATURE_VERSION),
                bool_to_int(would_trade),
                bool_to_int(live_trade_taken),
                json_dumps(prediction.get("reason", {})),
            ),
        )
    return prediction_id


def record_baseline_predictions_for_snapshot(
    snapshot_id: str,
    *,
    db_path: str | Path | None = None,
    would_trade: bool = False,
    live_trade_taken: bool = False,
) -> list[str]:
    """Generate and record all baseline predictions for one snapshot."""
    snapshot = fetch_feature_snapshot(snapshot_id, db_path=db_path)
    if snapshot is None:
        raise ValueError(f"unknown shadow snapshot_id: {snapshot_id}")
    prediction_ids = []
    for prediction in generate_baseline_predictions(snapshot):
        prediction_ids.append(
            record_prediction(
                snapshot_id,
                prediction,
                db_path=db_path,
                would_trade=would_trade,
                live_trade_taken=live_trade_taken,
            )
        )
    return prediction_ids
