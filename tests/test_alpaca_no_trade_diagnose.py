import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts.alpaca_no_trade_diagnose import build_diagnosis, categorize_skip_reason, render_text


ROOT = Path(__file__).resolve().parents[1]


def test_categorize_skip_reason_keywords():
    assert categorize_skip_reason("SCAN SPY equity | invalid quote bid=0 ask=0") == "invalid_quote"
    assert categorize_skip_reason("SCAN SPY equity | stale quote quote_time=x") == "stale_quote"
    assert categorize_skip_reason("SCAN SPY equity | no bars returned") == "no_bars"
    assert categorize_skip_reason("SCAN SPY equity | insufficient bars len=0 < 10") == "insufficient_bars"
    assert categorize_skip_reason("SCAN SPY starter | spread too wide 0.2 > max") == "spread_too_wide"
    assert categorize_skip_reason("SCAN SPY starter | conditions failed trend=False") == "conditions_failed"
    assert categorize_skip_reason("SCAN SPY starter | confidence below threshold 0.50 < min=0.55") == "confidence_below_threshold"


def test_build_diagnosis_from_local_logs_and_journal(tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "runtime").mkdir()
    (tmp_path / "state" / "alpaca").mkdir(parents=True)
    (tmp_path / "config_alpaca_stocks.yaml").write_text(
        """
mode: live
live_trading:
  allow_margin: false
  allow_short_selling: false
global_risk:
  max_total_live_exposure_usd: 6.0
  max_open_positions: 4
equities:
  symbols: [SPY, QQQ]
"""
    )
    (tmp_path / "runtime" / "alpaca_heartbeat.json").write_text(json.dumps({
        "status": "running",
        "mode": "live",
        "last_loop_time": "2026-05-26T15:00:00+00:00",
    }))
    (tmp_path / "state" / "alpaca" / "open_positions.json").write_text(json.dumps({
        "positions": {}
    }))
    (tmp_path / "logs" / "alpaca.launchd.out.log").write_text(
        "\n".join([
            "2026-05-26 10:00:00 | INFO | permissions | PERMISSIONS: Account ok",
            "2026-05-26 10:00:01 | INFO | strategy.equities | SCAN SPY equity | insufficient bars len=0 — skipped",
            "2026-05-26 10:00:02 | INFO | strategy.equities | SCAN QQQ starter | conditions failed trend=False — skipped",
            "2026-05-26 10:00:03 | WARNING | risk_manager | ENTRY_BLOCKED reason=global_exposure_cap_exceeded",
        ])
    )
    journal = tmp_path / "journal_alpaca_stocks.csv"
    with journal.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "decision", "action"])
        writer.writeheader()
        writer.writerow({
            "timestamp": "2026-05-26T15:01:00Z",
            "decision": "PREVIEW",
            "action": "BUY",
        })

    diagnosis = build_diagnosis(
        root=tmp_path,
        now=datetime(2026, 5, 26, 16, 0, tzinfo=timezone.utc),
    )

    assert diagnosis["strategy"]["skip_reasons_last_24h"]["insufficient_bars"] == 1
    assert diagnosis["strategy"]["skip_reasons_last_24h"]["conditions_failed"] == 1
    assert diagnosis["movement"]["proposals_last_24h"] == 1
    assert diagnosis["risk"]["last_entry_block_reason"] == "ENTRY_BLOCKED reason=global_exposure_cap_exceeded"
    assert "ALPACA NO-TRADE DIAGNOSIS" in render_text(diagnosis)
    assert "proposals_last_24h" in render_text(diagnosis, brief=True)


def test_build_diagnosis_since_filters_logs_and_journal_from_calendar_day(tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "runtime").mkdir()
    (tmp_path / "state" / "alpaca").mkdir(parents=True)
    (tmp_path / "config_alpaca_stocks.yaml").write_text(
        """
mode: live
live_trading:
  allow_margin: false
  allow_short_selling: false
global_risk:
  max_total_live_exposure_usd: 6.0
  max_open_positions: 4
equities:
  symbols: [SPY, QQQ]
"""
    )
    (tmp_path / "runtime" / "alpaca_heartbeat.json").write_text(json.dumps({
        "status": "running",
        "mode": "live",
        "last_loop_time": "2026-05-26T15:00:00+00:00",
    }))
    (tmp_path / "state" / "alpaca" / "open_positions.json").write_text(json.dumps({
        "positions": {}
    }))
    (tmp_path / "logs" / "alpaca.launchd.out.log").write_text(
        "\n".join([
            "2026-05-25 10:00:01 | INFO | strategy.equities | SCAN SPY equity | invalid quote bid=0 ask=0 — skipped",
            "2026-05-26 10:00:01 | INFO | strategy.equities | SCAN SPY equity | stale quote quote_time=x — skipped",
            "2026-05-26 10:00:02 | INFO | strategy.equities | SCAN QQQ starter | conditions failed trend=False — skipped",
            "2026-05-26 10:00:03 | WARNING | risk_manager | ENTRY_BLOCKED reason=global_exposure_cap_exceeded",
        ])
    )
    journal = tmp_path / "journal_alpaca_stocks.csv"
    with journal.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "decision", "action"])
        writer.writeheader()
        writer.writerow({
            "timestamp": "2026-05-25T15:01:00Z",
            "decision": "PREVIEW",
            "action": "BUY",
        })
        writer.writerow({
            "timestamp": "2026-05-26T15:01:00Z",
            "decision": "PREVIEW",
            "action": "BUY",
        })
        writer.writerow({
            "timestamp": "2026-05-26T15:02:00Z",
            "decision": "PLACED",
            "action": "BUY",
        })
        writer.writerow({
            "timestamp": "2026-05-26T15:03:00Z",
            "decision": "PLACED",
            "action": "EXIT",
        })

    diagnosis = build_diagnosis(
        root=tmp_path,
        since="2026-05-26",
        now=datetime(2026, 5, 26, 16, 0, tzinfo=timezone.utc),
    )

    counts = diagnosis["strategy"]["skip_reasons_last_24h"]
    assert diagnosis["analysis_window"]["mode"] == "since"
    assert diagnosis["analysis_window"]["since"] == "2026-05-26"
    assert counts["stale_quote"] == 1
    assert counts["conditions_failed"] == 1
    assert "invalid_quote" not in counts
    assert diagnosis["movement"]["proposals_last_24h"] == 1
    assert diagnosis["movement"]["orders_last_24h"] == 2
    assert diagnosis["movement"]["exits_last_24h"] == 1
    rendered = render_text(diagnosis)
    assert "Window:" in rendered
    assert "recommended_next_action" in rendered


def test_cli_rejects_since_and_hours_together(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "alpaca_no_trade_diagnose.py"),
            "--root",
            str(tmp_path),
            "--since",
            "2026-05-26",
            "--hours",
            "6",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=15,
    )

    assert result.returncode != 0
    assert "not allowed with argument" in result.stderr
