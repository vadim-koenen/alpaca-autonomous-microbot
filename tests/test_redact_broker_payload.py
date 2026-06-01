# ADVISORY ONLY — tests for the broker payload redaction helper (P2-019F)

import json
from pathlib import Path
import importlib.util
import sys

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "redact_broker_payload.py"
spec = importlib.util.spec_from_file_location("redact", SCRIPT)
redact = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = redact
spec.loader.exec_module(redact)


def test_redacts_sensitive_keys():
    payload = {
        "trade_id": "abc123",
        "account_id": "very-secret-account",
        "fee": 0.01,
        "details": {"portfolio_id": "port-999", "size": 0.01}
    }
    redacted = redact.redact(payload)
    assert redacted["trade_id"] == "abc123"
    assert redacted["account_id"] == "<REDACTED>"
    assert redacted["details"]["portfolio_id"] == "<REDACTED>"
    assert redacted["details"]["size"] == 0.01


def test_redacts_long_ids():
    payload = {"order_id": "a-very-long-order-identifier-that-should-be-truncated"}
    redacted = redact.redact(payload)
    assert redacted["order_id"].startswith("...")
    assert len(redacted["order_id"]) < len(payload["order_id"])
