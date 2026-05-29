"""Advisory price-coverage planning for shadow outcome labeling."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .public_price_backfill import infer_shadow_crypto_symbols
from .schema import connect, init_db

MIN_DIRECTIONAL_LABELS_FOR_EVALUATION = 100
MIN_SYMBOL_HORIZON_LABELS_FOR_EVALUATION = 30


def since_to_utc(value: str | None) -> str | None:
    if not value:
        return None
    return value if "T" in value else f"{value}T00:00:00Z"


def _filter_clause(
    alias: str,
    *,
    since_utc: str | None,
    broker: str | None = None,
    symbol: str | None = None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if since_utc:
        clauses.append(f"{alias}.created_at_utc >= ?")
        params.append(since_utc)
    if broker:
        clauses.append(f"{alias}.broker = ?")
        params.append(broker)
    if symbol:
        clauses.append(f"{alias}.symbol = ?")
        params.append(symbol)
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


def _rows(conn: sqlite3.Connection, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _count(conn: sqlite3.Connection, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def _status_count(rows: list[dict[str, Any]], status: str) -> int:
    return sum(int(row["count"]) for row in rows if row["outcome_status"] == status)


def build_price_coverage(
    *,
    db_path: str | Path | None = None,
    since: str | None = None,
    broker: str | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    """Summarize price coverage and whether advisory evaluation can proceed."""
    since_utc = since_to_utc(since)
    init_db(db_path)
    pred_where, pred_params = _filter_clause(
        "p",
        since_utc=since_utc,
        broker=broker,
        symbol=symbol,
    )
    price_clauses: list[str] = []
    price_params: list[Any] = []
    if since_utc:
        price_clauses.append("timestamp_utc >= ?")
        price_params.append(since_utc)
    if symbol:
        price_clauses.append("symbol = ?")
        price_params.append(symbol)
    price_where = ("WHERE " + " AND ".join(price_clauses)) if price_clauses else ""

    with connect(db_path) as conn:
        prediction_by_symbol = _rows(
            conn,
            f"""
            SELECT p.symbol, COUNT(*) AS count
            FROM shadow_predictions p
            {pred_where}
            GROUP BY p.symbol
            ORDER BY count DESC, p.symbol
            """,
            pred_params,
        )
        prediction_by_horizon = _rows(
            conn,
            f"""
            SELECT p.horizon_minutes, COUNT(*) AS count
            FROM shadow_predictions p
            {pred_where}
            GROUP BY p.horizon_minutes
            ORDER BY p.horizon_minutes
            """,
            pred_params,
        )
        prediction_by_type = _rows(
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
        price_by_symbol_timeframe = _rows(
            conn,
            f"""
            SELECT symbol,
                   timeframe,
                   COUNT(*) AS count,
                   MIN(timestamp_utc) AS first_timestamp_utc,
                   MAX(timestamp_utc) AS last_timestamp_utc
            FROM shadow_price_points
            {price_where}
            GROUP BY symbol, timeframe
            ORDER BY symbol, timeframe
            """,
            price_params,
        )
        outcome_by_symbol_horizon = _rows(
            conn,
            f"""
            SELECT p.symbol,
                   p.horizon_minutes,
                   COALESCE(o.outcome_status, 'unlabeled') AS outcome_status,
                   COUNT(*) AS count
            FROM shadow_predictions p
            LEFT JOIN shadow_outcomes o ON o.prediction_id = p.prediction_id
            {pred_where}
            GROUP BY p.symbol, p.horizon_minutes, COALESCE(o.outcome_status, 'unlabeled')
            ORDER BY p.symbol, p.horizon_minutes, outcome_status
            """,
            pred_params,
        )
        needed_windows = _rows(
            conn,
            f"""
            SELECT p.symbol,
                   MIN(p.created_at_utc) AS earliest_needed_utc,
                   MAX(strftime('%Y-%m-%dT%H:%M:%SZ',
                       datetime(replace(p.created_at_utc, 'Z', ''), '+' || p.horizon_minutes || ' minutes')
                   )) AS latest_needed_utc,
                   COUNT(*) AS prediction_count
            FROM shadow_predictions p
            {pred_where}
            GROUP BY p.symbol
            ORDER BY p.symbol
            """,
            pred_params,
        )
        directional_labeled_total = _count(
            conn,
            f"""
            SELECT COUNT(*)
            FROM shadow_predictions p
            JOIN shadow_outcomes o ON o.prediction_id = p.prediction_id
            {pred_where + (' AND' if pred_where else 'WHERE')}
              o.outcome_status = 'labeled'
              AND p.prediction_type LIKE 'return_direction_%'
            """,
            pred_params,
        )
        best_directional_bucket = conn.execute(
            f"""
            SELECT p.symbol, p.horizon_minutes, COUNT(*) AS count
            FROM shadow_predictions p
            JOIN shadow_outcomes o ON o.prediction_id = p.prediction_id
            {pred_where + (' AND' if pred_where else 'WHERE')}
              o.outcome_status = 'labeled'
              AND p.prediction_type LIKE 'return_direction_%'
            GROUP BY p.symbol, p.horizon_minutes
            ORDER BY count DESC, p.symbol, p.horizon_minutes
            LIMIT 1
            """,
            pred_params,
        ).fetchone()
        outcome_rows = _count(
            conn,
            f"""
            SELECT COUNT(*)
            FROM shadow_predictions p
            JOIN shadow_outcomes o ON o.prediction_id = p.prediction_id
            {pred_where}
            """,
            pred_params,
        )

    missing_count = _status_count(outcome_by_symbol_horizon, "missing_data")
    insufficient_count = _status_count(outcome_by_symbol_horizon, "insufficient_price_history")
    pending_count = _status_count(outcome_by_symbol_horizon, "pending_horizon")
    labeled_count = _status_count(outcome_by_symbol_horizon, "labeled")
    best_bucket_count = int(best_directional_bucket["count"]) if best_directional_bucket else 0
    gate_blockers = []
    gate_context = []
    if directional_labeled_total < MIN_DIRECTIONAL_LABELS_FOR_EVALUATION:
        gate_blockers.append(
            f"directional labeled outcomes {directional_labeled_total}/{MIN_DIRECTIONAL_LABELS_FOR_EVALUATION}"
        )
    if best_bucket_count < MIN_SYMBOL_HORIZON_LABELS_FOR_EVALUATION:
        gate_blockers.append(
            f"best symbol/horizon bucket {best_bucket_count}/{MIN_SYMBOL_HORIZON_LABELS_FOR_EVALUATION}"
        )
    bias_total = missing_count + insufficient_count
    if outcome_rows:
        gate_context.append(f"missing/insufficient price-history bias {bias_total}/{outcome_rows}")
    else:
        gate_blockers.append("no outcome rows available")

    crypto_symbols = set(
        infer_shadow_crypto_symbols(
            since_utc=since_utc or "0001-01-01T00:00:00Z",
            db_path=db_path,
            create_db=True,
        )
    )
    recommended_commands = []
    for row in needed_windows:
        row_symbol = row["symbol"]
        if symbol and row_symbol != symbol:
            continue
        if row_symbol in crypto_symbols:
            recommended_commands.append(
                {
                    "symbol": row_symbol,
                    "command": f"python3 scripts/shadow_backfill_prices.py --symbol {row_symbol} --since {since or '1970-01-01'} --granularity 60",
                    "reason": "public Coinbase crypto candles available",
                }
            )
        else:
            recommended_commands.append(
                {
                    "symbol": row_symbol,
                    "command": "",
                    "reason": "no unauthenticated public crypto backfill configured for this symbol",
                }
            )

    return {
        "since_utc": since_utc,
        "broker": broker or "all",
        "symbol": symbol or "all",
        "prediction_by_symbol": prediction_by_symbol,
        "prediction_by_horizon": prediction_by_horizon,
        "prediction_by_type": prediction_by_type,
        "price_by_symbol_timeframe": price_by_symbol_timeframe,
        "outcome_by_symbol_horizon": outcome_by_symbol_horizon,
        "needed_windows": needed_windows,
        "recommended_commands": recommended_commands,
        "label_counts": {
            "labeled": labeled_count,
            "missing_data": missing_count,
            "insufficient_price_history": insufficient_count,
            "pending_horizon": pending_count,
            "outcome_rows": outcome_rows,
            "directional_labeled": directional_labeled_total,
            "best_directional_symbol_horizon": best_bucket_count,
        },
        "evaluation_gate": {
            "status": "OPEN" if not gate_blockers else "BLOCKED",
            "reasons": gate_blockers + gate_context,
            "minimum_directional_labeled": MIN_DIRECTIONAL_LABELS_FOR_EVALUATION,
            "minimum_symbol_horizon_labeled": MIN_SYMBOL_HORIZON_LABELS_FOR_EVALUATION,
        },
    }
