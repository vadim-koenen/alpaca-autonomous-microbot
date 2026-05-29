#!/usr/bin/env python3
"""Advisory evaluation of shadow learner directional baseline predictions."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.redact import redact_text
from shadow_learner.evaluate import build_advisory_evaluation


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _metric_line(row: dict[str, Any], label: str) -> str:
    return (
        f"  {label}: samples={row['sample_count']} labeled={row['labeled_count']} "
        f"missing={row['missing_data_count']} insufficient={row['insufficient_price_history_count']} "
        f"accuracy={_fmt(row['accuracy'])} precision_up={_fmt(row['precision_predicted_up'])} "
        f"recall_up={_fmt(row['recall_actual_up'])} brier={_fmt(row['brier_score'])} "
        f"avg_ret_up={_fmt(row['avg_future_return_pct_when_prediction_gt_0_5'])} "
        f"avg_ret_down={_fmt(row['avg_future_return_pct_when_prediction_lt_0_5'])}"
    )


def _model_label(row: dict[str, Any]) -> str:
    version = row.get("model_version")
    return f"{row.get('model_name')}@{version}"


def _best_worst_models(rows: list[dict[str, Any]]) -> tuple[str, str]:
    eligible = [row for row in rows if row.get("labeled_count", 0) and row.get("accuracy") is not None]
    if not eligible:
        return "n/a", "n/a"
    best = max(eligible, key=lambda row: (row["accuracy"], -(row.get("brier_score") or 999.0)))
    worst = min(eligible, key=lambda row: (row["accuracy"], -(row.get("brier_score") or 999.0)))
    return (
        f"{_model_label(best)} accuracy={_fmt(best['accuracy'])} brier={_fmt(best['brier_score'])}",
        f"{_model_label(worst)} accuracy={_fmt(worst['accuracy'])} brier={_fmt(worst['brier_score'])}",
    )


def _rows_by_limit(rows: list[dict[str, Any]], *, limit: int = 12) -> list[dict[str, Any]]:
    return rows[:limit]


def build_markdown(report: dict[str, Any]) -> str:
    best, worst = _best_worst_models(report["by_model"])
    lines = [
        "# Shadow Learner Advisory Evaluation",
        "",
        f"Window start UTC: {report['window_start_utc'] or 'all'}",
        f"Window end UTC: {report['window_end_utc'] or 'open'}",
        f"Broker: {report['broker']}",
        f"Symbol: {report['symbol']}",
        f"Model filter: {report['model']}",
        f"Prospective only: {'YES' if report.get('prospective_only') else 'NO'}",
        f"Prospective collection days: {report.get('prospective_collection_days', 0)}",
        "",
        "## Evidence Status",
        "",
        f"Result: {report['evidence']['status']}",
        "Reasons:",
        *(f"- {reason}" for reason in report["evidence"]["reasons"]),
        "",
        "Promotion gate: CLOSED",
        "Approved for live trading: NO",
        "",
        "## Required Warnings",
        "",
        *(f"- {warning}" for warning in report["warnings"]),
        "",
        "## Overall Direction Metrics",
        "",
        _metric_line(report["overall"], "overall"),
        f"Actual up/down: {report['overall']['actual_up_count']}/{report['overall']['actual_down_count']}",
        f"Predicted up/down: {report['overall']['predicted_up_count']}/{report['overall']['predicted_down_count']}",
        f"Correct/incorrect: {report['overall']['correct_direction_count']}/{report['overall']['incorrect_direction_count']}",
        f"Average MFE/MAE: {_fmt(report['overall']['avg_max_favorable_excursion_pct'])}/{_fmt(report['overall']['avg_max_adverse_excursion_pct'])}",
        "",
        "## Model Comparison",
        "",
        f"Best model by accuracy: {best}",
        f"Worst model by accuracy: {worst}",
    ]
    for row in report["by_model"]:
        lines.append(_metric_line(row, _model_label(row)))
        lines.append(
            "    "
            f"accuracy_delta_vs_random={_fmt(row.get('accuracy_delta_vs_random'))} "
            f"brier_improvement_vs_random={_fmt(row.get('brier_improvement_vs_random'))}"
        )

    lines.extend(["", "## Calibration Buckets", ""])
    if report["overall"]["calibration"]:
        lines.append("| bucket | samples | avg prediction | actual up rate |")
        lines.append("|---|---:|---:|---:|")
        for row in report["overall"]["calibration"]:
            lines.append(
                f"| {row['bucket']} | {row['sample_count']} | "
                f"{_fmt(row['avg_prediction'])} | {_fmt(row['actual_up_rate'])} |"
            )
    else:
        lines.append("No labeled calibration samples.")

    lines.extend(["", "## By Symbol", ""])
    for row in _rows_by_limit(report["by_symbol"]):
        lines.append(_metric_line(row, str(row["group"])))

    lines.extend(["", "## By Horizon", ""])
    for row in report["by_horizon"]:
        lines.append(_metric_line(row, f"{row['group']}m"))

    lines.extend(["", "## By Symbol And Horizon", ""])
    for row in _rows_by_limit(report["by_symbol_horizon"], limit=20):
        lines.append(_metric_line(row, f"{row['symbol']} {row['horizon_minutes']}m"))

    lines.extend(["", "## By Retrospective Generated", ""])
    for row in report["by_retrospective_generated"]:
        lines.append(_metric_line(row, f"retrospective_generated={row['retrospective_generated']}"))

    lines.extend(["", "## By Prospective Shadow Generated", ""])
    for row in report["by_prospective_shadow_generated"]:
        lines.append(
            _metric_line(row, f"prospective_shadow_generated={row['prospective_shadow_generated']}")
        )

    lines.extend(["", "## By Broker", ""])
    for row in report["by_broker"]:
        lines.append(_metric_line(row, str(row["group"])))

    lines.extend(["", "## By Live Trade Taken", ""])
    for row in report["by_live_trade_taken"]:
        lines.append(_metric_line(row, str(bool(row["group"]))))

    lines.extend(["", "## Price And News Context", ""])
    lines.append(
        f"News context items: {report['news_context']['news_items']} "
        f"(links: {report['news_context']['news_signal_links']}); context only, not causal proof."
    )
    if report["price_context"]:
        for row in report["price_context"]:
            lines.append(
                f"- {row['symbol']}: {row['count']} price points "
                f"{row['first_timestamp_utc']} -> {row['last_timestamp_utc']}"
            )
    else:
        lines.append("- No price context rows found.")

    lines.extend(
        [
            "",
            "## Promotion Gate Requirements",
            "",
            *(f"- {item}" for item in report["promotion_gate"]["requirements"]),
            "",
            "Recommendation: advisory only; not used for live trading",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default=None, help="UTC date or timestamp lower bound")
    parser.add_argument("--until", default=None, help="Optional UTC upper bound")
    parser.add_argument("--broker", default=None, choices=["alpaca", "coinbase"])
    parser.add_argument("--symbol", default=None, help="Optional symbol filter")
    parser.add_argument("--model", default=None, help="Optional model_name filter")
    parser.add_argument(
        "--prospective-only",
        action="store_true",
        help="Evaluate only prospective shadow-generated directional predictions",
    )
    parser.add_argument("--output", default=None, help="Optional markdown report output path")
    parser.add_argument("--db", default=None, help="Optional shadow learner SQLite path")
    args = parser.parse_args()

    report = build_advisory_evaluation(
        db_path=args.db,
        since=args.since,
        until=args.until,
        broker=args.broker,
        symbol=args.symbol,
        model_name=args.model,
        prospective_only=args.prospective_only,
    )
    output = redact_text(build_markdown(report))
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output + "\n", encoding="utf-8")
        print(redact_text(f"Wrote advisory evaluation report: {output_path}"))
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
