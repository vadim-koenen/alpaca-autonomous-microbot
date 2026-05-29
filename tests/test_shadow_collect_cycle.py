import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import shadow_collect_cycle as cycle

ROOT = Path(__file__).resolve().parents[1]


def _fake_report(
    *,
    labeled=111,
    missing=1050,
    insufficient=0,
    days=1,
    best_bucket=10,
    accuracy_delta=0.27,
    brier_delta=0.014,
):
    return {
        "overall": {
            "sample_count": 1176,
            "labeled_count": labeled,
            "missing_data_count": missing,
            "insufficient_price_history_count": insufficient,
        },
        "by_symbol_horizon_model": [{"labeled_count": best_bucket}],
        "by_model": [
            {
                "model_name": "prospective_mean_reversion_v0",
                "labeled_count": labeled,
                "accuracy_delta_vs_random": accuracy_delta,
                "brier_improvement_vs_random": brier_delta,
            },
            {
                "model_name": "prospective_random_baseline_v0",
                "labeled_count": labeled,
                "accuracy_delta_vs_random": 0.0,
                "brier_improvement_vs_random": 0.0,
            },
        ],
        "evidence": {"status": "INSUFFICIENT_PROSPECTIVE_DATA"},
        "prospective_collection_days": days,
    }


def _clean_output(name):
    if name == "status_check":
        return "heartbeat_fresh=true\nbroker_recovered_open_count=0\naction_required_items=0\n"
    if name == "reconcile":
        return "manual_review_open_count        = 0\nnon_controllable_open_count     = 0\n"
    if name == "preflight":
        return "STATE_MAINTENANCE_PREFLIGHT overall_status=WARN\nbroker_recovered=0\n"
    if name == "ingest_logs":
        return (
            "Shadow ingest logs\n"
            "Inserted snapshots: 2\n"
            "Created prospective shadow predictions: 12\n"
        )
    if name == "prospective_eval":
        return "Result: INSUFFICIENT_PROSPECTIVE_DATA\nApproved for live trading: NO\n"
    return "Recommendation: advisory only; not used for live trading\n"


def _runner_factory(calls, *, overrides=None):
    overrides = overrides or {}

    def runner(name, command):
        calls.append((name, command))
        output = overrides.get(name, _clean_output(name))
        return cycle.CommandResult(name=name, command=command, returncode=0, stdout=output)

    return runner


def test_collect_cycle_dry_run_writes_no_daily_summary(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cycle, "build_advisory_evaluation", lambda **_kwargs: _fake_report())

    result = cycle.run_cycle(
        since="2026-05-28",
        dry_run=True,
        reports_dir=tmp_path,
        runner=_runner_factory(calls),
    )

    assert result["status"] == "DRY_RUN"
    assert result["summary_path"] is None
    assert not list(tmp_path.glob("shadow_collect_*.md"))
    assert any("--dry-run" in command for name, command in calls if name == "ingest_logs")
    assert any("--dry-run" in command for name, command in calls if name == "label_outcomes")


def test_collect_cycle_blocks_on_stale_heartbeat(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cycle, "build_advisory_evaluation", lambda **_kwargs: _fake_report())

    result = cycle.run_cycle(
        since="2026-05-28",
        reports_dir=tmp_path,
        runner=_runner_factory(calls, overrides={"status_check": "heartbeat_fresh=false\n"}),
    )

    assert result["status"] == "BLOCKED"
    assert any("stale heartbeat" in reason for reason in result["readiness"]["blockers"])
    assert "ingest_logs" not in [name for name, _command in calls]


def test_collect_cycle_blocks_on_manual_review_surprise(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cycle, "build_advisory_evaluation", lambda **_kwargs: _fake_report())

    result = cycle.run_cycle(
        since="2026-05-28",
        reports_dir=tmp_path,
        runner=_runner_factory(
            calls,
            overrides={"reconcile": "manual_review_open_count        = 1\n"},
        ),
    )

    assert result["status"] == "BLOCKED"
    assert any("manual-review" in reason for reason in result["readiness"]["blockers"])
    assert "ingest_logs" not in [name for name, _command in calls]


def test_collect_cycle_stage_order(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cycle, "build_advisory_evaluation", lambda **_kwargs: _fake_report())

    cycle.run_cycle(
        since="2026-05-28",
        reports_dir=tmp_path,
        runner=_runner_factory(calls),
    )

    assert [name for name, _command in calls] == [
        "status_check",
        "reconcile",
        "preflight",
        "ingest_logs",
        "price_refresh",
        "label_outcomes",
        "report",
        "prospective_eval",
        "all_eval",
    ]


def test_collect_cycle_writes_daily_summary(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cycle, "build_advisory_evaluation", lambda **_kwargs: _fake_report())

    result = cycle.run_cycle(
        since="2026-05-28",
        reports_dir=tmp_path,
        runner=_runner_factory(calls),
        now=datetime(2026, 5, 29, tzinfo=timezone.utc),
    )

    path = Path(result["summary_path"])
    assert path == tmp_path / "shadow_collect_2026-05-29.md"
    assert path.exists()
    text = path.read_text()
    assert "Prospective predictions inserted: 12" in text
    assert "Paper validation gate status: PAPER_GATE_BLOCKED_INSUFFICIENT_DAYS" in text
    assert "advisory-only" in text


def test_paper_gate_blocks_with_one_collection_day():
    report = _fake_report(days=1, labeled=111, best_bucket=30, missing=0)

    gate = cycle.paper_gate_from_report(report)

    assert gate["status"] == cycle.PAPER_BLOCKED_DAYS


def test_paper_gate_blocks_when_best_bucket_is_small():
    report = _fake_report(days=2, labeled=111, best_bucket=10, missing=0)

    gate = cycle.paper_gate_from_report(report)

    assert gate["status"] == cycle.PAPER_BLOCKED_BUCKET


def test_paper_gate_ready_for_review_only_when_thresholds_met():
    report = _fake_report(days=2, labeled=120, best_bucket=30, missing=20)

    gate = cycle.paper_gate_from_report(report)

    assert gate["status"] == cycle.PAPER_READY


def test_collect_cycle_does_not_modify_state_files(tmp_path, monkeypatch):
    calls = []
    state_file = tmp_path / "open_positions.json"
    state_file.write_text('{"positions":{}}')
    before = state_file.read_text()
    monkeypatch.setattr(cycle, "build_advisory_evaluation", lambda **_kwargs: _fake_report())

    cycle.run_cycle(
        since="2026-05-28",
        reports_dir=tmp_path / "reports",
        runner=_runner_factory(calls),
    )

    assert state_file.read_text() == before


def test_collect_cycle_source_does_not_import_execution_modules():
    source = (ROOT / "scripts" / "shadow_collect_cycle.py").read_text()

    assert "risk_manager" not in source
    assert "order_manager" not in source
    assert "broker_alpaca" not in source
    assert "broker_coinbase" not in source


def test_collect_cycle_output_redacts_sensitive_values(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cycle, "build_advisory_evaluation", lambda **_kwargs: _fake_report())
    result = cycle.run_cycle(
        since="2026-05-28",
        dry_run=True,
        reports_dir=tmp_path,
        runner=_runner_factory(
            calls,
            overrides={"status_check": "Account: 123456789 API_KEY=APCA1234567890ABCDE BTC/USD\n"},
        ),
    )

    output = result["summary_text"]

    assert "123456789" not in output
    assert "APCA1234567890ABCDE" not in output
    assert "BTC/USD" in output


def test_collect_cycle_cli_dry_run_runs_with_mocked_empty_db(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_collect_cycle.py"),
            "--since",
            "2020-01-01",
            "--dry-run",
            "--db",
            str(db),
            "--reports-dir",
            str(tmp_path / "reports"),
        ],
        text=True,
        capture_output=True,
    )

    # The real readiness scripts may warn in CI, but dry-run must not write reports.
    assert not list((tmp_path / "reports").glob("shadow_collect_*.md"))
    assert "Shadow Prospective Collection Cycle" in result.stdout
