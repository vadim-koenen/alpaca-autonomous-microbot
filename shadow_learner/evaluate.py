"""Evaluation helpers for advisory shadow learner predictions."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .prediction_journal import RETURN_DIRECTION_TYPES
from .price_coverage import (
    MIN_DIRECTIONAL_LABELS_FOR_EVALUATION,
    MIN_SYMBOL_HORIZON_LABELS_FOR_EVALUATION,
    since_to_utc,
)
from .schema import connect, init_db, json_dumps, new_id, utc_now

RANDOM_BASELINE_MODEL = "retrospective_random_baseline_v0"
PROSPECTIVE_RANDOM_BASELINE_MODEL = "prospective_random_baseline_v0"
EDGE_NO_EVIDENCE = "NO_EVIDENCE_OF_EDGE"
EDGE_WEAK = "WEAK_SIGNAL_REQUIRES_MORE_DATA"
EDGE_PROMISING = "PROMISING_RETROSPECTIVE_SIGNAL_NOT_LIVE_APPROVED"
EDGE_INSUFFICIENT_PROSPECTIVE = "INSUFFICIENT_PROSPECTIVE_DATA"
EDGE_WEAK_PROSPECTIVE = "WEAK_PROSPECTIVE_SIGNAL_REQUIRES_MORE_DATA"
EDGE_PROMISING_PROSPECTIVE = "PROMISING_PROSPECTIVE_SIGNAL_NOT_PAPER_APPROVED"
EDGE_INSUFFICIENT = "INSUFFICIENT_DATA_AFTER_FILTERS"
EDGE_DATA_QUALITY = "DATA_QUALITY_FAILURE"
PROMOTION_GATE_STATUS = "CLOSED"
MIN_PROSPECTIVE_COLLECTION_DAYS = 2


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_retrospective(row: dict[str, Any]) -> bool:
    try:
        reason = json.loads(row.get("reason_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        reason = {}
    return bool(reason.get("retrospective_generated"))


def _is_prospective(row: dict[str, Any]) -> bool:
    try:
        reason = json.loads(row.get("reason_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        reason = {}
    return bool(reason.get("prospective_shadow_generated"))


def _bucket_for_probability(value: float) -> str:
    lower = min(0.8, max(0.0, int(value * 5) / 5))
    upper = lower + 0.2
    return f"{lower:.1f}-{upper:.1f}"


def _direction_rows(
    *,
    db_path: str | Path | None = None,
    since: str | None = None,
    until: str | None = None,
    model_name: str | None = None,
    model_version: str | None = None,
) -> list[dict[str, Any]]:
    init_db(db_path)
    clauses = [
        "o.outcome_status = 'labeled'",
        f"p.prediction_type IN ({','.join('?' for _ in RETURN_DIRECTION_TYPES)})",
    ]
    params: list[Any] = list(RETURN_DIRECTION_TYPES.values())
    if since:
        clauses.append("p.created_at_utc >= ?")
        params.append(since)
    if until:
        clauses.append("p.created_at_utc <= ?")
        params.append(until)
    if model_name:
        clauses.append("p.model_name = ?")
        params.append(model_name)
    if model_version:
        clauses.append("p.model_version = ?")
        params.append(model_version)

    sql = f"""
        SELECT p.*, o.future_return_pct
        FROM shadow_predictions p
        JOIN shadow_outcomes o ON o.prediction_id = p.prediction_id
        WHERE {' AND '.join(clauses)}
    """
    with connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def evaluate_predictions(
    *,
    db_path: str | Path | None = None,
    since: str | None = None,
    until: str | None = None,
    model_name: str | None = None,
    model_version: str | None = None,
    record_run: bool = True,
) -> dict[str, Any]:
    """Evaluate labeled direction predictions and optionally record a run."""
    rows = _direction_rows(
        db_path=db_path,
        since=since,
        until=until,
        model_name=model_name,
        model_version=model_version,
    )
    sample_count = len(rows)
    correct = 0
    predicted_positive = 0
    true_positive = 0
    actual_positive = 0
    brier_terms: list[float] = []
    returns_when_positive: list[float] = []

    for row in rows:
        probability = float(row["prediction_value"])
        actual = 1 if float(row["future_return_pct"]) > 0 else 0
        predicted = 1 if probability >= 0.5 else 0
        correct += 1 if predicted == actual else 0
        predicted_positive += predicted
        actual_positive += actual
        if predicted and actual:
            true_positive += 1
        if predicted:
            returns_when_positive.append(float(row["future_return_pct"]))
        brier_terms.append((probability - actual) ** 2)

    metrics = {
        "sample_count": sample_count,
        "accuracy": correct / sample_count if sample_count else None,
        "precision": true_positive / predicted_positive if predicted_positive else None,
        "recall": true_positive / actual_positive if actual_positive else None,
        "brier_score": _mean(brier_terms),
        "avg_return_when_positive": _mean(returns_when_positive),
    }

    if record_run:
        run_id = new_id("eval")
        with connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO shadow_evaluation_runs (
                    run_id, created_at_utc, window_start_utc, window_end_utc,
                    model_name, model_version, sample_count, accuracy,
                    precision, recall, brier_score, avg_return_when_positive,
                    notes_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    utc_now(),
                    since,
                    until,
                    model_name,
                    model_version,
                    sample_count,
                    metrics["accuracy"],
                    metrics["precision"],
                    metrics["recall"],
                    metrics["brier_score"],
                    metrics["avg_return_when_positive"],
                    json_dumps({"prediction_scope": "return_direction"}),
                ),
            )
        metrics["run_id"] = run_id
    return metrics


def _advisory_rows(
    *,
    db_path: str | Path | None = None,
    since: str | None = None,
    until: str | None = None,
    broker: str | None = None,
    symbol: str | None = None,
    model_name: str | None = None,
    prospective_only: bool = False,
) -> list[dict[str, Any]]:
    init_db(db_path)
    clauses = [
        f"p.prediction_type IN ({','.join('?' for _ in RETURN_DIRECTION_TYPES)})",
    ]
    params: list[Any] = list(RETURN_DIRECTION_TYPES.values())
    since_utc = since_to_utc(since)
    until_utc = since_to_utc(until)
    if since_utc:
        clauses.append("p.created_at_utc >= ?")
        params.append(since_utc)
    if until_utc:
        clauses.append("p.created_at_utc <= ?")
        params.append(until_utc)
    if broker:
        clauses.append("p.broker = ?")
        params.append(broker)
    if symbol:
        clauses.append("p.symbol = ?")
        params.append(symbol.upper())
    if model_name:
        clauses.append("p.model_name = ?")
        params.append(model_name)
    if prospective_only:
        clauses.append("p.reason_json LIKE ?")
        params.append('%"prospective_shadow_generated": true%')

    with connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT
                p.*,
                COALESCE(o.outcome_status, 'unlabeled') AS outcome_status,
                o.future_return_pct,
                o.max_favorable_excursion_pct,
                o.max_adverse_excursion_pct,
                o.market_data_available,
                s.market_data_status AS snapshot_market_data_status,
                s.skip_reason AS snapshot_skip_reason
            FROM shadow_predictions p
            JOIN shadow_feature_snapshots s ON s.snapshot_id = p.snapshot_id
            LEFT JOIN shadow_outcomes o ON o.prediction_id = p.prediction_id
            WHERE {' AND '.join(clauses)}
            ORDER BY p.created_at_utc, p.model_name, p.symbol, p.horizon_minutes
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]


def _calibration_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        probability = _safe_float(row.get("prediction_value"))
        future_return = _safe_float(row.get("future_return_pct"))
        if probability is None or future_return is None:
            continue
        buckets[_bucket_for_probability(probability)].append(row)

    table = []
    for bucket in sorted(buckets):
        bucket_rows = buckets[bucket]
        actual_up = sum(1 for row in bucket_rows if float(row["future_return_pct"]) > 0)
        avg_probability = _mean([float(row["prediction_value"]) for row in bucket_rows])
        table.append(
            {
                "bucket": bucket,
                "sample_count": len(bucket_rows),
                "avg_prediction": avg_probability,
                "actual_up_rate": actual_up / len(bucket_rows) if bucket_rows else None,
            }
        )
    return table


def _metrics_for_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(str(row.get("outcome_status") or "unlabeled") for row in rows)
    labeled = [
        row
        for row in rows
        if row.get("outcome_status") == "labeled"
        and _safe_float(row.get("future_return_pct")) is not None
    ]

    correct = 0
    predicted_up_count = 0
    predicted_down_count = 0
    actual_up_count = 0
    actual_down_count = 0
    true_positive = 0
    brier_terms: list[float] = []
    returns_when_predicted_up: list[float] = []
    returns_when_predicted_down: list[float] = []
    mfe_values: list[float] = []
    mae_values: list[float] = []

    for row in labeled:
        probability = float(row["prediction_value"])
        future_return = float(row["future_return_pct"])
        actual_up = 1 if future_return > 0 else 0
        predicted_up = 1 if probability > 0.5 else 0
        correct += 1 if predicted_up == actual_up else 0
        predicted_up_count += predicted_up
        predicted_down_count += 0 if predicted_up else 1
        actual_up_count += actual_up
        actual_down_count += 0 if actual_up else 1
        if predicted_up and actual_up:
            true_positive += 1
        if probability > 0.5:
            returns_when_predicted_up.append(future_return)
        elif probability < 0.5:
            returns_when_predicted_down.append(future_return)
        brier_terms.append((probability - actual_up) ** 2)
        mfe = _safe_float(row.get("max_favorable_excursion_pct"))
        mae = _safe_float(row.get("max_adverse_excursion_pct"))
        if mfe is not None:
            mfe_values.append(mfe)
        if mae is not None:
            mae_values.append(mae)

    labeled_count = len(labeled)
    return {
        "sample_count": len(rows),
        "labeled_count": labeled_count,
        "missing_data_count": status_counts.get("missing_data", 0),
        "insufficient_price_history_count": status_counts.get("insufficient_price_history", 0),
        "pending_horizon_count": status_counts.get("pending_horizon", 0),
        "unlabeled_count": status_counts.get("unlabeled", 0),
        "accuracy": correct / labeled_count if labeled_count else None,
        "precision_predicted_up": true_positive / predicted_up_count if predicted_up_count else None,
        "recall_actual_up": true_positive / actual_up_count if actual_up_count else None,
        "actual_up_count": actual_up_count,
        "actual_down_count": actual_down_count,
        "predicted_up_count": predicted_up_count,
        "predicted_down_count": predicted_down_count,
        "correct_direction_count": correct,
        "incorrect_direction_count": labeled_count - correct,
        "avg_future_return_pct_when_prediction_gt_0_5": _mean(returns_when_predicted_up),
        "avg_future_return_pct_when_prediction_lt_0_5": _mean(returns_when_predicted_down),
        "avg_max_favorable_excursion_pct": _mean(mfe_values),
        "avg_max_adverse_excursion_pct": _mean(mae_values),
        "brier_score": _mean(brier_terms),
        "calibration": _calibration_table(labeled),
    }


def _group_metrics(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row.get(key)].append(row)
    return [
        {"group": group, **_metrics_for_rows(group_rows)}
        for group, group_rows in sorted(grouped.items(), key=lambda item: str(item[0]))
    ]


def _group_metrics_multi(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(row.get(key) for key in keys)].append(row)
    results = []
    for group, group_rows in sorted(grouped.items(), key=lambda item: tuple(str(part) for part in item[0])):
        result = {key: value for key, value in zip(keys, group)}
        result.update(_metrics_for_rows(group_rows))
        results.append(result)
    return results


def _retrospective_group_metrics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = {
        "true": [row for row in rows if _is_retrospective(row)],
        "false": [row for row in rows if not _is_retrospective(row)],
    }
    return [
        {"retrospective_generated": key, **_metrics_for_rows(group_rows)}
        for key, group_rows in grouped.items()
    ]


def _prospective_group_metrics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = {
        "true": [row for row in rows if _is_prospective(row)],
        "false": [row for row in rows if not _is_prospective(row)],
    }
    return [
        {"prospective_shadow_generated": key, **_metrics_for_rows(group_rows)}
        for key, group_rows in grouped.items()
    ]


def _collection_days(rows: list[dict[str, Any]]) -> int:
    days = {
        str(row.get("created_at_utc", ""))[:10]
        for row in rows
        if row.get("outcome_status") == "labeled" and row.get("created_at_utc")
    }
    return len(days)


def _add_random_comparison(
    model_rows: list[dict[str, Any]],
    *,
    random_model: str = RANDOM_BASELINE_MODEL,
) -> list[dict[str, Any]]:
    random_metrics = next(
        (row for row in model_rows if row["model_name"] == random_model),
        None,
    )
    if random_metrics is None:
        return model_rows
    random_accuracy = random_metrics.get("accuracy")
    random_brier = random_metrics.get("brier_score")
    enhanced = []
    for row in model_rows:
        item = dict(row)
        if random_accuracy is not None and item.get("accuracy") is not None:
            item["accuracy_delta_vs_random"] = item["accuracy"] - random_accuracy
        else:
            item["accuracy_delta_vs_random"] = None
        if random_brier is not None and item.get("brier_score") is not None:
            item["brier_improvement_vs_random"] = random_brier - item["brier_score"]
        else:
            item["brier_improvement_vs_random"] = None
        enhanced.append(item)
    return enhanced


def _count_news_context(conn, since_utc: str | None) -> dict[str, Any]:
    where = "WHERE published_at_utc >= ?" if since_utc else ""
    params = (since_utc,) if since_utc else ()
    news_count = int(conn.execute(f"SELECT COUNT(*) FROM shadow_news_items {where}", params).fetchone()[0])
    link_count = int(conn.execute("SELECT COUNT(*) FROM shadow_news_signal_links").fetchone()[0])
    return {"news_items": news_count, "news_signal_links": link_count}


def _price_context(conn, since_utc: str | None) -> list[dict[str, Any]]:
    where = "WHERE timestamp_utc >= ?" if since_utc else ""
    params = (since_utc,) if since_utc else ()
    rows = conn.execute(
        f"""
        SELECT symbol, COUNT(*) AS count,
               MIN(timestamp_utc) AS first_timestamp_utc,
               MAX(timestamp_utc) AS last_timestamp_utc
        FROM shadow_price_points
        {where}
        GROUP BY symbol
        ORDER BY symbol
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def _classify_evidence(report: dict[str, Any]) -> tuple[str, list[str]]:
    overall = report["overall"]
    reasons: list[str] = []
    if overall["sample_count"] == 0:
        return EDGE_DATA_QUALITY, ["no directional predictions found for this filter"]
    if overall["labeled_count"] == 0:
        return EDGE_DATA_QUALITY, ["no labeled directional outcomes found for this filter"]

    best_bucket = max(
        (row["labeled_count"] for row in report["by_symbol_horizon"]),
        default=0,
    )
    if overall["labeled_count"] < MIN_DIRECTIONAL_LABELS_FOR_EVALUATION:
        reasons.append(
            f"labeled directional outcomes {overall['labeled_count']}/{MIN_DIRECTIONAL_LABELS_FOR_EVALUATION}"
        )
    if best_bucket < MIN_SYMBOL_HORIZON_LABELS_FOR_EVALUATION:
        reasons.append(
            f"best symbol/horizon bucket {best_bucket}/{MIN_SYMBOL_HORIZON_LABELS_FOR_EVALUATION}"
        )
    if reasons:
        return EDGE_INSUFFICIENT, reasons

    random_metrics = next(
        (row for row in report["by_model"] if row["model_name"] == RANDOM_BASELINE_MODEL),
        None,
    )
    non_random = [
        row
        for row in report["by_model"]
        if row["model_name"] != RANDOM_BASELINE_MODEL and row.get("labeled_count", 0) > 0
    ]
    if random_metrics is None or not non_random:
        return EDGE_INSUFFICIENT, ["random baseline or non-random comparison model is missing"]

    eligible_non_random = [
        row
        for row in non_random
        if row.get("labeled_count", 0) >= MIN_DIRECTIONAL_LABELS_FOR_EVALUATION
    ]
    if not eligible_non_random:
        return EDGE_INSUFFICIENT, [
            "no non-random model has enough labeled samples for random-baseline comparison"
        ]

    best = max(
        eligible_non_random,
        key=lambda row: (
            row.get("accuracy_delta_vs_random") if row.get("accuracy_delta_vs_random") is not None else -999.0,
            row.get("brier_improvement_vs_random") if row.get("brier_improvement_vs_random") is not None else -999.0,
        ),
    )
    accuracy_delta = best.get("accuracy_delta_vs_random") or 0.0
    brier_delta = best.get("brier_improvement_vs_random") or 0.0
    reasons.append(
        f"best non-random model={best['model_name']} accuracy_delta_vs_random={accuracy_delta:.3f} brier_improvement_vs_random={brier_delta:.3f}"
    )

    if accuracy_delta >= 0.05 and brier_delta >= 0.01:
        return EDGE_PROMISING, reasons
    if accuracy_delta >= 0.02 or brier_delta >= 0.005:
        return EDGE_WEAK, reasons
    return EDGE_NO_EVIDENCE, reasons


def _classify_prospective_evidence(report: dict[str, Any]) -> tuple[str, list[str]]:
    overall = report["overall"]
    reasons: list[str] = []
    if overall["sample_count"] == 0:
        return EDGE_INSUFFICIENT_PROSPECTIVE, ["no prospective directional predictions found"]
    if overall["labeled_count"] == 0:
        return EDGE_INSUFFICIENT_PROSPECTIVE, ["no labeled prospective directional outcomes found"]

    best_bucket = max(
        (row["labeled_count"] for row in report["by_symbol_horizon_model"]),
        default=0,
    )
    collection_days = report.get("prospective_collection_days", 0)
    if overall["labeled_count"] < MIN_DIRECTIONAL_LABELS_FOR_EVALUATION:
        reasons.append(
            f"labeled prospective directional outcomes {overall['labeled_count']}/{MIN_DIRECTIONAL_LABELS_FOR_EVALUATION}"
        )
    if best_bucket < MIN_SYMBOL_HORIZON_LABELS_FOR_EVALUATION:
        reasons.append(
            f"best prospective symbol/horizon/model bucket {best_bucket}/{MIN_SYMBOL_HORIZON_LABELS_FOR_EVALUATION}"
        )
    if collection_days < MIN_PROSPECTIVE_COLLECTION_DAYS:
        reasons.append(
            f"prospective collection days {collection_days}/{MIN_PROSPECTIVE_COLLECTION_DAYS}"
        )
    if reasons:
        return EDGE_INSUFFICIENT_PROSPECTIVE, reasons

    random_metrics = next(
        (row for row in report["by_model"] if row["model_name"] == PROSPECTIVE_RANDOM_BASELINE_MODEL),
        None,
    )
    non_random = [
        row
        for row in report["by_model"]
        if row["model_name"] != PROSPECTIVE_RANDOM_BASELINE_MODEL
        and row.get("labeled_count", 0) >= MIN_DIRECTIONAL_LABELS_FOR_EVALUATION
    ]
    if random_metrics is None or not non_random:
        return EDGE_INSUFFICIENT_PROSPECTIVE, [
            "prospective random baseline or non-random comparison model is missing"
        ]

    best = max(
        non_random,
        key=lambda row: (
            row.get("accuracy_delta_vs_random") if row.get("accuracy_delta_vs_random") is not None else -999.0,
            row.get("brier_improvement_vs_random") if row.get("brier_improvement_vs_random") is not None else -999.0,
        ),
    )
    accuracy_delta = best.get("accuracy_delta_vs_random") or 0.0
    brier_delta = best.get("brier_improvement_vs_random") or 0.0
    reasons.append(
        f"best prospective non-random model={best['model_name']} accuracy_delta_vs_random={accuracy_delta:.3f} brier_improvement_vs_random={brier_delta:.3f}"
    )
    if accuracy_delta >= 0.05 and brier_delta >= 0.01:
        return EDGE_PROMISING_PROSPECTIVE, reasons
    if accuracy_delta >= 0.02 or brier_delta >= 0.005:
        return EDGE_WEAK_PROSPECTIVE, reasons
    return EDGE_NO_EVIDENCE, reasons


def build_advisory_evaluation(
    *,
    db_path: str | Path | None = None,
    since: str | None = None,
    until: str | None = None,
    broker: str | None = None,
    symbol: str | None = None,
    model_name: str | None = None,
    prospective_only: bool = False,
) -> dict[str, Any]:
    """Build a full advisory directional evaluation report.

    This reads only shadow learner tables and does not mutate live bot state.
    """
    since_utc = since_to_utc(since)
    until_utc = since_to_utc(until)
    rows = _advisory_rows(
        db_path=db_path,
        since=since_utc,
        until=until_utc,
        broker=broker,
        symbol=symbol,
        model_name=model_name,
        prospective_only=prospective_only,
    )
    random_model = PROSPECTIVE_RANDOM_BASELINE_MODEL if prospective_only else RANDOM_BASELINE_MODEL
    by_model = _group_metrics_multi(rows, ("model_name", "model_version"))
    by_model = _add_random_comparison(by_model, random_model=random_model)
    report: dict[str, Any] = {
        "window_start_utc": since_utc,
        "window_end_utc": until_utc,
        "broker": broker or "all",
        "symbol": symbol.upper() if symbol else "all",
        "model": model_name or "all",
        "prospective_only": prospective_only,
        "overall": _metrics_for_rows(rows),
        "by_model": by_model,
        "by_symbol": _group_metrics(rows, "symbol"),
        "by_horizon": _group_metrics(rows, "horizon_minutes"),
        "by_symbol_horizon": _group_metrics_multi(rows, ("symbol", "horizon_minutes")),
        "by_symbol_horizon_model": _group_metrics_multi(
            rows, ("symbol", "horizon_minutes", "model_name")
        ),
        "by_prediction_type": _group_metrics(rows, "prediction_type"),
        "by_retrospective_generated": _retrospective_group_metrics(rows),
        "by_prospective_shadow_generated": _prospective_group_metrics(rows),
        "by_broker": _group_metrics(rows, "broker"),
        "by_live_trade_taken": _group_metrics(rows, "live_trade_taken"),
        "warnings": [
            "Retrospective predictions are advisory backfilled predictions, not live-proven signals.",
            "Prospective shadow predictions are advisory samples only and require separate evaluation.",
            "No model output is used for orders, risk approvals, position sizing, or symbol selection.",
            "This report does not authorize scaling or live trading changes.",
            "Missing-data outcomes remain present and can bias comparisons.",
            "Equity snapshots remain mostly non-directional/no-price/no-bar.",
            "Crypto-only labeled samples may not generalize across assets or regimes.",
            "If random baseline performs similarly, report no evidence of edge.",
        ],
        "promotion_gate": {
            "status": PROMOTION_GATE_STATUS,
            "never_approved_for_live_trading": True,
            "requirements": [
                "prospective, not retrospective-only, results exist",
                "signal beats random baseline materially",
                "enough samples exist across multiple days/regimes",
                "paper-mode validation confirms behavior",
                "human approval is given",
                "rollback plan exists",
                "risk caps remain unchanged unless separately approved",
            ],
        },
        "prospective_collection_days": _collection_days(rows),
    }
    with connect(db_path) as conn:
        report["news_context"] = _count_news_context(conn, since_utc)
        report["price_context"] = _price_context(conn, since_utc)

    if prospective_only:
        evidence_status, evidence_reasons = _classify_prospective_evidence(report)
    else:
        evidence_status, evidence_reasons = _classify_evidence(report)
    report["evidence"] = {
        "status": evidence_status,
        "reasons": evidence_reasons,
    }
    return report
