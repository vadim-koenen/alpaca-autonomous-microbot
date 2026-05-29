import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "clear_recovered_position.sh"


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _run_script(tmp_path, *args):
    env = os.environ.copy()
    env["BOT_DIR_OVERRIDE"] = str(tmp_path)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_clear_recovered_position_moves_only_requested_key(tmp_path):
    open_path = tmp_path / "state" / "coinbase" / "open_positions.json"
    closed_path = tmp_path / "state" / "coinbase" / "closed_positions.json"
    _write_json(
        open_path,
        {
            "saved_at": "2026-05-26T00:00:00+00:00",
            "state_namespace": "coinbase",
            "positions": {
                "ETH/USD": {
                    "asset_class": "crypto",
                    "order_status": "broker_recovered",
                    "notional": 6.07,
                },
                "BTC/USD": {
                    "asset_class": "crypto",
                    "order_status": "filled",
                    "notional": 0.50,
                },
            },
        },
    )

    result = _run_script(
        tmp_path,
        "--broker",
        "coinbase",
        "--key",
        "ETH/USD",
        "--reason",
        "operator verified no API-controllable position remains",
    )

    assert result.returncode == 0, result.stderr
    assert "Cleared recovered position: broker=coinbase key=ETH/USD" in result.stdout
    assert "Restart remains manual" in result.stdout
    assert "secret" not in result.stdout.lower()

    open_state = json.loads(open_path.read_text(encoding="utf-8"))
    closed_state = json.loads(closed_path.read_text(encoding="utf-8"))

    assert set(open_state["positions"]) == {"BTC/USD"}
    archived = list(closed_state["positions"].values())
    assert len(archived) == 1
    assert archived[0]["position_key"] == "ETH/USD"
    assert archived[0]["cleared_by_script"] is True
    assert archived[0]["cleared_reason"] == "operator verified no API-controllable position remains"
    assert "cleared_at" in archived[0]


def test_clear_recovered_position_missing_key_does_not_modify_state(tmp_path):
    open_path = tmp_path / "state" / "alpaca" / "open_positions.json"
    original = {
        "saved_at": "2026-05-26T00:00:00+00:00",
        "state_namespace": "alpaca",
        "positions": {
            "SPY": {
                "asset_class": "equity",
                "order_status": "broker_recovered",
                "notional": 2.0,
            }
        },
    }
    _write_json(open_path, original)

    result = _run_script(
        tmp_path,
        "--broker",
        "alpaca",
        "--key",
        "QQQ",
        "--reason",
        "not present",
    )

    assert result.returncode == 3
    assert "position key not found" in result.stderr
    assert json.loads(open_path.read_text(encoding="utf-8")) == original
    assert not (tmp_path / "state" / "alpaca" / "closed_positions.json").exists()


def test_clear_recovered_position_requires_stopped_bot(tmp_path):
    open_path = tmp_path / "state" / "coinbase" / "open_positions.json"
    _write_json(
        open_path,
        {
            "state_namespace": "coinbase",
            "positions": {
                "ETH/USD": {
                    "asset_class": "crypto",
                    "order_status": "broker_recovered",
                    "notional": 6.07,
                }
            },
        },
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "coinbase.lock").write_text(str(os.getpid()), encoding="utf-8")

    result = _run_script(
        tmp_path,
        "--broker",
        "coinbase",
        "--key",
        "ETH/USD",
        "--reason",
        "operator clear",
    )

    assert result.returncode == 2
    assert "bot appears to be running" in result.stderr
    assert "ETH/USD" in json.loads(open_path.read_text(encoding="utf-8"))["positions"]


def test_clear_recovered_position_script_has_no_live_or_broker_actions():
    script = SCRIPT.read_text(encoding="utf-8")

    forbidden = [
        "launchctl",
        "main.py --mode live",
        "place_order",
        "place_market_order",
        "place_limit_order",
        "cancel_order",
        "submit_order",
        ".env",
    ]
    for token in forbidden:
        assert token not in script
