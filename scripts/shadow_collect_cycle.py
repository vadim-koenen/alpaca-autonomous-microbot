#!/usr/bin/env python3
"""Run a repeatable advisory-only shadow learner collection cycle."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.redact import redact_text
from shadow_learner.evaluate import (
    MIN_PROSPECTIVE_COLLECTION_DAYS,
    PROSPECTIVE_RANDOM_BASELINE_MODEL,
    build_advisory_evaluation,
)
from shadow_learner.price_coverage import (
    MIN_DIRECTIONAL_LABELS_FOR_EVALUATION,
    MIN_SYMBOL_HORIZON_LABELS_FOR_EVALUATION,
)
from shadow_learner.schema import resolve_db_path

PAPER_BLOCKED_DAYS = "PAPER_GATE_BLOCKED_INSUFFICIENT_DAYS"
PAPER_BLOCKED_SAMPLE = "PAPER_GATE_BLOCKED_SAMPLE_SIZE"
PAPER_BLOCKED_BUCKET = "PAPER_GATE_BLOCKED_BUCKET_SIZE"
PAPER_BLOCKED_EDGE = "PAPER_GATE_BLOCKED_NO_EDGE_VS_RANDOM"
PAPER_BLOCKED_DATA = "PAPER_GATE_BLOCKED_DATA_QUALITY"
PAPER_READY = "PAPER_GATE_READY_FOR_REVIEW"


@dataclass(frozen=True)
class CommandResult:
    name: str
    command: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""


CommandRunner = Callable[[str, list[str]], CommandResult]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _default_runner(name: str, command: list[str]) -> CommandResult:
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return CommandResult(
        name=name,
        command=command,
        returncode=result.returncode,
        stdout=redact_text(result.stdout),
        stderr=redact_text(result.stderr),
    )


def _combined(results: list[CommandResult]) -> str:
    return "\n".join(redact_text(result.stdout + "\n" + result.stderr) for result in results)


def _metric_from_output(text: str, label: str) -> int | None:
    match = re.search(
        rf"^\s*{re.escape(label)}\s*(?::|=)\s*([0-9,]+)",
        text,
        flags=re.MULTILINE,
    )
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def _nonzero_metric(text: str, label: str) -> bool:
    value = _metric_from_output(text, label)
    return value is not None and value != 0


def analyze_readiness(results: list[CommandResult]) -> dict[str, Any]:
    """Return readiness blockers from read-only status/reconcile/preflight output."""
    text = _combined(results)
    blockers: list[str] = []
    warnings: list[str] = []

    if "STOP_AND_REVIEW" in text:
        blockers.append("STOP_AND_REVIEW condition present")
    if "heartbeat_fresh=false" in text or "heartbeat_fresh=false" in text.lower():
        blockers.append("stale heartbeat detected")
    if re.search(r"\bduplicate\b", text, flags=re.IGNORECASE):
        blockers.append("duplicate process indicator detected")
    if _nonzero_metric(text, "manual_review_open_count"):
        blockers.append("manual-review open position count is nonzero")
    if _nonzero_metric(text, "non_controllable_open_count"):
        blockers.append("non-controllable open position count is nonzero")
    if _nonzero_metric(text, "broker_recovered_open_count"):
        blockers.append("broker_recovered open position count is nonzero")
    if _nonzero_metric(text, "action_required_items"):
        blockers.append("action-required open position count is nonzero")
    if re.search(
        r"ETH/USD.*(broker_recovered|manual[-_ ]review|readopt|re-adopt|drop)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        blockers.append("possible active ETH recovery churn detected")

    for result in results:
        if result.returncode and result.name != "preflight":
            warnings.append(f"{result.name} exited with code {result.returncode}")
        if result.returncode and result.name == "preflight":
            warnings.append("preflight returned WARN/nonzero; continuing only if no blockers are present")

    status = "READY" if not blockers else "BLOCKED"
    if not blockers and warnings:
        status = "READY_WITH_WARNINGS"
    return {
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
    }


def paper_gate_from_report(report: dict[str, Any], *, safety_blockers: list[str] | None = None) -> dict[str, Any]:
    """Evaluate whether prospective evidence is ready for human paper-review."""
    blockers: list[str] = list(safety_blockers or [])
    overall = report["overall"]
    labeled = int(overall["labeled_count"])
    missing = int(overall["missing_data_count"])
    insufficient = int(overall["insufficient_price_history_count"])
    collection_days = int(report.get("prospective_collection_days", 0))
    best_bucket = max(
        (int(row["labeled_count"]) for row in report.get("by_symbol_horizon_model", [])),
        default=0,
    )
    best_model = None
    non_random = [
        row
        for row in report.get("by_model", [])
        if row.get("model_name") != PROSPECTIVE_RANDOM_BASELINE_MODEL
        and row.get("labeled_count", 0) >= MIN_DIRECTIONAL_LABELS_FOR_EVALUATION
    ]
    if non_random:
        best_model = max(
            non_random,
            key=lambda row: (
                row.get("accuracy_delta_vs_random")
                if row.get("accuracy_delta_vs_random") is not None
                else -999.0,
                row.get("brier_improvement_vs_random")
                if row.get("brier_improvement_vs_random") is not None
                else -999.0,
            ),
        )
    accuracy_delta = (best_model or {}).get("accuracy_delta_vs_random") or 0.0
    brier_delta = (best_model or {}).get("brier_improvement_vs_random") or 0.0
    beats_random = accuracy_delta >= 0.05 and brier_delta >= 0.01

    reasons = [
        f"collection_days={collection_days}/{MIN_PROSPECTIVE_COLLECTION_DAYS}",
        f"labeled_prospective_directional_outcomes={labeled}/{MIN_DIRECTIONAL_LABELS_FOR_EVALUATION}",
        f"best_symbol_horizon_model_bucket={best_bucket}/{MIN_SYMBOL_HORIZON_LABELS_FOR_EVALUATION}",
        f"missing_data={missing}",
        f"insufficient_price_history={insufficient}",
        f"best_accuracy_delta_vs_random={accuracy_delta:.3f}",
        f"best_brier_improvement_vs_random={brier_delta:.3f}",
    ]

    if blockers:
        return {"status": PAPER_BLOCKED_DATA, "reasons": blockers + reasons}
    if collection_days < MIN_PROSPECTIVE_COLLECTION_DAYS:
        return {"status": PAPER_BLOCKED_DAYS, "reasons": reasons}
    if labeled < MIN_DIRECTIONAL_LABELS_FOR_EVALUATION:
        return {"status": PAPER_BLOCKED_SAMPLE, "reasons": reasons}
    if best_bucket < MIN_SYMBOL_HORIZON_LABELS_FOR_EVALUATION:
        return {"status": PAPER_BLOCKED_BUCKET, "reasons": reasons}
    if missing + insufficient > labeled * 5:
        return {"status": PAPER_BLOCKED_DATA, "reasons": reasons}
    if not beats_random:
        return {"status": PAPER_BLOCKED_EDGE, "reasons": reasons}
    return {"status": PAPER_READY, "reasons": reasons}


def _command(base: list[str], *, db_path: str | Path | None, dry_run: bool) -> list[str]:
    command = list(base)
    if db_path:
        command.extend(["--db", str(db_path)])
    if dry_run:
        command.append("--dry-run")
    return command


def _empty_prospective_report() -> dict[str, Any]:
    return {
        "overall": {
            "sample_count": 0,
            "labeled_count": 0,
            "missing_data_count": 0,
            "insufficient_price_history_count": 0,
        },
        "by_symbol_horizon_model": [],
        "by_model": [],
        "evidence": {"status": "INSUFFICIENT_PROSPECTIVE_DATA"},
        "prospective_collection_days": 0,
    }


def _stage_outputs(results: list[CommandResult]) -> list[str]:
    lines = []
    for result in results:
        lines.append(f"### {result.name}")
        lines.append("")
        lines.append(f"Command: `{' '.join(result.command)}`")
        lines.append(f"Exit code: {result.returncode}")
        combined = redact_text((result.stdout + "\n" + result.stderr).strip())
        if combined:
            lines.append("")
            lines.append("```text")
            lines.append("\n".join(combined.splitlines()[:80]))
            lines.append("```")
        lines.append("")
    return lines


def build_daily_summary(
    *,
    since: str,
    dry_run: bool,
    readiness: dict[str, Any],
    results: list[CommandResult],
    prospective_report: dict[str, Any],
    paper_gate: dict[str, Any],
) -> str:
    ingest_output = next((result.stdout for result in results if result.name == "ingest_logs"), "")
    overall = prospective_report["overall"]
    best_bucket = max(
        (int(row["labeled_count"]) for row in prospective_report.get("by_symbol_horizon_model", [])),
        default=0,
    )
    lines = [
        "# Shadow Prospective Collection Cycle",
        "",
        f"Run timestamp UTC: {_utc_now()}",
        f"Since: {since}",
        f"Mode: {'dry-run' if dry_run else 'write'}",
        f"Readiness status: {readiness['status']}",
        f"Readiness blockers: {', '.join(readiness['blockers']) if readiness['blockers'] else 'none'}",
        f"Readiness warnings: {', '.join(readiness['warnings']) if readiness['warnings'] else 'none'}",
        "",
        "## Daily Metrics",
        "",
        f"Snapshots inserted: {_metric_from_output(ingest_output, 'Inserted snapshots') or 0}",
        f"Prospective predictions inserted: {_metric_from_output(ingest_output, 'Created prospective shadow predictions') or 0}",
        f"Prospective predictions total: {overall['sample_count']}",
        f"Prospective labeled outcomes total: {overall['labeled_count']}",
        f"Prospective missing_data total: {overall['missing_data_count']}",
        f"Best prospective symbol/horizon/model bucket: {best_bucket}",
        f"Collection days: {prospective_report.get('prospective_collection_days', 0)}",
        f"Prospective-only evaluation status: {prospective_report['evidence']['status']}",
        f"Paper validation gate status: {paper_gate['status']}",
        "Paper validation gate reasons:",
        *(f"- {reason}" for reason in paper_gate["reasons"]),
        "",
        "## Safety Confirmation",
        "",
        "- Advisory-only shadow collection; not used for live trading.",
        "- advisory-only confirmation: shadow outputs remain detached from trading actions.",
        "- No live mode, order, restart, launchctl, config, risk, strategy, dead_chop, environment-secret action was performed by this cycle.",
        "- No learner output is approved for live orders, risk approvals, sizing, symbol selection, or paper validation.",
        "",
        "## Stage Outputs",
        "",
        *_stage_outputs(results),
    ]
    return redact_text("\n".join(lines).rstrip() + "\n")


def _summary_path(reports_dir: str | Path | None, *, now: datetime | None = None) -> Path:
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return Path(reports_dir or (ROOT / "reports")) / f"shadow_collect_{timestamp.date().isoformat()}.md"


def run_cycle(
    *,
    since: str,
    dry_run: bool = False,
    prospective_only: bool = False,
    db_path: str | Path | None = None,
    reports_dir: str | Path | None = None,
    runner: CommandRunner | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run the collection cycle. Writes only advisory shadow DB/report files."""
    command_runner = runner or _default_runner
    results: list[CommandResult] = []

    for name, command in (
        ("status_check", ["bash", "scripts/status.sh"]),
        ("reconcile", ["bash", "scripts/reconcile.sh"]),
        ("preflight", ["bash", "scripts/state_maintenance_preflight.sh"]),
    ):
        results.append(command_runner(name, command))

    readiness = analyze_readiness(results)
    if readiness["blockers"]:
        return {
            "status": "BLOCKED",
            "readiness": readiness,
            "results": results,
            "summary_path": None,
            "paper_gate": {"status": PAPER_BLOCKED_DATA, "reasons": readiness["blockers"]},
        }

    stages = [
        (
            "ingest_logs",
            _command(
                ["python3", "scripts/shadow_ingest_logs.py", "--since", since],
                db_path=db_path,
                dry_run=dry_run,
            ),
        ),
        (
            "price_refresh",
            _command(
                [
                    "python3",
                    "scripts/shadow_backfill_prices.py",
                    "--from-predictions",
                    "--since",
                    since,
                    "--granularity",
                    "60",
                ],
                db_path=db_path,
                dry_run=dry_run,
            ),
        ),
    ]
    dry_run_db_missing = dry_run and not resolve_db_path(db_path).exists()
    if not dry_run_db_missing:
        stages.extend(
            [
                (
                    "label_outcomes",
                    _command(
                        ["python3", "scripts/shadow_label_outcomes.py", "--since", since],
                        db_path=db_path,
                        dry_run=dry_run,
                    ),
                ),
                (
                    "report",
                    _command(
                        ["python3", "scripts/shadow_learner_report.py", "--since", since],
                        db_path=db_path,
                        dry_run=False,
                    ),
                ),
                (
                    "prospective_eval",
                    _command(
                        [
                            "python3",
                            "scripts/shadow_evaluate_predictions.py",
                            "--since",
                            since,
                            "--prospective-only",
                        ],
                        db_path=db_path,
                        dry_run=False,
                    ),
                ),
            ]
        )
    if not prospective_only and not dry_run_db_missing:
        stages.append(
            (
                "all_eval",
                _command(
                    ["python3", "scripts/shadow_evaluate_predictions.py", "--since", since],
                    db_path=db_path,
                    dry_run=False,
                ),
            )
        )

    for name, command in stages:
        result = command_runner(name, command)
        results.append(result)
        if result.returncode and name in {"ingest_logs", "label_outcomes", "report", "prospective_eval"}:
            readiness["blockers"].append(f"{name} exited with code {result.returncode}")
            return {
                "status": "BLOCKED",
                "readiness": readiness,
                "results": results,
                "summary_path": None,
                "paper_gate": {"status": PAPER_BLOCKED_DATA, "reasons": readiness["blockers"]},
            }
    if dry_run_db_missing:
        skip_text = "Skipped in dry-run because the selected shadow DB does not exist; no DB was created."
        for name in ("label_outcomes", "report", "prospective_eval"):
            results.append(CommandResult(name=name, command=["skipped"], returncode=0, stdout=skip_text))

    if dry_run_db_missing:
        prospective_report = _empty_prospective_report()
    else:
        prospective_report = build_advisory_evaluation(
            db_path=db_path,
            since=since,
            prospective_only=True,
        )
    price_refresh = next((result for result in results if result.name == "price_refresh"), None)
    safety_blockers = []
    if price_refresh is not None and price_refresh.returncode:
        safety_blockers.append(f"price_refresh exited with code {price_refresh.returncode}")
    paper_gate = paper_gate_from_report(prospective_report, safety_blockers=safety_blockers)

    summary_text = build_daily_summary(
        since=since,
        dry_run=dry_run,
        readiness=readiness,
        results=results,
        prospective_report=prospective_report,
        paper_gate=paper_gate,
    )
    summary_path = None
    if not dry_run:
        summary_path = _summary_path(reports_dir, now=now)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(summary_text, encoding="utf-8")

    return {
        "status": "DRY_RUN" if dry_run else "COMPLETED",
        "readiness": readiness,
        "results": results,
        "prospective_report": prospective_report,
        "paper_gate": paper_gate,
        "summary_path": str(summary_path) if summary_path else None,
        "summary_text": summary_text,
    }


def build_output(result: dict[str, Any]) -> str:
    readiness = result["readiness"]
    lines = [
        "Shadow Prospective Collection Cycle",
        f"Status: {result['status']}",
        f"Readiness: {readiness['status']}",
    ]
    if readiness["blockers"]:
        lines.append("Readiness blockers:")
        lines.extend(f"  {item}" for item in readiness["blockers"])
    if readiness["warnings"]:
        lines.append("Readiness warnings:")
        lines.extend(f"  {item}" for item in readiness["warnings"])

    paper_gate = result.get("paper_gate") or {}
    if paper_gate:
        lines.append(f"Paper gate: {paper_gate['status']}")
        lines.append("Paper gate reasons:")
        lines.extend(f"  {item}" for item in paper_gate.get("reasons", []))

    for stage in result.get("results", []):
        if stage.name == "ingest_logs":
            lines.extend(
                [
                    f"Snapshots inserted: {_metric_from_output(stage.stdout, 'Inserted snapshots') or 0}",
                    f"Prospective predictions inserted: {_metric_from_output(stage.stdout, 'Created prospective shadow predictions') or 0}",
                ]
            )
        if stage.name == "prospective_eval":
            status_match = re.search(r"^Result:\s*(.+)$", stage.stdout, flags=re.MULTILINE)
            if status_match:
                lines.append(f"Prospective-only evaluation: {status_match.group(1)}")

    if result.get("prospective_report"):
        overall = result["prospective_report"]["overall"]
        lines.extend(
            [
                f"Prospective predictions total: {overall['sample_count']}",
                f"Prospective labeled outcomes total: {overall['labeled_count']}",
                f"Prospective missing_data total: {overall['missing_data_count']}",
                f"Collection days: {result['prospective_report'].get('prospective_collection_days', 0)}",
            ]
        )
    lines.append(f"Daily summary path: {result.get('summary_path') or 'not written'}")
    lines.append("Recommendation: advisory only; not used for live trading")
    return redact_text("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", required=True, help="UTC date or timestamp lower bound")
    parser.add_argument("--dry-run", action="store_true", help="Run without shadow DB/report writes")
    parser.add_argument("--prospective-only", action="store_true", help="Skip all-data evaluation stage")
    parser.add_argument("--db", default=None, help="Optional shadow learner SQLite path")
    parser.add_argument("--reports-dir", default=str(ROOT / "reports"), help="Daily summary output directory")
    args = parser.parse_args()

    result = run_cycle(
        since=args.since,
        dry_run=args.dry_run,
        prospective_only=args.prospective_only,
        db_path=args.db,
        reports_dir=args.reports_dir,
    )
    print(build_output(result))
    return 1 if result["status"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
