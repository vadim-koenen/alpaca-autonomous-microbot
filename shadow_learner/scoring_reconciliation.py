"""Scoring reconciliation and bucket watchlist for the advisory shadow learner.

This module reconciles results from the evaluator and diagnostics to provide
a unified advisory view and identify promising or problematic buckets.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .evaluate import (
    build_advisory_evaluation,
    EDGE_NO_EVIDENCE,
    EDGE_WEAK_PROSPECTIVE,
    EDGE_PROMISING_PROSPECTIVE,
    EDGE_INSUFFICIENT_PROSPECTIVE,
    EDGE_DATA_QUALITY as EVAL_DATA_QUALITY,
)
from .prospective_diagnostics import (
    ProspectiveAnalyzer,
    CONCLUSION_NO_EDGE,
    CONCLUSION_WEAK_CALIBRATION,
    CONCLUSION_PROMISING,
    CONCLUSION_DATA_QUALITY as DIAG_DATA_QUALITY,
    CONCLUSION_INSUFFICIENT,
    PROSPECTIVE_RANDOM_BASELINE,
)

# Reconciled Conclusion Labels
RECONCILED_NO_EDGE = "RECONCILED_NO_EDGE"
RECONCILED_WEAK_SIGNAL_TRACK_ONLY = "RECONCILED_WEAK_SIGNAL_TRACK_ONLY"
RECONCILED_DATA_QUALITY_BLOCKED = "RECONCILED_DATA_QUALITY_BLOCKED"
RECONCILED_INSUFFICIENT_SAMPLE = "RECONCILED_INSUFFICIENT_SAMPLE"
RECONCILED_READY_FOR_HUMAN_REVIEW_ONLY = "RECONCILED_READY_FOR_HUMAN_REVIEW_ONLY"

# Watchlist/Reject List thresholds
MIN_BUCKET_SAMPLES = 50


class ScoringReconciler:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = db_path
        self.analyzer = ProspectiveAnalyzer(db_path=db_path)

    def reconcile(
        self,
        since: str | None = None,
        symbol: str | None = None,
        model_name: str | None = None,
    ) -> dict[str, Any]:
        # 1. Get Evaluator Report (Prospective only)
        eval_report = build_advisory_evaluation(
            db_path=self.db_path,
            since=since,
            symbol=symbol,
            model_name=model_name,
            prospective_only=True,
        )

        # 2. Get Diagnostic Report
        rows = self.analyzer.fetch_data(since=since, symbol=symbol, model_name=model_name)
        diag_report = self.analyzer.run_diagnostics(rows)

        # 3. Reconcile Conclusion
        conclusion, reason = self._determine_conclusion(eval_report, diag_report)

        # 4. Find Best Model Overall
        best_model = self._find_best_model(eval_report)

        # 5. Build Watchlist and Reject List
        watchlist, reject_list = self._build_bucket_lists(diag_report)

        return {
            "eval_report": eval_report,
            "diag_report": diag_report,
            "conclusion": conclusion,
            "reconciliation_reason": reason,
            "best_model_overall": best_model,
            "watchlist": watchlist,
            "reject_list": reject_list,
            "paper_gate_status": "CLOSED",
            "next_gate_requirements": eval_report["promotion_gate"]["requirements"],
        }

    def _determine_conclusion(
        self, eval_report: dict[str, Any], diag_report: dict[str, Any]
    ) -> tuple[str, str]:
        eval_status = eval_report["evidence"]["status"]
        diag_status = diag_report["conclusion"]

        if eval_status == EVAL_DATA_QUALITY or diag_status == DIAG_DATA_QUALITY:
            return RECONCILED_DATA_QUALITY_BLOCKED, "Data quality issues detected in evaluator or diagnostics."

        if eval_status == EDGE_INSUFFICIENT_PROSPECTIVE or diag_status == CONCLUSION_INSUFFICIENT:
            return RECONCILED_INSUFFICIENT_SAMPLE, "Insufficient prospective samples to reach a conclusion."

        if eval_status == EDGE_PROMISING_PROSPECTIVE and diag_status == CONCLUSION_PROMISING:
            return (
                RECONCILED_READY_FOR_HUMAN_REVIEW_ONLY,
                "Both evaluator and diagnostics show promising signal.",
            )

        if eval_status != diag_status:
            diff_reason = f"Evaluator says {eval_status} while Diagnostics says {diag_status}. "
            if eval_status == EDGE_NO_EVIDENCE and diag_status == CONCLUSION_WEAK_CALIBRATION:
                diff_reason += "Diagnostics found slight edge in deltas that Evaluator considered noise."
            elif eval_status == EDGE_WEAK_PROSPECTIVE and diag_status == CONCLUSION_NO_EDGE:
                diff_reason += "Evaluator found enough aggregate delta, but Diagnostics did not see it in MSH buckets."
            
            return RECONCILED_WEAK_SIGNAL_TRACK_ONLY, diff_reason

        if eval_status in (EDGE_WEAK_PROSPECTIVE, EDGE_PROMISING_PROSPECTIVE):
             return RECONCILED_WEAK_SIGNAL_TRACK_ONLY, f"Consistent weak/promising signal detected ({eval_status})."

        return RECONCILED_NO_EDGE, "No significant edge detected by either tool."

    def _find_best_model(self, eval_report: dict[str, Any]) -> dict | None:
        models = eval_report.get("by_model", [])
        eligible = [m for m in models if m.get("labeled_count", 0) > 0 and m.get("accuracy") is not None]
        if not eligible:
            return None
        return max(eligible, key=lambda m: (m["accuracy"], m.get("brier_improvement_vs_random") or -999))

    def _build_bucket_lists(self, diag_report: dict[str, Any]) -> tuple[list[dict], list[dict]]:
        watchlist = []
        reject_list = []
        msh_metrics = diag_report.get("msh_metrics", {})
        
        # Find baselines for comparison
        baselines = {key: m for key, m in msh_metrics.items() if key[0] == PROSPECTIVE_RANDOM_BASELINE}

        for key, m in msh_metrics.items():
            model, symbol, horizon = key
            if model == PROSPECTIVE_RANDOM_BASELINE:
                continue

            base_key = (PROSPECTIVE_RANDOM_BASELINE, symbol, horizon)
            base = baselines.get(base_key)
            
            if not base:
                continue

            acc_delta = m["accuracy"] - base["accuracy"]
            brier_delta = base["brier"] - m["brier"]
            
            bucket_info = {
                "model": model,
                "symbol": symbol,
                "horizon": horizon,
                "sample_count": m["sample_count"],
                "accuracy_delta": acc_delta,
                "brier_delta": brier_delta,
            }

            # Reject List criteria
            if acc_delta <= 0 or brier_delta <= 0:
                reject_list.append(bucket_info)
                continue

            # Watchlist criteria
            # Bucket sample count >= 50 preferred
            # Accuracy above random is interesting but not sufficient
            # Brier improvement must be material (e.g. > 0.005)
            if m["sample_count"] >= 50 and acc_delta > 0.02 and brier_delta > 0.005:
                watchlist.append(bucket_info)
            elif m["sample_count"] >= 20 and acc_delta > 0.05 and brier_delta > 0.01:
                # Smaller sample but very strong signal
                watchlist.append(bucket_info)

        return watchlist, reject_list
