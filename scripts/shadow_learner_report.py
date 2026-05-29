#!/usr/bin/env python3
"""Summarize advisory shadow learner samples and outcomes."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shadow_learner.evaluate import evaluate_predictions
from shadow_learner.schema import connect, init_db


def _since_to_utc(value: str | None) -> str | None:
    if not value:
        return None
    if "T" in value:
        return value
    return f"{value}T00:00:00Z"


def _count(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def _rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    return conn.execute(sql, params).fetchall()


def _format_metric(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}"


def _source_summary(conn: sqlite3.Connection, since_utc: str | None) -> Counter[str]:
    where = "WHERE created_at_utc >= ?" if since_utc else ""
    params = (since_utc,) if since_utc else ()
    rows = conn.execute(
        f"SELECT features_json FROM shadow_feature_snapshots {where}",
        params,
    ).fetchall()
    counts: Counter[str] = Counter()
    for row in rows:
        try:
            features = json.loads(row["features_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            features = {}
        source = features.get("ingestion_source") or features.get("source_kind") or "unknown"
        counts[str(source)] += 1
    return counts


def _news_theme_summary(conn: sqlite3.Connection, since_utc: str | None) -> Counter[str]:
    where = "WHERE published_at_utc >= ?" if since_utc else ""
    params = (since_utc,) if since_utc else ()
    rows = conn.execute(
        f"SELECT themes_json FROM shadow_news_items {where}",
        params,
    ).fetchall()
    counts: Counter[str] = Counter()
    for row in rows:
        try:
            themes = json.loads(row["themes_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            themes = []
        if isinstance(themes, list):
            counts.update(str(theme) for theme in themes)
    return counts


def build_report(*, db_path: str | Path | None, since: str | None) -> str:
    since_utc = _since_to_utc(since)
    init_db(db_path)
    where = "WHERE created_at_utc >= ?" if since_utc else ""
    params = (since_utc,) if since_utc else ()
    pred_where = "WHERE p.created_at_utc >= ?" if since_utc else ""
    pred_params = (since_utc,) if since_utc else ()

    with connect(db_path) as conn:
        snapshots = _count(
            conn,
            f"SELECT COUNT(*) FROM shadow_feature_snapshots {where}",
            params,
        )
        predictions = _count(
            conn,
            f"SELECT COUNT(*) FROM shadow_predictions {where}",
            params,
        )
        prospective_predictions = _count(
            conn,
            """
            SELECT COUNT(*)
            FROM shadow_predictions
            WHERE reason_json LIKE '%"prospective_shadow_generated": true%'
            """
            + (" AND created_at_utc >= ?" if since_utc else ""),
            pred_params,
        )
        retrospective_predictions = _count(
            conn,
            """
            SELECT COUNT(*)
            FROM shadow_predictions
            WHERE reason_json LIKE '%"retrospective_generated": true%'
            """
            + (" AND created_at_utc >= ?" if since_utc else ""),
            pred_params,
        )
        outcome_rows = _count(
            conn,
            """
            SELECT COUNT(*)
            FROM shadow_outcomes o
            JOIN shadow_predictions p ON p.prediction_id = o.prediction_id
            """
            + pred_where,
            pred_params,
        )
        labeled_outcomes = _count(
            conn,
            """
            SELECT COUNT(*)
            FROM shadow_outcomes o
            JOIN shadow_predictions p ON p.prediction_id = o.prediction_id
            WHERE o.outcome_status = 'labeled'
            """
            + (" AND p.created_at_utc >= ?" if since_utc else ""),
            pred_params,
        )
        pending_horizon_count = _count(
            conn,
            """
            SELECT COUNT(*)
            FROM shadow_outcomes o
            JOIN shadow_predictions p ON p.prediction_id = o.prediction_id
            WHERE o.outcome_status = 'pending_horizon'
            """
            + (" AND p.created_at_utc >= ?" if since_utc else ""),
            pred_params,
        )
        pending = _count(
            conn,
            """
            SELECT COUNT(*)
            FROM shadow_predictions p
            LEFT JOIN shadow_outcomes o ON o.prediction_id = p.prediction_id
            WHERE o.prediction_id IS NULL
            """
            + (" AND p.created_at_utc >= ?" if since_utc else ""),
            pred_params,
        )
        pending += pending_horizon_count
        by_broker = _rows(
            conn,
            f"""
            SELECT broker, COUNT(*) AS count
            FROM shadow_feature_snapshots
            {where}
            GROUP BY broker
            ORDER BY count DESC, broker
            """,
            params,
        )
        by_symbol = _rows(
            conn,
            f"""
            SELECT symbol, COUNT(*) AS count
            FROM shadow_feature_snapshots
            {where}
            GROUP BY symbol
            ORDER BY count DESC, symbol
            LIMIT 20
            """,
            params,
        )
        by_type = _rows(
            conn,
            f"""
            SELECT prediction_type, COUNT(*) AS count
            FROM shadow_predictions
            {where}
            GROUP BY prediction_type
            ORDER BY count DESC, prediction_type
            """,
            params,
        )
        missing_count = _count(
            conn,
            """
            SELECT COUNT(*)
            FROM shadow_outcomes o
            JOIN shadow_predictions p ON p.prediction_id = o.prediction_id
            WHERE o.outcome_status = 'missing_data'
            """
            + (" AND p.created_at_utc >= ?" if since_utc else ""),
            pred_params,
        )
        labeled_by_broker = _rows(
            conn,
            """
            SELECT p.broker, COUNT(*) AS count
            FROM shadow_outcomes o
            JOIN shadow_predictions p ON p.prediction_id = o.prediction_id
            WHERE o.outcome_status = 'labeled'
            """
            + (" AND p.created_at_utc >= ?" if since_utc else "")
            + """
            GROUP BY p.broker
            ORDER BY count DESC, p.broker
            """,
            pred_params,
        )
        original_scan_time_predictions = max(
            0,
            predictions - prospective_predictions - retrospective_predictions,
        )
        insufficient_count = _count(
            conn,
            """
            SELECT COUNT(*)
            FROM shadow_outcomes o
            JOIN shadow_predictions p ON p.prediction_id = o.prediction_id
            WHERE o.outcome_status = 'insufficient_price_history'
            """
            + (" AND p.created_at_utc >= ?" if since_utc else ""),
            pred_params,
        )
        labeled_by_symbol = _rows(
            conn,
            """
            SELECT p.symbol, COUNT(*) AS count
            FROM shadow_outcomes o
            JOIN shadow_predictions p ON p.prediction_id = o.prediction_id
            WHERE o.outcome_status = 'labeled'
            """
            + (" AND p.created_at_utc >= ?" if since_utc else "")
            + """
            GROUP BY p.symbol
            ORDER BY count DESC, p.symbol
            LIMIT 20
            """,
            pred_params,
        )
        labeled_by_horizon = _rows(
            conn,
            """
            SELECT p.horizon_minutes, COUNT(*) AS count
            FROM shadow_outcomes o
            JOIN shadow_predictions p ON p.prediction_id = o.prediction_id
            WHERE o.outcome_status = 'labeled'
            """
            + (" AND p.created_at_utc >= ?" if since_utc else "")
            + """
            GROUP BY p.horizon_minutes
            ORDER BY p.horizon_minutes
            """,
            pred_params,
        )
        top_skips = _rows(
            conn,
            f"""
            SELECT COALESCE(NULLIF(skip_reason, ''), 'none') AS skip_reason,
                   COUNT(*) AS count
            FROM shadow_feature_snapshots
            {where}
            GROUP BY COALESCE(NULLIF(skip_reason, ''), 'none')
            ORDER BY count DESC, skip_reason
            LIMIT 10
            """,
            params,
        )
        accuracy_rows = _rows(
            conn,
            """
            SELECT p.horizon_minutes,
                   COUNT(*) AS count,
                   AVG(
                       CASE
                           WHEN (p.prediction_value >= 0.5 AND o.future_return_pct > 0)
                             OR (p.prediction_value < 0.5 AND o.future_return_pct <= 0)
                           THEN 1.0 ELSE 0.0
                       END
                   ) AS accuracy
            FROM shadow_predictions p
            JOIN shadow_outcomes o ON o.prediction_id = p.prediction_id
            WHERE o.outcome_status = 'labeled'
              AND p.prediction_type LIKE 'return_direction_%'
            """
            + (" AND p.created_at_utc >= ?" if since_utc else "")
            + """
            GROUP BY p.horizon_minutes
            ORDER BY p.horizon_minutes
            """,
            pred_params,
        )
        source_summary = _source_summary(conn, since_utc)
        price_point_count = _count(
            conn,
            "SELECT COUNT(*) FROM shadow_price_points "
            + ("WHERE timestamp_utc >= ?" if since_utc else ""),
            (since_utc,) if since_utc else (),
        )
        price_symbols = _rows(
            conn,
            """
            SELECT symbol,
                   COUNT(*) AS count,
                   MIN(timestamp_utc) AS first_timestamp_utc,
                   MAX(timestamp_utc) AS last_timestamp_utc
            FROM shadow_price_points
            """
            + ("WHERE timestamp_utc >= ?" if since_utc else "")
            + """
            GROUP BY symbol
            ORDER BY count DESC, symbol
            LIMIT 20
            """,
            (since_utc,) if since_utc else (),
        )
        news_count = _count(
            conn,
            "SELECT COUNT(*) FROM shadow_news_items "
            + ("WHERE published_at_utc >= ?" if since_utc else ""),
            (since_utc,) if since_utc else (),
        )
        news_theme_summary = _news_theme_summary(conn, since_utc)

    metrics = evaluate_predictions(
        db_path=db_path,
        since=since_utc,
        record_run=False,
    )
    missing_rate = (missing_count / outcome_rows) if outcome_rows else None

    lines = [
        "Shadow Learner Report",
        f"Since: {since_utc or 'all'}",
        f"Snapshots: {snapshots}",
        f"Predictions: {predictions}",
        f"Prospective shadow predictions: {prospective_predictions}",
        f"Retrospective shadow predictions: {retrospective_predictions}",
        f"Original scan-time predictions: {original_scan_time_predictions}",
        f"Price points: {price_point_count}",
        f"Outcome rows: {outcome_rows}",
        f"Outcomes labeled: {labeled_outcomes}",
        f"Missing-data outcomes: {missing_count}",
        f"Insufficient-price-history outcomes: {insufficient_count}",
        f"Pending outcomes: {pending}",
        f"News items: {news_count}",
        "",
        "Sample count by broker:",
    ]
    if by_broker:
        lines.extend(f"  {row['broker']}: {row['count']}" for row in by_broker)
    else:
        lines.append("  none")

    lines.extend(
        [
            "",
            "Sample count by symbol:",
        ]
    )
    if by_symbol:
        lines.extend(f"  {row['symbol']}: {row['count']}" for row in by_symbol)
    else:
        lines.append("  none")

    lines.append("")
    lines.append("Price symbols available:")
    if price_symbols:
        lines.extend(f"  {row['symbol']}: {row['count']}" for row in price_symbols)
    else:
        lines.append("  none")

    lines.append("")
    lines.append("Price coverage:")
    if price_symbols:
        lines.extend(
            f"  {row['symbol']}: {row['first_timestamp_utc']} -> {row['last_timestamp_utc']} ({row['count']} points)"
            for row in price_symbols
        )
    else:
        lines.append("  none")

    lines.append("")
    lines.append("Sample count by prediction_type:")
    if by_type:
        lines.extend(f"  {row['prediction_type']}: {row['count']}" for row in by_type)
    else:
        lines.append("  none")

    lines.append("")
    lines.append("Labeled outcome count by broker:")
    if labeled_by_broker:
        lines.extend(f"  {row['broker']}: {row['count']}" for row in labeled_by_broker)
    else:
        lines.append("  none")

    lines.append("")
    lines.append("Labeled outcome count by symbol:")
    if labeled_by_symbol:
        lines.extend(f"  {row['symbol']}: {row['count']}" for row in labeled_by_symbol)
    else:
        lines.append("  none")

    lines.append("")
    lines.append("Labeled outcome count by horizon:")
    if labeled_by_horizon:
        lines.extend(f"  {row['horizon_minutes']}m: {row['count']}" for row in labeled_by_horizon)
    else:
        lines.append("  none")

    lines.append("")
    lines.append("Accuracy by horizon:")
    if accuracy_rows:
        lines.extend(
            f"  {row['horizon_minutes']}m: {row['accuracy']:.3f} ({row['count']} samples)"
            for row in accuracy_rows
        )
    else:
        lines.append("  n/a")

    lines.extend(
        [
            "",
            f"Overall direction sample_count: {metrics['sample_count']}",
            f"Overall direction accuracy: {_format_metric(metrics['accuracy'])}",
            f"Overall direction precision: {_format_metric(metrics['precision'])}",
            f"Overall direction recall: {_format_metric(metrics['recall'])}",
            f"Overall direction brier_score: {_format_metric(metrics['brier_score'])}",
            f"Avg return when positive: {_format_metric(metrics['avg_return_when_positive'])}",
            f"Missing data rate: {_format_metric(missing_rate)}",
            "",
            "Top skip reasons:",
        ]
    )
    if top_skips:
        lines.extend(f"  {row['skip_reason']}: {row['count']}" for row in top_skips)
    else:
        lines.append("  none")

    lines.append("")
    lines.append("Top news themes:")
    if news_theme_summary:
        for theme, count in news_theme_summary.most_common(10):
            lines.append(f"  {theme}: {count}")
    else:
        lines.append("  none")

    lines.append("")
    lines.append("Ingestion source summary:")
    if source_summary:
        for source, count in source_summary.most_common(20):
            lines.append(f"  {source}: {count}")
    else:
        lines.append("  none")

    lines.append("")
    lines.append(f"Next required data source: {_next_required_data_source(price_point_count, labeled_outcomes, missing_count, insufficient_count)}")

    lines.extend(
        [
            "",
            "Recommendation: advisory only; not used for live trading",
        ]
    )
    return "\n".join(lines)


def _next_required_data_source(
    price_point_count: int,
    labeled_outcomes: int,
    missing_count: int,
    insufficient_count: int,
) -> str:
    if price_point_count == 0:
        return "import read-only price bars covering prediction timestamps and horizons"
    if labeled_outcomes == 0:
        return "add price bars at t0 plus 15/30/60/90m horizons for BTC/USD, SOL/USD, and equity scan symbols"
    if missing_count or insufficient_count:
        return "fill remaining symbol/timeframe gaps for missing and insufficient outcome rows"
    return "enough coverage for baseline evaluation; proceed to advisory evaluation only"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default=None, help="UTC date or timestamp lower bound")
    parser.add_argument("--db", default=None, help="Optional shadow learner SQLite path")
    args = parser.parse_args()
    print(build_report(db_path=args.db, since=args.since))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
