# ADVISORY ONLY - offline tests for Coinbase LaunchAgent classification.
# No launchctl, no restarts, no kills, no broker calls, no .env reads.

from pathlib import Path
import plistlib

from scripts.coinbase_trading_process_audit import build_audit, classify_plist


REPO = "/Users/vadimkoenen/Documents/Claude/Projects/Investing/alpaca-autonomous-microbot"


def _write_plist(path: Path, payload: dict):
    with path.open("wb") as handle:
        plistlib.dump(payload, handle)


def test_classifies_price_logger_as_price_logger(tmp_path):
    plist = tmp_path / "com.vadim.price-path-logger.plist"
    _write_plist(
        plist,
        {
            "Label": "com.vadim.price-path-logger",
            "ProgramArguments": [
                f"{REPO}/.venv/bin/python3",
                f"{REPO}/scripts/coinbase_price_path_logger.py",
            ],
            "WorkingDirectory": REPO,
        },
    )

    result = classify_plist(plist)

    assert result["classification"] == "price_logger"
    assert result["confidence"] == "high"
    assert result["recommended_restart_target"] is None


def test_classifies_coinbase_trading_bot_plist(tmp_path):
    plist = tmp_path / "com.vadim.coinbase-crypto-bot.plist"
    _write_plist(
        plist,
        {
            "Label": "com.vadim.coinbase-crypto-bot",
            "ProgramArguments": [
                f"{REPO}/.venv/bin/python3",
                f"{REPO}/main.py",
                "--mode",
                "live",
            ],
            "WorkingDirectory": REPO,
            "EnvironmentVariables": {
                "BROKER": "coinbase",
                "CONFIG_FILE": "config_coinbase_crypto.yaml",
            },
        },
    )

    result = classify_plist(plist)

    assert result["classification"] == "trading_bot"
    assert result["confidence"] == "high"
    assert result["recommended_restart_target"] == "com.vadim.coinbase-crypto-bot"


def test_unknown_plist_gets_no_restart_recommendation(tmp_path):
    plist = tmp_path / "com.example.unrelated.plist"
    _write_plist(
        plist,
        {
            "Label": "com.example.unrelated",
            "ProgramArguments": ["/usr/bin/true"],
        },
    )

    result = classify_plist(plist)

    assert result["classification"] == "unknown"
    assert result["recommended_restart_target"] is None


def test_audit_recommends_only_trading_bot_restart_target(tmp_path):
    _write_plist(
        tmp_path / "com.vadim.price-path-logger.plist",
        {
            "Label": "com.vadim.price-path-logger",
            "ProgramArguments": [f"{REPO}/.venv/bin/python3", f"{REPO}/scripts/coinbase_price_path_logger.py"],
            "WorkingDirectory": REPO,
        },
    )
    _write_plist(
        tmp_path / "com.vadim.coinbase-crypto-bot.plist",
        {
            "Label": "com.vadim.coinbase-crypto-bot",
            "ProgramArguments": [f"{REPO}/.venv/bin/python3", f"{REPO}/main.py", "--mode", "live"],
            "WorkingDirectory": REPO,
            "EnvironmentVariables": {"BROKER": "coinbase", "CONFIG_FILE": "config_coinbase_crypto.yaml"},
        },
    )

    audit = build_audit(tmp_path)

    assert audit["verdict"] == "TRADING_BOT_PLIST_FOUND"
    assert audit["trading_bot_found"] is True
    assert audit["price_logger_found"] is True
    assert audit["recommended_restart_targets"] == ["com.vadim.coinbase-crypto-bot"]
    assert audit["safety"]["launchctl_mutation"] is False
    assert audit["safety"]["process_kill_or_restart"] is False
