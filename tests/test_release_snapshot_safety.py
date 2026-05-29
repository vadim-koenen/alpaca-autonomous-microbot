from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_snapshot_script_excludes_secret_bearing_paths():
    script = (ROOT / "scripts" / "make_release_snapshot.sh").read_text()

    for expected in [
        "--exclude='.env'",
        "--exclude='.env.*'",
        "--exclude='.venv'",
        "--exclude='__pycache__'",
        "--exclude='.pytest_cache'",
        "--exclude='logs'",
        "--exclude='memory/bot_memory.sqlite3'",
        "--exclude='secrets'",
    ]:
        assert expected in script


def test_release_snapshot_script_declares_no_deploy_or_restart():
    script = (ROOT / "scripts" / "make_release_snapshot.sh").read_text()
    assert '"deploys": False' in script
    assert '"restarts_bots": False' in script
    assert "launchctl" not in script
    assert "main.py --mode live" not in script


def test_version_and_releases_baseline_exist():
    assert (ROOT / "VERSION").read_text().strip() == "v0.1.0-safety-baseline"
    releases = (ROOT / "RELEASES.md").read_text()
    assert "v0.1.0-safety-baseline" in releases
    assert "No auto-deploy exists" in releases
