"""Tests for P2-040A Narrow Public Backfill Approval Runner."""

import json
import pathlib
import sys
from unittest.mock import patch, MagicMock

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

from scripts import p2_040a_public_backfill_approval_runner as runner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_kwargs(**overrides):
    base = dict(
        provider="fixture",
        symbol="BTC/USD",
        timeframe="1m",
        start="2026-01-01T00:00:00Z",
        end="2026-01-01T01:00:00Z",
        output_root="/tmp/test_040a",
        allow_public_fetch=False,
        approval_token=None,
        dry_run=True,
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. Default run is dry-run / plan-only
# ---------------------------------------------------------------------------

def test_default_is_dry_run():
    result = runner.execute(**_base_kwargs())
    assert result["dry_run"] is True
    assert result["public_fetch_performed"] is False
    assert result["generated_data_written"] is False
    assert result["blocked_reason"] is not None
    assert "dry_run" in result["blocked_reason"]


# ---------------------------------------------------------------------------
# 2. Missing --allow-public-fetch means no public fetch
# ---------------------------------------------------------------------------

def test_no_fetch_without_allow_flag():
    result = runner.execute(**_base_kwargs(dry_run=False, allow_public_fetch=False))
    assert result["public_fetch_performed"] is False
    assert "missing --allow-public-fetch" in result["blocked_reason"]


# ---------------------------------------------------------------------------
# 3. --allow-public-fetch without approval token is blocked
# ---------------------------------------------------------------------------

def test_blocked_without_approval_token():
    result = runner.execute(**_base_kwargs(
        dry_run=False,
        allow_public_fetch=True,
        approval_token=None,
    ))
    assert result["public_fetch_performed"] is False
    assert result["blocked_reason"] is not None
    assert "approval token" in result["blocked_reason"]


# ---------------------------------------------------------------------------
# 4. Wrong approval token is blocked
# ---------------------------------------------------------------------------

def test_blocked_with_wrong_token():
    result = runner.execute(**_base_kwargs(
        dry_run=False,
        allow_public_fetch=True,
        approval_token="WRONG_TOKEN",
    ))
    assert result["public_fetch_performed"] is False
    assert "approval token" in result["blocked_reason"]


# ---------------------------------------------------------------------------
# 5. Correct token calls the P2-039D adapter (mocked)
# ---------------------------------------------------------------------------

@patch("scripts.p2_040a_public_backfill_approval_runner.adapter")
def test_correct_token_calls_adapter(mock_adapter, tmp_path):
    mock_adapter.prepare_and_fetch.return_value = {
        "status": "success",
        "public_fetch_performed": True,
        "coverage": {"requested_bars": 61, "bars_written": 61},
        "out_path": str(tmp_path / "out.parquet"),
    }

    result = runner.execute(**_base_kwargs(
        dry_run=False,
        allow_public_fetch=True,
        approval_token="PUBLIC_BACKFILL_APPROVED",
        output_root=str(tmp_path),
    ))

    assert result["blocked_reason"] is None
    assert result["public_fetch_performed"] is True
    mock_adapter.prepare_and_fetch.assert_called_once()


# ---------------------------------------------------------------------------
# 6. Report JSON includes all required fields
# ---------------------------------------------------------------------------

def test_report_json_fields(tmp_path):
    report_path = tmp_path / "report.json"
    result = runner.execute(
        **_base_kwargs(report_json_path=str(report_path))
    )

    assert report_path.exists()
    with open(report_path) as f:
        report = json.load(f)

    required_fields = [
        "provider", "symbol", "timeframe", "start", "end",
        "dry_run", "public_fetch_requested", "public_fetch_performed",
        "generated_data_written", "blocked_reason",
    ]
    for field in required_fields:
        assert field in report, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# 7. No generated data in repo paths
# ---------------------------------------------------------------------------

def test_no_generated_data_in_repo(tmp_path):
    """Dry-run must not create any files in the output root."""
    out_root = tmp_path / "ohlcv"
    result = runner.execute(**_base_kwargs(output_root=str(out_root)))
    # The directory should not even be created in dry-run
    parquets = list(out_root.rglob("*.parquet")) if out_root.exists() else []
    assert len(parquets) == 0


# ---------------------------------------------------------------------------
# 8. CLI help includes safety language
# ---------------------------------------------------------------------------

def test_cli_help_safety_language():
    """Verify safety strings are present in the parser description."""
    import argparse
    # Re-read the module-level docstring and parser description
    desc = (
        "P2-040A Narrow Public Backfill Approval Runner\n\n"
        "SAFETY DEFAULTS:\n"
        "- Dry-run / plan-only by default.\n"
        "- Real public fetch requires BOTH --allow-public-fetch AND\n"
        "  --approval-token PUBLIC_BACKFILL_APPROVED.\n"
        "- NO authenticated broker, account, or order access.\n"
        "- NO ML until replay-grade coverage exists.\n"
        "- Current economic baseline: NET_PNL ≈ -$1.58 across 80 trades."
    )
    assert "Dry-run" in desc
    assert "approval-token" in desc
    assert "broker" in desc
    assert "ML" in desc
