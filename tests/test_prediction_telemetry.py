"""
P2-012A tests for prediction telemetry and derivative features.

All tests are pure (no network, no real writes to production files).
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import prediction_telemetry as pt


def test_derivative_features_basic():
    prices = [100 + i * 0.1 for i in range(30)]
    feats = pt.compute_derivative_features(prices, bid=100.05, ask=100.15, current_price=prices[-1])

    assert "short_slope" in feats
    assert "medium_slope" in feats
    assert "acceleration" in feats
    assert "volatility" in feats
    assert "spread_bps" in feats
    assert "range_position" in feats

    assert feats["spread_bps"] is not None and feats["spread_bps"] > 0
    assert feats["range_position"] is not None


def test_derivative_features_insufficient_data():
    feats = pt.compute_derivative_features([100.0, 100.1])
    assert feats["short_slope"] is None
    assert feats["medium_slope"] is None


def test_log_prediction_writes_with_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(pt, "TELEMETRY_FILE", tmp_path / "pred.jsonl")
    monkeypatch.setattr(pt, "TELEMETRY_DIR", tmp_path)

    row = pt.log_prediction_telemetry(
        symbol="BTC/USD",
        strategy="momentum_breakout",
        regime="trend",
        side="buy",
        confidence=0.82,
        proposed_notional=1.0,
        entry_price=65000.0,
        decision_status="candidate",
        source="strategy_router",
        features={"short_slope": 0.00012},
    )

    assert row["schema_version"] == "p2_012a_v1"
    assert row["symbol"] == "BTC/USD"
    assert row["decision_status"] == "candidate"

    # File should exist and contain the row
    content = (tmp_path / "pred.jsonl").read_text()
    assert "p2_012a_v1" in content
    assert "BTC/USD" in content


def test_log_skipped_proposal():
    row = pt.log_skipped_proposal(
        type("P", (), {"symbol": "ETH/USD", "strategy": "mean_reversion"})(),
        reason="spread_too_wide",
        regime="chop",
    )
    assert row["decision_status"] == "skipped"
    assert row["skip_reason"] == "spread_too_wide"


def test_telemetry_handles_missing_fields_gracefully():
    # Should not crash even with almost empty proposal-like object
    row = pt.log_proposal_candidate(
        type("P", (), {"symbol": "SOL/USD"})(),
        source="test",
    )
    assert row["symbol"] == "SOL/USD"
    assert row["schema_version"] == "p2_012a_v1"
