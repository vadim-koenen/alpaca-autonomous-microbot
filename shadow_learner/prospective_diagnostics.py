"""Prospective-only diagnostic analysis for the advisory shadow learner.

This module focuses on evaluating the quality, calibration, and edge of prospective
predictions (those generated at or before T0) vs realized outcomes.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .evaluate import _safe_float, _mean
from .schema import connect, init_db, json_dumps

PROSPECTIVE_RANDOM_BASELINE = "prospective_random_baseline_v0"

# Calibration buckets as per requirements
BUCKETS = [
    (0.40, 0.45, "0.40-0.45"),
    (0.45, 0.50, "0.45-0.50"),
    (0.50, 0.50, "exactly 0.50"),
    (0.50, 0.55, "0.50-0.55"),
    (0.55, 0.60, "0.55-0.60"),
    (0.60, 1.01, "> 0.60"),
]

# Report conclusions
CONCLUSION_NO_EDGE = "SIGNAL_DIAGNOSTICS_NO_EDGE"
CONCLUSION_WEAK_CALIBRATION = "SIGNAL_DIAGNOSTICS_WEAK_CALIBRATION"
CONCLUSION_PROMISING = "SIGNAL_DIAGNOSTICS_PROMISING_BUCKETS_TRACK_ONLY"
CONCLUSION_DATA_QUALITY = "SIGNAL_DIAGNOSTICS_DATA_QUALITY_ISSUE"
CONCLUSION_INSUFFICIENT = "SIGNAL_DIAGNOSTICS_INSUFFICIENT_PROSPECTIVE_DATA"


def _get_bucket_label(probability: float) -> str:
    if probability == 0.50:
        return "exactly 0.50"
    for lower, upper, label in BUCKETS:
        if lower <= probability < upper:
            return label
    return "out of range"


def _calculate_brier(predictions: list[dict[str, Any]]) -> float | None:
    terms = []
    for p in predictions:
        prob = _safe_float(p.get("prediction_value"))
        actual = 1.0 if _safe_float(p.get("future_return_pct", 0.0)) > 0 else 0.0
        if prob is not None:
            terms.append((prob - actual) ** 2)
    return _mean(terms)


class ProspectiveAnalyzer:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = db_path
        init_db(self.db_path)

    def fetch_data(
        self,
        since: str | None = None,
        symbol: str | None = None,
        model_name: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = [
            "p.reason_json LIKE '%\"prospective_shadow_generated\": true%'",
            "p.reason_json LIKE '%\"retrospective_generated\": false%'",
            "p.reason_json LIKE '%\"no_live_trading_influence\": true%'",
            "p.reason_json LIKE '%\"uses_only_t0_or_prior_data\": true%'",
        ]
        params: list[Any] = []

        if since:
            if "T" not in since:
                since = f"{since}T00:00:00Z"
            clauses.append("p.created_at_utc >= ?")
            params.append(since)
        if symbol:
            clauses.append("p.symbol = ?")
            params.append(symbol.upper())
        if model_name:
            clauses.append("p.model_name = ?")
            params.append(model_name)

        sql = f"""
            SELECT p.*, o.future_return_pct, o.outcome_status, o.market_data_available,
                   o.max_favorable_excursion_pct, o.max_adverse_excursion_pct
            FROM shadow_predictions p
            LEFT JOIN shadow_outcomes o ON o.prediction_id = p.prediction_id
            WHERE {" AND ".join(clauses)}
            ORDER BY p.created_at_utc ASC
        """
        with connect(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]

    def run_diagnostics(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {"conclusion": CONCLUSION_INSUFFICIENT, "sample_count": 0}

        labeled = [r for r in rows if r.get("outcome_status") == "labeled" and r.get("future_return_pct") is not None]
        if not labeled:
            return {
                "conclusion": CONCLUSION_INSUFFICIENT,
                "sample_count": len(rows),
                "labeled_count": 0,
            }

        # Brier scores by model/symbol/horizon
        by_msh = defaultdict(list)
        for r in labeled:
            key = (r["model_name"], r["symbol"], r["horizon_minutes"])
            by_msh[key].append(r)

        msh_metrics = {}
        for key, group in by_msh.items():
            msh_metrics[key] = {
                "sample_count": len(group),
                "brier": _calculate_brier(group),
                "accuracy": sum(1 for r in group if (r["prediction_value"] >= 0.5) == (r["future_return_pct"] > 0)) / len(group),
                "actual_up_pct": sum(1 for r in group if r["future_return_pct"] > 0) / len(group),
                "predicted_up_pct": sum(1 for r in group if r["prediction_value"] > 0.5) / len(group),
            }

        # Baseline comparison
        baselines = {key: m for key, m in msh_metrics.items() if key[0] == PROSPECTIVE_RANDOM_BASELINE}
        
        # Calibration buckets
        cal_buckets = defaultdict(list)
        for r in labeled:
            bucket = _get_bucket_label(float(r["prediction_value"]))
            cal_buckets[bucket].append(r)

        calibration_stats = []
        for _, _, label in BUCKETS:
            group = cal_buckets.get(label, [])
            if not group:
                calibration_stats.append({"bucket": label, "count": 0, "actual_up_pct": None, "avg_conf": None})
                continue
            
            actual_up = sum(1 for r in group if r["future_return_pct"] > 0) / len(group)
            avg_conf = _mean([float(r["confidence"]) for r in group])
            calibration_stats.append({
                "bucket": label,
                "count": len(group),
                "actual_up_pct": actual_up,
                "avg_conf": avg_conf
            })

        # Confidence distribution
        conf_vals = [float(r["confidence"]) for r in labeled]
        low_conf_share = sum(1 for r in labeled if _get_bucket_label(float(r["prediction_value"])) == "exactly 0.50") / len(labeled)

        # Feature capture audit
        audit_failures = 0
        for r in rows:
            try:
                reason = json.loads(r["reason_json"])
                if not reason.get("uses_only_t0_or_prior_data"):
                    audit_failures += 1
            except:
                audit_failures += 1

        # Strongest / Weakest MSH bucket
        if msh_metrics:
            strongest_msh = max(msh_metrics.items(), key=lambda x: x[1]["accuracy"])
            weakest_msh = min(msh_metrics.items(), key=lambda x: x[1]["accuracy"])
        else:
            strongest_msh = weakest_msh = None

        # Determine Paper Gate Status
        # We need to compute brier delta vs baseline
        brier_deltas = []
        acc_deltas = []
        for key, m in msh_metrics.items():
            if key[0] == PROSPECTIVE_RANDOM_BASELINE:
                continue
            base_key = (PROSPECTIVE_RANDOM_BASELINE, key[1], key[2])
            if base_key in baselines:
                brier_deltas.append(baselines[base_key]["brier"] - m["brier"])
                acc_deltas.append(m["accuracy"] - baselines[base_key]["accuracy"])

        avg_brier_delta = _mean(brier_deltas) if brier_deltas else 0.0
        avg_acc_delta = _mean(acc_deltas) if acc_deltas else 0.0

        # Conclusion logic
        conclusion = CONCLUSION_NO_EDGE
        if audit_failures > 0:
            conclusion = CONCLUSION_DATA_QUALITY
        elif len(labeled) < 20:
            conclusion = CONCLUSION_INSUFFICIENT
        elif avg_acc_delta >= 0.05 and avg_brier_delta >= 0.01:
            conclusion = CONCLUSION_PROMISING
        elif avg_acc_delta >= 0.01 or avg_brier_delta >= 0.005:
            conclusion = CONCLUSION_WEAK_CALIBRATION
        
        return {
            "conclusion": conclusion,
            "sample_count": len(rows),
            "labeled_count": len(labeled),
            "msh_metrics": msh_metrics,
            "calibration_stats": calibration_stats,
            "low_conf_share": low_conf_share,
            "avg_brier_delta": avg_brier_delta,
            "avg_acc_delta": avg_acc_delta,
            "audit_failures": audit_failures,
            "strongest_msh": strongest_msh,
            "weakest_msh": weakest_msh,
            "conf_distribution": {
                "min": min(conf_vals) if conf_vals else None,
                "max": max(conf_vals) if conf_vals else None,
                "avg": _mean(conf_vals)
            }
        }
