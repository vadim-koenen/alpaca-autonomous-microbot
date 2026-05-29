"""Tests for secret-safe diagnostic redaction."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import redact


def test_uuid_and_account_id_are_redacted():
    text = (
        "PERMISSIONS: Account: d4b97f68-9a92-5fc8-8a7f-b654af62059a "
        "account_id=11111111-2222-3333-4444-555555555555 id=abc123xyz"
    )

    redacted = redact.redact_text(text)

    assert "d4b97f68" not in redacted
    assert "11111111-2222-3333-4444-555555555555" not in redacted
    assert "abc123xyz" not in redacted
    assert "Account: [REDACTED_ACCOUNT]" in redacted
    assert "account_id=[REDACTED_ID]" in redacted
    assert "id=[REDACTED_ID]" in redacted


def test_api_key_like_string_is_redacted():
    text = "connected with key PKABCDEF1234567890ABCDEF and status=ACTIVE"

    redacted = redact.redact_text(text)

    assert "PKABCDEF1234567890ABCDEF" not in redacted
    assert "[REDACTED_SECRET]" in redacted
    assert "status=ACTIVE" in redacted


def test_bearer_token_is_redacted():
    text = "Authorization: Bearer fakeBearerToken1234567890"

    redacted = redact.redact_text(text)

    assert "fakeBearerToken1234567890" not in redacted
    assert redacted == "Authorization: [REDACTED_SECRET]"


def test_env_style_secret_line_is_redacted():
    text = "COINBASE_API_SECRET='fake-super-secret-value'\nALPACA_API_KEY=PKFAKE1234567890ABCD"

    redacted = redact.redact_text(text)

    assert "fake-super-secret-value" not in redacted
    assert "PKFAKE1234567890ABCD" not in redacted
    assert "COINBASE_API_SECRET=[REDACTED_SECRET]" in redacted
    assert "ALPACA_API_KEY=[REDACTED_SECRET]" in redacted


def test_symbols_and_numeric_trading_context_remain_visible():
    text = (
        "BTC/USD notional=$0.5000 price=75742.23 cap=$4.00 "
        "AAPL pnl=$0.00 timestamp=2026-05-27T01:36:20Z"
    )

    redacted = redact.redact_text(text)

    assert "BTC/USD" in redacted
    assert "AAPL" in redacted
    assert "$0.5000" in redacted
    assert "75742.23" in redacted
    assert "$4.00" in redacted
    assert "2026-05-27T01:36:20Z" in redacted


def test_status_script_syntax_remains_valid():
    result = subprocess.run(
        ["bash", "-n", str(ROOT / "scripts" / "status.sh")],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
