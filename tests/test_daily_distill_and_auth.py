import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.event_store import EventStore

ROOT = Path(__file__).resolve().parents[1]


def _load_script(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_daily_distill_outputs_markdown_and_json(tmp_path):
    db = tmp_path / "memory.sqlite3"
    out_dir = tmp_path / "distillations"
    store = EventStore(db)
    store.start_run(
        bot_name="coinbase_crypto",
        broker="coinbase",
        mode="dry_run",
        asset_class="crypto",
        config_hash="abc123",
        payload={},
    )
    store.record_event(event_type="startup", broker="coinbase", asset_class="crypto")
    store.record_risk_decision(
        allowed=False,
        reason="external/untradeable exposure",
        broker="coinbase",
        asset_class="crypto",
        strategy="coinbase_probe",
        symbol="BTC/USD",
        requested_notional=0.5,
        current_exposure=6.18,
        projected_exposure=6.68,
        cap_name="crypto.max_total_crypto_exposure_usd",
        cap_value=4.0,
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/daily_distill.py",
            "--date",
            "2026-05-26",
            "--db",
            str(db),
            "--output-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    md_path = out_dir / "daily_summary_2026-05-26.md"
    json_path = out_dir / "daily_summary_2026-05-26.json"
    assert md_path.exists()
    assert json_path.exists()
    assert "Daily Summary" in md_path.read_text()
    data = json.loads(json_path.read_text())
    assert data["date"] == "2026-05-26"


def test_alpaca_auth_diagnostics_are_secret_safe(monkeypatch):
    monkeypatch.setenv("ALPACA_PAPER", "true")
    monkeypatch.setenv("ALPACA_API_KEY", "VISIBLE_SHOULD_NOT_PRINT")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "SECRET_SHOULD_NOT_PRINT")
    monkeypatch.setenv("LIVE_TRADING", "false")
    monkeypatch.setenv("CONFIG_FILE", "config_alpaca_stocks.yaml")
    import utils
    utils._config = None

    mod = _load_script(ROOT / "scripts" / "check_alpaca_auth_config.py", "check_alpaca_auth_config")
    try:
        diag = mod.collect_diagnostics()
        rendered = json.dumps(diag, sort_keys=True)
    finally:
        utils._config = None

    assert diag["alpaca_paper"] is True
    assert diag["selected_endpoint"] == "paper"
    assert diag["fallback_api_key_present"] is True
    assert diag["fallback_secret_present"] is True
    assert "VISIBLE_SHOULD_NOT_PRINT" not in rendered
    assert "SECRET_SHOULD_NOT_PRINT" not in rendered
