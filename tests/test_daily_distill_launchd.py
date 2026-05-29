"""Static validation for the advisory daily_distill launchd plist."""

from __future__ import annotations

import plistlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLIST = ROOT / "launchd" / "com.vadim.daily-distill.plist"


def _load_plist() -> dict:
    with PLIST.open("rb") as f:
        return plistlib.load(f)


def test_daily_distill_plist_exists_and_runs_only_distill_script():
    payload = _load_plist()

    assert payload["Label"] == "com.vadim.daily-distill"

    # WorkingDirectory must point to the repo root — the plist stores the
    # absolute Mac path which differs from the sandbox-resolved ROOT, so we
    # check the suffix rather than requiring an exact match.
    wd = payload["WorkingDirectory"]
    assert wd.endswith("alpaca-autonomous-microbot"), (
        f"WorkingDirectory should end with 'alpaca-autonomous-microbot', got: {wd!r}"
    )

    args = payload["ProgramArguments"]
    # python3 interpreter must come from the venv inside the repo
    assert args[0].endswith(str(Path(".venv") / "bin" / "python3")), (
        f"ProgramArguments[0] should be venv python3, got: {args[0]!r}"
    )
    # Second argument must be the distill script, not main.py or anything else
    assert args[1] == "scripts/daily_distill.py", (
        f"ProgramArguments[1] should be scripts/daily_distill.py, got: {args[1]!r}"
    )
    assert len(args) == 2, f"Expected exactly 2 ProgramArguments, got: {args}"
    assert "main.py" not in args
    assert not any("launchctl" in arg for arg in args)


def test_daily_distill_plist_schedule_is_2355_utc_process_time():
    payload = _load_plist()

    assert payload["StartCalendarInterval"] == {"Hour": 23, "Minute": 55}
    assert payload["EnvironmentVariables"]["TZ"] == "UTC"
    assert payload["RunAtLoad"] is False
    assert "KeepAlive" not in payload


def test_daily_distill_plist_logs_to_distinct_files():
    payload = _load_plist()

    assert payload["StandardOutPath"].endswith("logs/daily_distill.launchd.out.log")
    assert payload["StandardErrorPath"].endswith("logs/daily_distill.launchd.err.log")


def test_operations_docs_include_install_later_warning():
    text = (ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")

    assert "python3 scripts/daily_distill.py" in text
    assert "launchd/com.vadim.daily-distill.plist" in text
    assert "Do not install, load, bootstrap, start, or kickstart" in text
    assert "advisory memory/reporting only" in text
