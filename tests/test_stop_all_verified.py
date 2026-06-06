import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "stop_all_verified.sh"


def make_fake_commands(tmp_path: Path, pids: str, alive: str = "") -> tuple[Path, Path, Path]:
    calls = tmp_path / "kill_calls.txt"
    fake_pgrep = tmp_path / "fake_pgrep"
    fake_kill = tmp_path / "fake_kill"
    escaped_pids = pids.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    fake_pgrep.write_text(
        f'#!/usr/bin/env bash\nprintf \'%b\' "{escaped_pids}"\n',
        encoding="utf-8",
    )
    fake_kill.write_text(
        "#!/usr/bin/env bash\n"
        f"echo \"$*\" >> {str(calls)!r}\n"
        "if [[ \"$1\" == \"-0\" ]]; then\n"
        f"  [[ \" {alive} \" == *\" $2 \"* ]]\n"
        "  exit $?\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_pgrep.chmod(0o755)
    fake_kill.chmod(0o755)
    return fake_pgrep, fake_kill, calls


def run_script(tmp_path: Path, pids: str, *args: str, alive: str = "") -> tuple[subprocess.CompletedProcess, Path]:
    root = tmp_path / "repo"
    (root / "runtime").mkdir(parents=True)
    fake_pgrep, fake_kill, calls = make_fake_commands(tmp_path, pids, alive)
    env = {
        **os.environ,
        "BOT_DIR_OVERRIDE": str(root),
        "PGREP_BIN": str(fake_pgrep),
        "KILL_BIN": str(fake_kill),
    }
    completed = subprocess.run(
        ["bash", str(SCRIPT), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    return completed, calls


def test_verified_stop_creates_and_retains_kill_switch(tmp_path):
    completed, calls = run_script(tmp_path, "", "--wait-seconds", "0")
    assert completed.returncode == 0
    assert "VERIFIED_STOPPED" in completed.stdout
    assert (tmp_path / "repo" / "runtime" / "STOP_TRADING").exists()
    assert not calls.exists()


def test_remaining_processes_exit_nonzero_and_print_pids_without_signals(tmp_path):
    completed, calls = run_script(tmp_path, "34217\n34222\n", "--wait-seconds", "0")
    assert completed.returncode == 2
    assert "34217 34222" in completed.stdout + completed.stderr
    assert not calls.exists()
    assert (tmp_path / "repo" / "runtime" / "STOP_TRADING").exists()


def test_explicit_term_after_sends_sigterm(tmp_path):
    completed, calls = run_script(
        tmp_path,
        "34217\n",
        "--wait-seconds",
        "0",
        "--term-after",
        "0",
    )
    assert completed.returncode == 2
    assert "-TERM 34217" in calls.read_text(encoding="utf-8")
    assert "-KILL" not in calls.read_text(encoding="utf-8")


def test_active_lock_pid_is_reported(tmp_path):
    root = tmp_path / "repo"
    (root / "runtime").mkdir(parents=True)
    (root / "runtime" / "coinbase.lock").write_text("34222\n", encoding="utf-8")
    fake_pgrep, fake_kill, calls = make_fake_commands(tmp_path, "", "34222")
    completed = subprocess.run(
        ["bash", str(SCRIPT), "--wait-seconds", "0"],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "BOT_DIR_OVERRIDE": str(root),
            "PGREP_BIN": str(fake_pgrep),
            "KILL_BIN": str(fake_kill),
        },
    )
    assert completed.returncode == 2
    assert "34222" in completed.stdout + completed.stderr
    assert "-0 34222" in calls.read_text(encoding="utf-8")


def test_script_never_removes_stop_or_restarts():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "rm " not in text
    assert "launchctl" not in text
    assert "start_all" not in text
