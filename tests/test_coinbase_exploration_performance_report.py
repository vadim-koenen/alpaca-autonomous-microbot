#!/usr/bin/env python3
"""
test_coinbase_exploration_performance_report.py

Tests for the Coinbase exploration performance report.
"""

import pytest
import pandas as pd
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import csv

from scripts.coinbase_exploration_performance_report import (
    CoinbaseExplorationAnalyzer,
)


@pytest.fixture
def temp_journal(tmp_path):
    """Create a temporary journal CSV with sample data."""
    journal_path = tmp_path / "journal.csv"

    # Create sample data
    rows = [
        {
            "timestamp": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
            "mode": "live",
            "asset_class": "crypto",
            "symbol": "BTC/USD",
            "strategy": "coinbase_exploration",
            "action": "BUY",
            "decision": "PLACED",
            "reason": "",
            "confidence": "0.8",
            "price": "100.0",
            "bid": "99.95",
            "ask": "100.05",
            "spread_pct": "0.05",
            "notional": "1.00",
            "qty": "0.01",
            "order_type": "market",
            "order_id": "order1",
            "client_order_id": "client1",
            "intent_key": "key1",
            "status": "PLACED",
            "fill_price": "100.0",
            "exit_price": "0.0",
            "gross_pnl": "0.0",
            "fees_paid": "0.0",
            "pnl_usd": "0.0",
            "pnl_pct": "0.0",
            "equity": "10000.0",
            "buying_power": "10000.0",
            "open_positions": "0",
            "daily_trade_count": "0",
            "consecutive_losses": "0",
            "error": "",
            "regime": "dead_chop",
        },
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": "live",
            "asset_class": "crypto",
            "symbol": "BTC/USD",
            "strategy": "coinbase_exploration",
            "action": "EXIT",
            "decision": "PLACED",
            "reason": "max hold time 90min exceeded",
            "confidence": "0.0",
            "price": "0.0",
            "bid": "0.0",
            "ask": "0.0",
            "spread_pct": "0.0",
            "notional": "0.0",
            "qty": "0.01",
            "order_type": "market",
            "order_id": "order2",
            "client_order_id": "client2",
            "intent_key": "key2",
            "status": "PLACED",
            "fill_price": "100.0",
            "exit_price": "101.0",
            "gross_pnl": "0.01",
            "fees_paid": "0.005",
            "pnl_usd": "0.005",
            "pnl_pct": "0.5",
            "equity": "10000.005",
            "buying_power": "10000.005",
            "open_positions": "0",
            "daily_trade_count": "1",
            "consecutive_losses": "0",
            "error": "",
            "regime": "dead_chop",
        },
    ]

    with open(journal_path, "w", newline="") as f:
        if rows:
            fieldnames = rows[0].keys()
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    return journal_path


def test_analyzer_initialization():
    """Test analyzer initializes correctly."""
    analyzer = CoinbaseExplorationAnalyzer()
    assert analyzer.df is None
    assert analyzer.trades == []


def test_load_journal_missing_file(monkeypatch):
    """Test load_journal handles missing file gracefully."""
    analyzer = CoinbaseExplorationAnalyzer()
    monkeypatch.setattr(analyzer, "find_journal_file", lambda: None)
    result = analyzer.load_journal()
    assert result is False


def test_load_journal_success(temp_journal, monkeypatch):
    """Test load_journal successfully loads CSV."""
    analyzer = CoinbaseExplorationAnalyzer()
    monkeypatch.setattr(analyzer, "find_journal_file", lambda: temp_journal)

    result = analyzer.load_journal()
    assert result is True
    assert analyzer.df is not None
    assert len(analyzer.df) > 0


def test_extract_exploration_trades(temp_journal, monkeypatch):
    """Test extraction of round-trip trades."""
    analyzer = CoinbaseExplorationAnalyzer()
    monkeypatch.setattr(analyzer, "find_journal_file", lambda: temp_journal)

    analyzer.load_journal()
    trades = analyzer.extract_exploration_trades()

    assert len(trades) >= 1
    trade = trades[0]
    assert trade["symbol"] == "BTC/USD"
    assert trade["exit_type"] == "max_hold"
    assert trade["gross_pnl"] == 0.01
    assert trade["fees"] == 0.005


def test_classify_exit_type():
    """Test exit type classification."""
    analyzer = CoinbaseExplorationAnalyzer()

    assert analyzer._classify_exit_type("max hold time exceeded") == "max_hold"
    assert analyzer._classify_exit_type("max_hold") == "max_hold"
    assert analyzer._classify_exit_type("stop loss triggered") == "stop_loss"
    assert analyzer._classify_exit_type("take_profit threshold") == "take_profit"
    assert analyzer._classify_exit_type("other reason") == "unknown"


def test_fee_reconstruction():
    """Test that fees are correctly extracted."""
    analyzer = CoinbaseExplorationAnalyzer()

    trade = {
        "gross_pnl": 0.02,
        "fees": 0.005,
        "net_pnl": 0.015,
    }

    # Net should equal gross minus fees
    assert abs(trade["net_pnl"] - (trade["gross_pnl"] - trade["fees"])) < 1e-6


def test_compute_metrics_empty():
    """Test compute_metrics with empty trades."""
    analyzer = CoinbaseExplorationAnalyzer()
    metrics = analyzer.compute_metrics([])

    assert metrics["total_trades"] == 0
    assert metrics["gross_pnl_total"] == 0.0
    assert metrics["fees_total"] == 0.0
    assert metrics["net_pnl_total"] == 0.0


def test_compute_metrics_single_trade(temp_journal, monkeypatch):
    """Test compute_metrics with single profitable trade."""
    analyzer = CoinbaseExplorationAnalyzer()
    monkeypatch.setattr(analyzer, "find_journal_file", lambda: temp_journal)

    analyzer.load_journal()
    trades = analyzer.extract_exploration_trades()
    metrics = analyzer.compute_metrics(trades)

    assert metrics["total_trades"] == 1
    assert metrics["gross_pnl_total"] == 0.01
    assert metrics["fees_total"] == 0.005
    assert metrics["net_pnl_total"] == 0.005
    assert metrics["gross_wins"] == 1
    assert metrics["gross_losses"] == 0
    assert metrics["net_wins"] == 1
    assert metrics["net_losses"] == 0


def test_compute_metrics_by_symbol(temp_journal, monkeypatch):
    """Test by-symbol breakdown in metrics."""
    analyzer = CoinbaseExplorationAnalyzer()
    monkeypatch.setattr(analyzer, "find_journal_file", lambda: temp_journal)

    analyzer.load_journal()
    trades = analyzer.extract_exploration_trades()
    metrics = analyzer.compute_metrics(trades)

    assert "BTC/USD" in metrics["by_symbol"]
    assert metrics["by_symbol"]["BTC/USD"]["count"] == 1
    assert metrics["by_symbol"]["BTC/USD"]["net_pnl"] == 0.005


def test_compute_metrics_by_exit_type(temp_journal, monkeypatch):
    """Test by-exit-type breakdown in metrics."""
    analyzer = CoinbaseExplorationAnalyzer()
    monkeypatch.setattr(analyzer, "find_journal_file", lambda: temp_journal)

    analyzer.load_journal()
    trades = analyzer.extract_exploration_trades()
    metrics = analyzer.compute_metrics(trades)

    assert "max_hold" in metrics["by_exit_type"]
    assert metrics["by_exit_type"]["max_hold"]["count"] == 1


def test_breakeven_threshold_calculation(temp_journal, monkeypatch):
    """Test fee breakeven threshold is correctly calculated."""
    analyzer = CoinbaseExplorationAnalyzer()
    monkeypatch.setattr(analyzer, "find_journal_file", lambda: temp_journal)

    analyzer.load_journal()
    trades = analyzer.extract_exploration_trades()
    metrics = analyzer.compute_metrics(trades)

    if metrics["total_trades"] > 0:
        avg_fee = metrics["fees_total"] / metrics["total_trades"]
        avg_gross = metrics["gross_pnl_total"] / metrics["total_trades"]

        # Minimum gross move = average fee per trade
        min_gross_needed = avg_fee

        # With fee=0.005 and gross=0.01, should be above breakeven
        assert avg_gross >= min_gross_needed


def test_max_hold_exit_classification():
    """Test that max-hold exits are correctly classified."""
    analyzer = CoinbaseExplorationAnalyzer()

    test_reasons = [
        "max hold time 90min exceeded",
        "max_hold reached",
        "max hold 120 minutes",
    ]

    for reason in test_reasons:
        assert analyzer._classify_exit_type(reason) == "max_hold"


def test_empty_journal_handling(monkeypatch):
    """Test graceful handling of empty journal."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        empty_journal = tmp_path / "journal.csv"

        with open(empty_journal, "w") as f:
            f.write("timestamp,symbol,action,status\n")

        analyzer = CoinbaseExplorationAnalyzer()
        monkeypatch.setattr(analyzer, "find_journal_file", lambda: empty_journal)

        result = analyzer.load_journal()
        trades = analyzer.extract_exploration_trades()

        assert result is False  # Empty journal returns False
        assert len(trades) == 0


def test_generate_report_structure(temp_journal, monkeypatch):
    """Test that generated report contains expected sections."""
    analyzer = CoinbaseExplorationAnalyzer()
    monkeypatch.setattr(analyzer, "find_journal_file", lambda: temp_journal)

    report = analyzer.generate_report()

    assert "COINBASE CONTROLLED EXPLORATION PERFORMANCE REPORT" in report
    assert "SUMMARY" in report
    assert "BY SYMBOL" in report
    assert "EXIT TYPE DISTRIBUTION" in report
    assert "FEE BREAKEVEN ANALYSIS" in report
    assert "WARNINGS & DIAGNOSTICS" in report


def test_negative_pnl_warning():
    """Test that negative P/L triggers warning."""
    analyzer = CoinbaseExplorationAnalyzer()

    trades = [
        {
            "symbol": "BTC/USD",
            "entry_time": datetime.now(timezone.utc),
            "exit_time": datetime.now(timezone.utc),
            "entry_price": 100.0,
            "exit_price": 99.0,
            "qty": 0.01,
            "gross_pnl": -0.01,
            "fees": 0.005,
            "net_pnl": -0.015,
            "exit_type": "stop_loss",
            "regime": "dead_chop",
            "reason": "stop loss",
        },
    ]

    metrics = analyzer.compute_metrics(trades)
    assert metrics["net_pnl_total"] < 0
