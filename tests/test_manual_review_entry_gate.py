"""Tests for manual-review/non-controllable crypto entry blocking."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = Path(__file__).resolve().parents[1]


def _write_state(root: Path, broker: str, positions: dict) -> None:
    state_dir = root / "state" / broker
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "open_positions.json").write_text(
        json.dumps({"saved_at": "2026-05-26T22:00:00+00:00", "positions": positions}),
        encoding="utf-8",
    )


def _write_config(root: Path) -> None:
    (root / "config_coinbase_crypto.yaml").write_text(
        "\n".join([
            "crypto:",
            "  max_total_crypto_exposure_usd: 4.0",
            "  max_trade_notional_usd: 2.0",
            "global_risk:",
            "  max_total_live_exposure_usd: 6.0",
            "  max_daily_loss_usd: 2.0",
            "  stop_after_consecutive_losses: 2",
            "account:",
            "  disable_live_below_equity: 1.5",
            "",
        ]),
        encoding="utf-8",
    )
    (root / "config_alpaca_stocks.yaml").write_text(
        "\n".join([
            "equities:",
            "  max_total_equity_exposure_usd: 4.0",
            "  max_trade_notional_usd: 2.0",
            "global_risk:",
            "  max_total_live_exposure_usd: 6.0",
            "",
        ]),
        encoding="utf-8",
    )


def _prepare_script_workspace(tmp_path: Path) -> Path:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    shutil.copy(ROOT / "scripts" / "reconcile.sh", scripts_dir / "reconcile.sh")
    _write_config(tmp_path)
    _write_state(tmp_path, "alpaca", {})
    (tmp_path / "runtime").mkdir()
    return tmp_path


def test_reconcile_entry_allowed_false_when_manual_review_position_exists(tmp_path):
    workspace = _prepare_script_workspace(tmp_path)
    _write_state(
        workspace,
        "coinbase",
        {
            "BTC/USD": {
                "asset_class": "crypto",
                "strategy": "coinbase_probe",
                "order_status": "filled",
                "notional": 0.50,
                "counts_toward_exposure": False,
                "user_action_required": True,
                "api_controllable": False,
                "exit_evaluation_enabled": False,
            }
        },
    )

    result = subprocess.run(
        ["bash", "scripts/reconcile.sh"],
        cwd=workspace,
        text=True,
        capture_output=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert "manual_review_open_count        = 1" in result.stdout
    assert "non_controllable_open_count     = 1" in result.stdout
    assert "entry_allowed                   = ❌  NO" in result.stdout
    assert "block_reason                    = manual_review_position_open" in result.stdout


def test_status_script_reports_manual_review_gate_fields():
    text = (ROOT / "scripts" / "status.sh").read_text(encoding="utf-8")

    assert "manual_review_open_count" in text
    assert "non_controllable_open_count" in text
    assert "entry_allowed" in text
    assert "manual_review_position_open" in text
