"""Outcome labeling helpers for advisory shadow predictions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .prediction_journal import SUPPORTED_PREDICTION_TYPES
from .schema import bool_to_int, connect, init_db, json_dumps, utc_now

OUTCOME_STATUSES = {
    "labeled",
    "pending_horizon",
    "missing_data",
    "insufficient_price_history",
    "unsupported_prediction_type",
    "error",
}


@dataclass(frozen=True)
class PriceObservation:
    symbol: str
    timestamp_utc: str
    price: float
    source: str = ""
    terminal: bool = False
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None
    timeframe: str = ""


def _parse_utc(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _price_series_values(future_prices: Iterable[Any] | None) -> list[float]:
    values: list[float] = []
    for item in future_prices or []:
        if isinstance(item, dict):
            raw = item.get("price", item.get("close", item.get("last")))
        else:
            raw = item
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            values.append(value)
    return values


def _price_series_observations(
    observations: Iterable[PriceObservation | dict[str, Any]] | None,
    *,
    symbol: str,
    start: datetime,
    end: datetime,
) -> list[PriceObservation]:
    values: list[PriceObservation] = []
    for item in observations or []:
        if isinstance(item, PriceObservation):
            obs = item
        else:
            raw_symbol = item.get("symbol", "")
            raw_time = item.get("timestamp_utc", item.get("time", item.get("ts", "")))
            raw_price = item.get("price", item.get("close", item.get("last", item.get("exit", item.get("limit")))))
            try:
                raw_price = float(raw_price)
            except (TypeError, ValueError):
                continue
            obs = PriceObservation(
                symbol=str(raw_symbol),
                timestamp_utc=str(raw_time),
                price=raw_price,
                source=str(item.get("source", "")),
                terminal=bool(item.get("terminal", False)),
                open=_coerce_optional_float(item.get("open")),
                high=_coerce_optional_float(item.get("high")),
                low=_coerce_optional_float(item.get("low")),
                close=_coerce_optional_float(item.get("close", raw_price)),
                volume=_coerce_optional_float(item.get("volume")),
                timeframe=str(item.get("timeframe", "")),
            )
        if obs.symbol != symbol or obs.price <= 0:
            continue
        try:
            ts = _parse_utc(obs.timestamp_utc)
        except ValueError:
            continue
        if start < ts <= end:
            values.append(obs)
    return sorted(values, key=lambda obs: _parse_utc(obs.timestamp_utc))


def _coerce_optional_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _obs_close(obs: PriceObservation) -> float:
    return float(obs.close if obs.close is not None else obs.price)


def _obs_high(obs: PriceObservation) -> float:
    close = _obs_close(obs)
    high = obs.high if obs.high is not None else close
    open_price = obs.open if obs.open is not None else close
    return float(max(high, open_price, close))


def _obs_low(obs: PriceObservation) -> float:
    close = _obs_close(obs)
    low = obs.low if obs.low is not None else close
    open_price = obs.open if obs.open is not None else close
    return float(min(low, open_price, close))


def _timeframe_seconds(timeframe: str) -> int:
    value = (timeframe or "").strip().lower()
    if not value:
        return 0
    try:
        if value.endswith("s"):
            return int(float(value[:-1]))
        if value.endswith("m"):
            return int(float(value[:-1]) * 60)
        if value.endswith("h"):
            return int(float(value[:-1]) * 3600)
    except ValueError:
        return 0
    return 0


def _obs_covers_time(obs: PriceObservation, target: datetime) -> bool:
    timestamp = _parse_utc(obs.timestamp_utc)
    if timestamp >= target:
        return True
    seconds = _timeframe_seconds(obs.timeframe)
    return bool(seconds and timestamp + timedelta(seconds=seconds) >= target)


def _fetch_prediction_with_snapshot(
    prediction_id: str,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT p.*, s.price AS entry_price, s.created_at_utc AS snapshot_created_at_utc
            FROM shadow_predictions p
            JOIN shadow_feature_snapshots s ON s.snapshot_id = p.snapshot_id
            WHERE p.prediction_id = ?
            """,
            (prediction_id,),
        ).fetchone()
    return dict(row) if row else None


def fetch_predictions_for_labeling(
    *,
    db_path: str | Path | None = None,
    since_utc: str | None = None,
    broker: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch predictions plus snapshot context that need outcome processing."""
    init_db(db_path)
    clauses = [
        """
        (
            o.prediction_id IS NULL
            OR o.outcome_status IN (
                'pending_horizon',
                'missing_data',
                'insufficient_price_history',
                'error'
            )
        )
        """,
    ]
    params: list[Any] = []
    if since_utc:
        clauses.append("p.created_at_utc >= ?")
        params.append(since_utc)
    if broker:
        clauses.append("p.broker = ?")
        params.append(broker)
    with connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT
                p.*,
                s.price AS entry_price,
                s.created_at_utc AS snapshot_created_at_utc,
                s.market_data_status AS snapshot_market_data_status,
                s.skip_reason AS snapshot_skip_reason,
                o.outcome_status AS existing_outcome_status,
                o.outcome_json AS existing_outcome_json
            FROM shadow_predictions p
            JOIN shadow_feature_snapshots s ON s.snapshot_id = p.snapshot_id
            LEFT JOIN shadow_outcomes o ON o.prediction_id = p.prediction_id
            WHERE {' AND '.join(clauses)}
            ORDER BY p.created_at_utc, p.prediction_id
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def write_outcome(
    *,
    prediction_id: str,
    horizon_minutes: int,
    outcome_status: str,
    db_path: str | Path | None = None,
    future_return_pct: float | None = None,
    max_favorable_excursion_pct: float | None = None,
    max_adverse_excursion_pct: float | None = None,
    hit_take_profit: bool | None = None,
    hit_stop_loss: bool | None = None,
    market_data_available: bool = False,
    outcome_json: dict[str, Any] | None = None,
    labeled_at_utc: str | None = None,
) -> str:
    if outcome_status not in OUTCOME_STATUSES:
        raise ValueError(f"unsupported outcome_status: {outcome_status}")
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO shadow_outcomes (
                prediction_id, labeled_at_utc, horizon_minutes,
                future_return_pct, max_favorable_excursion_pct,
                max_adverse_excursion_pct, hit_take_profit, hit_stop_loss,
                market_data_available, outcome_status, outcome_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prediction_id,
                labeled_at_utc or utc_now(),
                int(horizon_minutes),
                future_return_pct,
                max_favorable_excursion_pct,
                max_adverse_excursion_pct,
                bool_to_int(bool(hit_take_profit)) if hit_take_profit is not None else None,
                bool_to_int(bool(hit_stop_loss)) if hit_stop_loss is not None else None,
                bool_to_int(market_data_available),
                outcome_status,
                json_dumps(outcome_json),
            ),
        )
    return outcome_status


def classify_prediction_outcome(
    prediction: dict[str, Any],
    observations: Iterable[PriceObservation | dict[str, Any]] | None,
    *,
    now: datetime | None = None,
    take_profit_pct: float = 1.0,
    stop_loss_pct: float = 0.75,
) -> dict[str, Any]:
    """Classify one pending prediction using supplied read-only price observations."""
    cutoff_now = now or datetime.now(timezone.utc)
    prediction_type = str(prediction.get("prediction_type", ""))
    horizon_minutes = int(prediction.get("horizon_minutes", 0) or 0)
    created_raw = prediction.get("created_at_utc") or prediction.get("snapshot_created_at_utc")
    try:
        created = _parse_utc(str(created_raw))
    except (TypeError, ValueError):
        return {
            "outcome_status": "error",
            "horizon_minutes": horizon_minutes,
            "market_data_available": False,
            "outcome_json": {"error": "invalid_created_at"},
        }

    if prediction_type not in SUPPORTED_PREDICTION_TYPES:
        return {
            "outcome_status": "unsupported_prediction_type",
            "horizon_minutes": horizon_minutes,
            "market_data_available": False,
            "outcome_json": {"prediction_type": prediction_type},
        }

    horizon_end = created + timedelta(minutes=horizon_minutes)
    if horizon_end > cutoff_now:
        return {
            "outcome_status": "pending_horizon",
            "horizon_minutes": horizon_minutes,
            "market_data_available": False,
            "outcome_json": {
                "created_at_utc": created.isoformat().replace("+00:00", "Z"),
                "horizon_end_utc": horizon_end.isoformat().replace("+00:00", "Z"),
            },
        }

    symbol = str(prediction.get("symbol", ""))
    all_symbol_observations = sorted(
        [
            obs
            for obs in observations or []
            if (
                (obs.symbol if isinstance(obs, PriceObservation) else str(obs.get("symbol", "")))
                == symbol
            )
        ],
        key=lambda obs: _parse_utc(obs.timestamp_utc if isinstance(obs, PriceObservation) else str(obs.get("timestamp_utc", obs.get("time", obs.get("ts", ""))))),
    )
    future_series = _price_series_observations(
        observations,
        symbol=symbol,
        start=created,
        end=horizon_end,
    )
    anchor_series = [
        obs
        for obs in all_symbol_observations
        if _parse_utc(obs.timestamp_utc if isinstance(obs, PriceObservation) else str(obs.get("timestamp_utc", obs.get("time", obs.get("ts", ""))))) <= created
    ]
    anchor = anchor_series[-1] if anchor_series else None

    entry_price = prediction.get("entry_price")
    try:
        entry = float(entry_price)
    except (TypeError, ValueError):
        entry = 0.0
    if anchor is not None:
        entry = _obs_close(anchor)
    elif all_symbol_observations and not any(obs.terminal for obs in future_series):
        return {
            "outcome_status": "insufficient_price_history",
            "horizon_minutes": horizon_minutes,
            "market_data_available": True,
            "outcome_json": {
                "reason": "missing_t0_price",
                "symbol": symbol,
                "observation_count_for_symbol": len(all_symbol_observations),
            },
        }
    if entry <= 0:
        return {
            "outcome_status": "insufficient_price_history",
            "horizon_minutes": horizon_minutes,
            "market_data_available": False,
            "outcome_json": {
                "reason": "missing_t0_price",
                "market_data_status": prediction.get("snapshot_market_data_status", ""),
                "skip_reason": prediction.get("snapshot_skip_reason", ""),
            },
        }

    if not future_series:
        return {
            "outcome_status": "missing_data",
            "horizon_minutes": horizon_minutes,
            "market_data_available": False,
            "outcome_json": {"reason": "no_future_prices", "entry_price": entry},
        }

    has_horizon_price = any(_obs_covers_time(obs, horizon_end) for obs in future_series)
    has_terminal_price = any(obs.terminal for obs in future_series)
    if not has_horizon_price and not has_terminal_price:
        return {
            "outcome_status": "missing_data",
            "horizon_minutes": horizon_minutes,
            "market_data_available": True,
            "outcome_json": {
                "reason": "future_prices_do_not_reach_horizon",
                "entry_price": entry,
                "last_price_time_utc": future_series[-1].timestamp_utc,
                "price_count": len(future_series),
            },
        }

    closes = [_obs_close(obs) for obs in future_series]
    highs = [_obs_high(obs) for obs in future_series]
    lows = [_obs_low(obs) for obs in future_series]
    future_return_pct = ((closes[-1] - entry) / entry) * 100.0
    max_favorable_excursion_pct = ((max(highs) - entry) / entry) * 100.0
    max_adverse_excursion_pct = ((min(lows) - entry) / entry) * 100.0
    hit_take_profit = max_favorable_excursion_pct >= take_profit_pct
    hit_stop_loss = max_adverse_excursion_pct <= -abs(stop_loss_pct)
    return {
        "outcome_status": "labeled",
        "horizon_minutes": horizon_minutes,
        "future_return_pct": future_return_pct,
        "max_favorable_excursion_pct": max_favorable_excursion_pct,
        "max_adverse_excursion_pct": max_adverse_excursion_pct,
        "hit_take_profit": hit_take_profit,
        "hit_stop_loss": hit_stop_loss,
        "market_data_available": True,
        "outcome_json": {
            "entry_price": entry,
            "last_price": closes[-1],
            "max_price": max(highs),
            "min_price": min(lows),
            "price_count": len(future_series),
            "sources": sorted({obs.source for obs in future_series if obs.source}),
            "terminal_observed": has_terminal_price,
            "take_profit_pct": take_profit_pct,
            "stop_loss_pct": stop_loss_pct,
            "entry_source": anchor.source if anchor else "snapshot_entry_price",
        },
    }


def label_prediction(
    prediction_id: str,
    future_prices: Iterable[Any] | None,
    *,
    db_path: str | Path | None = None,
    take_profit_pct: float = 1.0,
    stop_loss_pct: float = 0.75,
    labeled_at_utc: str | None = None,
) -> str:
    """Label one prediction from supplied future prices.

    Missing future data is explicitly recorded as missing_data. No outcome is
    guessed when the future price series is unavailable or unusable.
    """
    row = _fetch_prediction_with_snapshot(prediction_id, db_path=db_path)
    if row is None:
        raise ValueError(f"unknown shadow prediction_id: {prediction_id}")

    entry_price = row.get("entry_price")
    prices = _price_series_values(future_prices)
    status = "missing_data"
    future_return_pct = None
    max_favorable_excursion_pct = None
    max_adverse_excursion_pct = None
    hit_take_profit = None
    hit_stop_loss = None
    outcome_json: dict[str, Any] = {
        "price_count": len(prices),
        "take_profit_pct": take_profit_pct,
        "stop_loss_pct": stop_loss_pct,
    }

    if entry_price and float(entry_price) > 0 and prices:
        entry = float(entry_price)
        returns = [((price - entry) / entry) * 100.0 for price in prices]
        future_return_pct = returns[-1]
        max_favorable_excursion_pct = max(returns)
        max_adverse_excursion_pct = min(returns)
        hit_take_profit = max_favorable_excursion_pct >= take_profit_pct
        hit_stop_loss = max_adverse_excursion_pct <= -abs(stop_loss_pct)
        status = "labeled"
        outcome_json.update(
            {
                "entry_price": entry,
                "last_price": prices[-1],
                "max_price": max(prices),
                "min_price": min(prices),
            }
        )

    write_outcome(
        prediction_id=prediction_id,
        horizon_minutes=int(row["horizon_minutes"]),
        future_return_pct=future_return_pct,
        max_favorable_excursion_pct=max_favorable_excursion_pct,
        max_adverse_excursion_pct=max_adverse_excursion_pct,
        hit_take_profit=hit_take_profit,
        hit_stop_loss=hit_stop_loss,
        market_data_available=status == "labeled",
        outcome_status=status,
        outcome_json=outcome_json,
        db_path=db_path,
        labeled_at_utc=labeled_at_utc,
    )
    return status


def pending_prediction_ids(
    *,
    db_path: str | Path | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Return predictions whose horizon has expired and has no outcome."""
    init_db(db_path)
    cutoff_now = now or datetime.now(timezone.utc)
    due: list[str] = []
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT p.prediction_id, p.created_at_utc, p.horizon_minutes
            FROM shadow_predictions p
            LEFT JOIN shadow_outcomes o ON o.prediction_id = p.prediction_id
            WHERE o.prediction_id IS NULL
            """
        ).fetchall()
    for row in rows:
        created = _parse_utc(row["created_at_utc"])
        if created + timedelta(minutes=int(row["horizon_minutes"])) <= cutoff_now:
            due.append(row["prediction_id"])
    return due
