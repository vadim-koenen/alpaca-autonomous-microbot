"""
P2-012A tests for prediction telemetry and derivative features.

All tests are pure and use temp files for telemetry output.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import prediction_telemetry as pt


def test_derivative_features_basic():
    prices = [100 + i * 0.05 for i in range(40)]
    feats = pt.compute_derivative_features(prices, bid=102.0, ask=102.05)

    assert feats["short_slope"] is not None
    assert feats["medium_slope"] is not None
    assert feats["acceleration"] is not None
    assert feats["volatility"] is not None
    assert feats["spread_bps"] is not None and feats["spread_bps"] > 0
    assert feats["range_position"] is not None


def test_derivative_features_insufficient_history():
    feats = pt.compute_derivative_features([100.0, 100.1, 100.2])
    assert feats["short_slope"] is None or isinstance(feats["short_slope"], (int, float))
    # Very short series should not crash
    feats2 = pt.compute_derivative_features([100.0])
    assert feats2["short_slope"] is None


def test_telemetry_writes_stable_schema(tmp_path, monkeypatch):
    out = tmp_path / "pred.jsonl"
    monkeypatch.setattr(pt, "TELEMETRY_FILE", out)
    monkeypatch.setattr(pt, "TELEMETRY_DIR", tmp_path)

    row = pt.log_prediction_telemetry(
        symbol="BTC/USD",
        product_id="BTC-USD",
        product_type="spot_crypto",
        strategy="momentum_breakout",
        regime="trend",
        side="buy",
        confidence=0.78,
        proposed_notional=1.0,
        reference_price=65000.0,
        decision_status="candidate",
        source="strategy_router",
        features=pt.compute_derivative_features([65000 + i for i in range(30)]),
    )

    assert row["schema_version"] == "p2_012a_v1"
    assert row["symbol"] == "BTC/USD"
    assert row["product_type"] == "spot_crypto"

    content = out.read_text()
    assert "p2_012a_v1" in content
    assert "BTC/USD" in content


def test_log_skipped_proposal(tmp_path, monkeypatch):
    out = tmp_path / "pred.jsonl"
    monkeypatch.setattr(pt, "TELEMETRY_FILE", out)
    monkeypatch.setattr(pt, "TELEMETRY_DIR", tmp_path)

    row = pt.log_skipped_proposal(
        {"symbol": "ETH/USD", "strategy": "mean_reversion", "product_type": "spot_crypto"},
        reason="spread_too_wide",
    )
    assert row["decision_status"] == "skipped"
    assert row["reason"] == "spread_too_wide"


def test_no_production_logger_write():
    """The module's executable code must never reference the production fill logger."""
    import re
    source = Path(pt.__file__).read_text()
    # Remove comments and docstrings for the check
    cleaned = re.sub(r'""".*?"""', '', source, flags=re.DOTALL)
    cleaned = re.sub(r"'''.*?'''", '', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'#.*', '', cleaned)
    assert "append_coinbase_fill_row" not in cleaned
    assert "coinbase_fills.csv" not in cleaned
