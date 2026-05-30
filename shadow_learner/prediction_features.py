"""Prediction feature assembly for the advisory shadow learner.

This module orchestrates the generation of feature vectors for specific symbols
and timestamps, using raw DB data and derivative calculations.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .derivative_features import (
    calculate_acceleration,
    calculate_high_low_range_pct,
    calculate_return_pct,
    calculate_velocity,
    calculate_volatility,
    calculate_spread_trend,
    calculate_mfe_mae_ratio,
    calculate_win_rate,
)
from .price_history import fetch_price_observations
from .schema import connect, init_db


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assemble_symbol_features(
    symbol: str,
    target_time_utc: str | datetime,
    *,
    db_path: str | Path | None = None,
    lookback_minutes: int = 120,
) -> dict[str, Any]:
    """Assembles a derivative feature vector for a symbol at a specific T0."""
    t0 = target_time_utc if isinstance(target_time_utc, datetime) else _parse_utc(target_time_utc)
    since_utc = (t0 - timedelta(minutes=lookback_minutes)).isoformat().replace("+00:00", "Z")
    
    observations = fetch_price_observations(
        db_path=db_path,
        since_utc=since_utc,
        symbol=symbol,
    )
    
    # Filter to at or before T0
    prior = [obs for obs in observations if _parse_utc(obs.timestamp_utc) <= t0]
    if not prior:
        return {"error": "no_prior_prices", "symbol": symbol, "t0": t0.isoformat()}

    latest_price = prior[-1].price
    
    def _get_price_at(minutes_ago: int) -> float | None:
        target = t0 - timedelta(minutes=minutes_ago)
        # Find closest observation at or before target
        match = [obs for obs in prior if _parse_utc(obs.timestamp_utc) <= target]
        return match[-1].price if match else None

    def _get_window_prices(minutes_window: int) -> list[float]:
        start = t0 - timedelta(minutes=minutes_window)
        return [obs.price for obs in prior if start <= _parse_utc(obs.timestamp_utc) <= t0]

    def _get_window_obs(minutes_window: int) -> list[Any]:
        start = t0 - timedelta(minutes=minutes_window)
        return [obs for obs in prior if start <= _parse_utc(obs.timestamp_utc) <= t0]

    features: dict[str, Any] = {
        "symbol": symbol,
        "t0_utc": t0.isoformat().replace("+00:00", "Z"),
        "price_t0": latest_price,
    }

    # Returns
    features["return_1m"] = calculate_return_pct(_get_price_at(1), latest_price)
    features["return_5m"] = calculate_return_pct(_get_price_at(5), latest_price)
    features["return_15m"] = calculate_return_pct(_get_price_at(15), latest_price)
    features["return_30m"] = calculate_return_pct(_get_price_at(30), latest_price)
    features["return_60m"] = calculate_return_pct(_get_price_at(60), latest_price)

    # Velocity
    v5 = calculate_velocity(_get_window_prices(5), 5)
    v15 = calculate_velocity(_get_window_prices(15), 15)
    features["price_velocity_5m"] = v5
    features["price_velocity_15m"] = v15

    # Acceleration (v15 - v_prior_15) / 15
    # Simplified: (v5 - v_prev_5) / 5 where v_prev_5 is velocity from T-10 to T-5
    v5_prior = calculate_velocity([obs.price for obs in prior if t0 - timedelta(minutes=10) <= _parse_utc(obs.timestamp_utc) <= t0 - timedelta(minutes=5)], 5)
    features["price_acceleration_15m"] = calculate_acceleration(v5_prior, v5, 5)

    # Volatility & Range
    features["volatility_15m"] = calculate_volatility(_get_window_prices(15))
    features["volatility_60m"] = calculate_volatility(_get_window_prices(60))
    
    obs15 = _get_window_obs(15)
    highs = [obs.high for obs in obs15 if obs.high is not None]
    lows = [obs.low for obs in obs15 if obs.low is not None]
    features["high_low_range_15m"] = calculate_high_low_range_pct(highs, lows, latest_price)

    # Spread trend
    spreads = [obs.price * 0.001 for obs in obs15] # Mock if missing, but we should check if snapshots have it
    # Real spread trend needs to join with shadow_feature_snapshots
    features["spread_trend"] = None # Placeholder, report will explain

    # Outcomes-based features (Win Rate, Brier)
    perf = get_symbol_performance_metrics(symbol, t0, db_path=db_path)
    features.update(perf)

    return features


def get_symbol_performance_metrics(symbol: str, t0: datetime, db_path: str | Path | None = None) -> dict[str, Any]:
    """Calculate recent win rate and MFE/MAE ratio for a symbol."""
    init_db(db_path)
    since = (t0 - timedelta(days=7)).isoformat().replace("+00:00", "Z")
    
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT o.future_return_pct, o.max_favorable_excursion_pct, o.max_adverse_excursion_pct
            FROM shadow_outcomes o
            JOIN shadow_predictions p ON p.prediction_id = o.prediction_id
            WHERE p.symbol = ? AND p.created_at_utc <= ? AND p.created_at_utc >= ?
              AND o.outcome_status = 'labeled'
            """,
            (symbol, t0.isoformat().replace("+00:00", "Z"), since),
        ).fetchall()
    
    if not rows:
        return {
            "recent_win_rate_by_symbol": None,
            "mfe_mae_ratio": None,
        }
    
    returns = [r["future_return_pct"] for r in rows]
    mfes = [r["max_favorable_excursion_pct"] for r in rows if r["max_favorable_excursion_pct"] is not None]
    maes = [r["max_adverse_excursion_pct"] for r in rows if r["max_adverse_excursion_pct"] is not None]
    
    avg_mfe = sum(mfes) / len(mfes) if mfes else None
    avg_mae = sum(maes) / len(maes) if maes else None
    
    return {
        "recent_win_rate_by_symbol": calculate_win_rate(returns),
        "mfe_mae_ratio": calculate_mfe_mae_ratio(avg_mfe, avg_mae),
    }


# NOTE: This function has no T0 time gate. Advisory/evaluation use only.
# If ever used for live feature assembly, add a cutoff parameter.
def get_brier_metrics(db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Calculates recent Brier metrics for all model/symbol/horizon buckets."""
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT p.model_name, p.symbol, p.horizon_minutes, p.prediction_value, o.future_return_pct
            FROM shadow_predictions p
            JOIN shadow_outcomes o ON o.prediction_id = p.prediction_id
            WHERE o.outcome_status = 'labeled'
            """
        ).fetchall()
        
    buckets = {}
    for r in rows:
        key = (r["model_name"], r["symbol"], r["horizon_minutes"])
        if key not in buckets:
            buckets[key] = {"preds": [], "actuals": []}
        buckets[key]["preds"].append(r["prediction_value"])
        buckets[key]["actuals"].append(1 if r["future_return_pct"] > 0 else 0)
        
    results = []
    for (model, symbol, horizon), data in buckets.items():
        brier = 0.0
        for p, a in zip(data["preds"], data["actuals"]):
            brier += (p - a) ** 2
        brier /= len(data["preds"])
        results.append({
            "model": model,
            "symbol": symbol,
            "horizon": horizon,
            "brier": brier,
            "samples": len(data["preds"]),
        })
    return results
