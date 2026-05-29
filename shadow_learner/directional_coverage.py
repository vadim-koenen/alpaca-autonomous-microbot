"""Directional prediction coverage audit for the advisory shadow learner."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .price_coverage import (
    MIN_DIRECTIONAL_LABELS_FOR_EVALUATION,
    MIN_SYMBOL_HORIZON_LABELS_FOR_EVALUATION,
    since_to_utc,
)
from .schema import connect, init_db

DIRECTIONAL_PREFIX = "return_direction_%"
GATE_OPEN = "EVALUATION_GATE_OPEN"
GATE_BLOCKED_PRICE = "EVALUATION_GATE_BLOCKED_PRICE_COVERAGE"
GATE_BLOCKED_NO_DIRECTIONAL = "EVALUATION_GATE_BLOCKED_NO_DIRECTIONAL_PREDICTIONS"
GATE_BLOCKED_SAMPLE = "EVALUATION_GATE_BLOCKED_SAMPLE_SIZE"
GATE_BLOCKED_UNSUPPORTED = "EVALUATION_GATE_BLOCKED_UNSUPPORTED_TYPES"


def _filter_clause(
    alias: str,
    *,
    since_utc: str | None,
    broker: str | None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if since_utc:
        clauses.append(f"{alias}.created_at_utc >= ?")
        params.append(since_utc)
    if broker:
        clauses.append(f"{alias}.broker = ?")
        params.append(broker)
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


def _rows(conn, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _count(rows: list[dict[str, Any]], status: str) -> int:
    return sum(int(row["count"]) for row in rows if row.get("outcome_status") == status)


def build_directional_coverage(
    *,
    db_path: str | Path | None = None,
    since: str | None = None,
    broker: str | None = None,
) -> dict[str, Any]:
    since_utc = since_to_utc(since)
    init_db(db_path)
    pred_where, pred_params = _filter_clause("p", since_utc=since_utc, broker=broker)
    snap_where, snap_params = _filter_clause("s", since_utc=since_utc, broker=broker)

    with connect(db_path) as conn:
        predictions_by_type = _rows(
            conn,
            f"""
            SELECT p.prediction_type, COUNT(*) AS count
            FROM shadow_predictions p
            {pred_where}
            GROUP BY p.prediction_type
            ORDER BY count DESC, p.prediction_type
            """,
            pred_params,
        )
        outcomes_by_type_status = _rows(
            conn,
            f"""
            SELECT p.prediction_type,
                   COALESCE(o.outcome_status, 'unlabeled') AS outcome_status,
                   COUNT(*) AS count
            FROM shadow_predictions p
            LEFT JOIN shadow_outcomes o ON o.prediction_id = p.prediction_id
            {pred_where}
            GROUP BY p.prediction_type, COALESCE(o.outcome_status, 'unlabeled')
            ORDER BY p.prediction_type, outcome_status
            """,
            pred_params,
        )
        directional_by_broker_symbol_horizon = _rows(
            conn,
            f"""
            SELECT p.broker, p.symbol, p.horizon_minutes, COUNT(*) AS count
            FROM shadow_predictions p
            {pred_where + (' AND' if pred_where else 'WHERE')}
              p.prediction_type LIKE ?
            GROUP BY p.broker, p.symbol, p.horizon_minutes
            ORDER BY p.broker, p.symbol, p.horizon_minutes
            """,
            pred_params + [DIRECTIONAL_PREFIX],
        )
        non_directional_by_broker_symbol_horizon = _rows(
            conn,
            f"""
            SELECT p.broker, p.symbol, p.horizon_minutes, COUNT(*) AS count
            FROM shadow_predictions p
            {pred_where + (' AND' if pred_where else 'WHERE')}
              p.prediction_type NOT LIKE ?
            GROUP BY p.broker, p.symbol, p.horizon_minutes
            ORDER BY p.broker, p.symbol, p.horizon_minutes
            """,
            pred_params + [DIRECTIONAL_PREFIX],
        )
        directional_outcomes_by_status = _rows(
            conn,
            f"""
            SELECT COALESCE(o.outcome_status, 'unlabeled') AS outcome_status,
                   COUNT(*) AS count
            FROM shadow_predictions p
            LEFT JOIN shadow_outcomes o ON o.prediction_id = p.prediction_id
            {pred_where + (' AND' if pred_where else 'WHERE')}
              p.prediction_type LIKE ?
            GROUP BY COALESCE(o.outcome_status, 'unlabeled')
            ORDER BY outcome_status
            """,
            pred_params + [DIRECTIONAL_PREFIX],
        )
        directional_outcomes_by_symbol_horizon = _rows(
            conn,
            f"""
            SELECT p.broker,
                   p.symbol,
                   p.horizon_minutes,
                   COALESCE(o.outcome_status, 'unlabeled') AS outcome_status,
                   COUNT(*) AS count
            FROM shadow_predictions p
            LEFT JOIN shadow_outcomes o ON o.prediction_id = p.prediction_id
            {pred_where + (' AND' if pred_where else 'WHERE')}
              p.prediction_type LIKE ?
            GROUP BY p.broker, p.symbol, p.horizon_minutes, COALESCE(o.outcome_status, 'unlabeled')
            ORDER BY p.broker, p.symbol, p.horizon_minutes, outcome_status
            """,
            pred_params + [DIRECTIONAL_PREFIX],
        )
        symbols_with_snapshots_no_directional = _rows(
            conn,
            f"""
            SELECT s.broker, s.symbol, COUNT(DISTINCT s.snapshot_id) AS snapshot_count
            FROM shadow_feature_snapshots s
            LEFT JOIN shadow_predictions p
              ON p.snapshot_id = s.snapshot_id
             AND p.prediction_type LIKE ?
            {snap_where + (' AND' if snap_where else 'WHERE')}
              p.prediction_id IS NULL
            GROUP BY s.broker, s.symbol
            ORDER BY s.broker, s.symbol
            """,
            [DIRECTIONAL_PREFIX] + snap_params,
        )
        symbols_with_price_no_directional = _rows(
            conn,
            f"""
            SELECT pp.symbol,
                   COUNT(*) AS price_points,
                   MIN(pp.timestamp_utc) AS first_timestamp_utc,
                   MAX(pp.timestamp_utc) AS last_timestamp_utc
            FROM shadow_price_points pp
            WHERE {('pp.timestamp_utc >= ? AND ' if since_utc else '')}
                  NOT EXISTS (
                    SELECT 1
                    FROM shadow_predictions p
                    WHERE p.symbol = pp.symbol
                      AND p.prediction_type LIKE ?
                      {('AND p.created_at_utc >= ?' if since_utc else '')}
                      {('AND p.broker = ?' if broker else '')}
                  )
            GROUP BY pp.symbol
            ORDER BY pp.symbol
            """,
            ([since_utc] if since_utc else [])
            + [DIRECTIONAL_PREFIX]
            + ([since_utc] if since_utc else [])
            + ([broker] if broker else []),
        )
        directional_insufficient_by_symbol = _rows(
            conn,
            f"""
            SELECT p.broker, p.symbol, p.horizon_minutes, COUNT(*) AS count
            FROM shadow_predictions p
            JOIN shadow_outcomes o ON o.prediction_id = p.prediction_id
            {pred_where + (' AND' if pred_where else 'WHERE')}
              p.prediction_type LIKE ?
              AND o.outcome_status = 'insufficient_price_history'
            GROUP BY p.broker, p.symbol, p.horizon_minutes
            ORDER BY p.broker, p.symbol, p.horizon_minutes
            """,
            pred_params + [DIRECTIONAL_PREFIX],
        )

    prediction_type_counts = {
        row["prediction_type"]: int(row["count"]) for row in predictions_by_type
    }
    directional_predictions = sum(
        count for prediction_type, count in prediction_type_counts.items()
        if prediction_type.startswith("return_direction_")
    )
    directional_labeled = _count(directional_outcomes_by_status, "labeled")
    directional_missing = _count(directional_outcomes_by_status, "missing_data")
    directional_insufficient = _count(directional_outcomes_by_status, "insufficient_price_history")
    directional_unsupported = _count(directional_outcomes_by_status, "unsupported_prediction_type")
    best_bucket = max(
        (
            int(row["count"])
            for row in directional_outcomes_by_symbol_horizon
            if row["outcome_status"] == "labeled"
        ),
        default=0,
    )

    thresholds_met = (
        directional_labeled >= MIN_DIRECTIONAL_LABELS_FOR_EVALUATION
        and best_bucket >= MIN_SYMBOL_HORIZON_LABELS_FOR_EVALUATION
    )

    if directional_unsupported:
        gate_status = GATE_BLOCKED_UNSUPPORTED
    elif thresholds_met:
        gate_status = GATE_OPEN
    elif directional_missing or directional_insufficient:
        gate_status = GATE_BLOCKED_PRICE
    elif directional_labeled < MIN_DIRECTIONAL_LABELS_FOR_EVALUATION and symbols_with_snapshots_no_directional:
        gate_status = GATE_BLOCKED_NO_DIRECTIONAL
    elif directional_labeled < MIN_DIRECTIONAL_LABELS_FOR_EVALUATION or best_bucket < MIN_SYMBOL_HORIZON_LABELS_FOR_EVALUATION:
        gate_status = GATE_BLOCKED_SAMPLE
    else:
        gate_status = GATE_OPEN

    gate_reasons = []
    if directional_labeled < MIN_DIRECTIONAL_LABELS_FOR_EVALUATION:
        gate_reasons.append(
            f"directional labeled outcomes {directional_labeled}/{MIN_DIRECTIONAL_LABELS_FOR_EVALUATION}"
        )
    if best_bucket < MIN_SYMBOL_HORIZON_LABELS_FOR_EVALUATION:
        gate_reasons.append(
            f"best directional symbol/horizon bucket {best_bucket}/{MIN_SYMBOL_HORIZON_LABELS_FOR_EVALUATION}"
        )
    if directional_missing or directional_insufficient:
        gate_reasons.append(
            f"directional price coverage gaps: missing_data={directional_missing}, insufficient_price_history={directional_insufficient}"
        )
    if symbols_with_snapshots_no_directional:
        gate_reasons.append(
            f"symbols/snapshots without directional predictions: {len(symbols_with_snapshots_no_directional)} symbol rows"
        )
    if directional_unsupported:
        gate_reasons.append(f"unsupported directional outcomes: {directional_unsupported}")

    return {
        "since_utc": since_utc,
        "broker": broker or "all",
        "predictions_by_type": predictions_by_type,
        "outcomes_by_type_status": outcomes_by_type_status,
        "directional_counts": {
            "predictions": directional_predictions,
            "labeled": directional_labeled,
            "insufficient_price_history": directional_insufficient,
            "missing_data": directional_missing,
            "unsupported": directional_unsupported,
            "best_symbol_horizon_bucket": best_bucket,
        },
        "directional_by_broker_symbol_horizon": directional_by_broker_symbol_horizon,
        "non_directional_by_broker_symbol_horizon": non_directional_by_broker_symbol_horizon,
        "directional_outcomes_by_symbol_horizon": directional_outcomes_by_symbol_horizon,
        "symbols_with_snapshots_no_directional": symbols_with_snapshots_no_directional,
        "symbols_with_price_no_directional": symbols_with_price_no_directional,
        "symbols_with_directional_insufficient_price_history": directional_insufficient_by_symbol,
        "evaluation_gate": {
            "status": gate_status,
            "reasons": gate_reasons,
        },
    }
