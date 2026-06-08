from pathlib import Path

from app_shell.runtime_truth import build_runtime_truth


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "app_shell" / "server.py"
RUNTIME_TRUTH = ROOT / "app_shell" / "runtime_truth.py"
APP_JS = ROOT / "app_shell" / "static" / "app.js"
INDEX = ROOT / "app_shell" / "static" / "index.html"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_stop_trading_present_is_reported(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "STOP_TRADING").touch()

    truth = build_runtime_truth(tmp_path)

    assert truth["schema"] == "runtime_truth.v1"
    assert truth["read_only"] is True
    assert truth["broker_calls_made"] is False
    assert truth["order_mutation_performed"] is False
    assert truth["state_mutation_performed"] is False
    assert truth["guards"]["stop_trading_present"] is True
    assert truth["runtime_files"]["runtime/STOP_TRADING"]["present"] is True


def test_missing_runtime_files_are_handled_gracefully(tmp_path):
    truth = build_runtime_truth(tmp_path)

    assert truth["guards"]["stop_trading_present"] is False
    assert truth["runtime_files"]["runtime/STOP_TRADING"]["present"] is False
    assert truth["runtime_files"]["runtime/heartbeat.json"]["present"] is False
    assert truth["runtime_files"]["runtime/coinbase_heartbeat.json"]["present"] is False


def test_json_runtime_file_metadata_is_read_only(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    heartbeat = runtime / "heartbeat.json"
    heartbeat.write_text('{"status":"ok","x":1}', encoding="utf-8")

    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    truth = build_runtime_truth(tmp_path)
    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))

    assert before == after
    info = truth["runtime_files"]["runtime/heartbeat.json"]
    assert info["present"] is True
    assert info["valid_json"] is True
    assert info["keys"] == ["status", "x"]


def test_server_endpoint_route_is_registered():
    text = read(SERVER)
    assert "get_runtime_truth" in text
    assert '"/api/runtime-truth"' in text
    assert "build_runtime_truth(self.repo_root)" in text


def test_ui_labels_exist_in_app_js():
    text = read(APP_JS)
    assert "Runtime Truth" in text
    assert "STOP_TRADING" in text
    assert "Live Process" in text
    assert "Read-only" in text
    assert "/api/runtime-truth" in text


def test_runtime_truth_panel_exists_in_index():
    text = read(INDEX)
    assert 'id="runtime-truth"' in text
    assert 'id="truth-stop-trading"' in text
    assert 'id="truth-live-process"' in text
    assert 'id="truth-read-only"' in text
    assert 'id="truth-json"' in text


def test_forbidden_tokens_absent_from_new_runtime_truth_code():
    checked = "\n".join([
        read(RUNTIME_TRUTH),
        read(APP_JS),
        read(INDEX),
    ])

    forbidden = [
        "." + "env",
        "API" + "_KEY",
        "SEC" + "RET",
        "submit" + "_order",
        "cancel" + "_order",
        "close" + "_position",
        "main.py" + " --mode " + "live",
    ]

    for token in forbidden:
        assert token not in checked
