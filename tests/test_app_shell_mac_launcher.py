from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "launch_app_shell_mac.sh"
APPLESCRIPT = ROOT / "app_shell" / "macos" / "InvestingBotLauncher.applescript"
DOCS = ROOT / "docs" / "APP_SHELL_MAC_LAUNCHER.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_mac_launcher_files_exist():
    assert LAUNCHER.exists()
    assert APPLESCRIPT.exists()
    assert DOCS.exists()


def test_launcher_starts_existing_app_shell_script():
    text = read(LAUNCHER)

    assert "scripts/run_app_shell.py" in text
    assert 'PYTHONPATH=".:scripts"' in text
    assert "reports/app_shell" in text
    assert "http://localhost:${PORT}" in text
    assert 'open "$URL"' in text
    assert "lsof -iTCP" in text


def test_applescript_launches_repo_launcher_and_chrome():
    text = read(APPLESCRIPT)

    assert "alpaca-autonomous-microbot" in text
    assert "scripts/launch_app_shell_mac.sh" in text
    assert "http://localhost:8080" in text
    assert 'tell application "Google Chrome"' in text


def test_docs_include_compile_troubleshooting_and_safety_notes():
    text = read(DOCS)

    assert "osacompile" in text
    assert 'open "Investing Bot.app"' in text
    assert "lsof -iTCP:8080" in text
    assert "reports/app_shell/app_shell_<timestamp>.log" in text
    assert "read-only" in text.lower()
    assert "does not remove `runtime/STOP_TRADING`" in text
    assert "does not restart live trading" in text.lower()
    assert "does not run `main.py --mode live`" in text
    assert "does not scale or change strategy" in text.lower()


def test_executable_launcher_paths_do_not_include_trading_mutation_hooks():
    checked_text = "\n".join(
        [
            read(LAUNCHER),
            read(APPLESCRIPT),
        ]
    )

    forbidden_tokens = [
        "main.py --mode live",
        "rm runtime/STOP_TRADING",
        "mv runtime/STOP_TRADING",
        "unlink runtime/STOP_TRADING",
        "place_order",
        "cancel_order",
        "close_position",
        "broker_coinbase",
        "broker_alpaca",
        "coinbase_broker",
    ]

    for token in forbidden_tokens:
        assert token not in checked_text
