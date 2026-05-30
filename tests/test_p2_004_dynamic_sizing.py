"""P2-004: dynamic equity sizing for Coinbase controlled exploration (review branch)."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pandas as pd
import pytest

import strategy_crypto
from market_data import MarketData
from strategy_crypto import CryptoStrategy


def _base_config(tmp_path, **overrides):
    journal_file = tmp_path / "journal_test.csv"
    with open(journal_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "symbol", "strategy", "decision", "equity"])
        writer.writeheader()

    config = {
        "crypto": {
            "max_trade_notional_usd": 2.00,
            "min_trade_notional_usd": 0.50,
            "buying_power_safety_buffer": 0.85,
            "controlled_exploration": {
                "enabled": True,
                "approved_symbols": ["BTC/USD"],
                "max_single_trade_notional_usd": 1.00,
                "max_total_exploration_exposure_usd": 6.00,
                "daily_stop_loss_usd": 3.00,
                "per_symbol_cooldown_minutes": 0,
                "max_entries_per_symbol_per_day": 99,
            },
            "live_symbols": ["BTC/USD"],
            "dynamic_sizing": {
                "enabled": True,
                "position_size_pct": 2.5,
                "min_notional_usd": 1.00,
                "max_notional_usd": 25.00,
                "scaling_threshold_usd": 20.00,
                "daily_stop_loss_pct": 7.5,
                "max_exposure_pct": 15.0,
            },
        },
        "logging": {"journal_file": str(journal_file.name)},
    }
    def _deep_merge(node: dict, patch: dict) -> None:
        for key, val in patch.items():
            if isinstance(val, dict) and isinstance(node.get(key), dict):
                _deep_merge(node[key], val)
            else:
                node[key] = val

    _deep_merge(config, overrides)
    return config, journal_file


def _install_cfg(monkeypatch, config, tmp_path):
    def mock_get_cfg(*keys, default=None):
        val = config
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val

    monkeypatch.setattr(strategy_crypto, "get_cfg", mock_get_cfg)
    monkeypatch.setattr(strategy_crypto, "load_saved_positions", lambda: {})
    monkeypatch.setattr(strategy_crypto, "ROOT", tmp_path)


def _strategy(tmp_path, monkeypatch, **config_overrides) -> CryptoStrategy:
    config, _ = _base_config(tmp_path, **config_overrides)
    _install_cfg(monkeypatch, config, tmp_path)
    return CryptoStrategy(MagicMock(spec=MarketData))


def _append_journal_equity(journal_path, equity: float) -> None:
    with open(journal_path, "a", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["timestamp", "symbol", "strategy", "decision", "equity"],
        )
        writer.writerow(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "symbol": "BTC/USD",
                "strategy": "coinbase_exploration",
                "decision": "FILLED",
                "equity": str(equity),
            }
        )


def test_resolve_equity_prefers_runtime_over_journal(monkeypatch, tmp_path):
    config, journal = _base_config(tmp_path)
    _install_cfg(monkeypatch, config, tmp_path)
    _append_journal_equity(journal, 99.0)

    s = CryptoStrategy(MagicMock(spec=MarketData))
    s.current_equity = 40.0
    assert s._resolve_equity_for_sizing() == 40.0


def test_resolve_equity_journal_fallback_when_runtime_unset(monkeypatch, tmp_path):
    config, journal = _base_config(tmp_path)
    _install_cfg(monkeypatch, config, tmp_path)
    _append_journal_equity(journal, 41.5)

    s = CryptoStrategy(MagicMock(spec=MarketData))
    assert s._resolve_equity_for_sizing() == 41.5


def test_missing_equity_falls_back_to_legacy_notional(monkeypatch, tmp_path):
    s = _strategy(tmp_path, monkeypatch)
    # max_trade 2.0, hard cap 1.0 -> 1.0
    assert s._resolve_exploration_notional(1000.0) == 1.00


def test_zero_equity_falls_back_to_legacy_notional(monkeypatch, tmp_path):
    s = _strategy(tmp_path, monkeypatch)
    s.current_equity = 0.0
    assert s._resolve_exploration_notional(1000.0) == 1.00


def test_high_equity_cannot_exceed_max_single_trade_cap(monkeypatch, tmp_path):
    s = _strategy(tmp_path, monkeypatch)
    s.current_equity = 10_000.0
    assert s._resolve_exploration_notional(50_000.0) == 1.00


def test_high_equity_cannot_exceed_dynamic_max_notional(monkeypatch, tmp_path):
    crypto = {
        "controlled_exploration": {
            "max_single_trade_notional_usd": 50.00,
        },
        "dynamic_sizing": {"max_notional_usd": 25.00},
    }
    s = _strategy(tmp_path, monkeypatch, crypto=crypto)
    s.current_equity = 10_000.0
    assert s._resolve_exploration_notional(50_000.0) == 25.00


def test_buying_power_safety_buffer_respected(monkeypatch, tmp_path):
    crypto = {
        "controlled_exploration": {"max_single_trade_notional_usd": 50.00},
        "dynamic_sizing": {"max_notional_usd": 50.00},
    }
    s = _strategy(tmp_path, monkeypatch, crypto=crypto)
    s.current_equity = 500.0  # 2.5% -> 12.50 before caps
    # buying_power 2.0 * 0.85 = 1.70
    assert s._resolve_exploration_notional(2.0) == 1.70


def test_daily_stop_loss_capped_by_absolute(monkeypatch, tmp_path):
    s = _strategy(tmp_path, monkeypatch)
    s.current_equity = 1000.0  # 7.5% = 75, cap 3.00
    assert s.get_dynamic_daily_stop_loss() == 3.00


def test_max_exposure_capped_by_absolute(monkeypatch, tmp_path):
    s = _strategy(tmp_path, monkeypatch)
    s.current_equity = 1000.0  # 15% = 150, cap 6.00
    assert s.get_dynamic_max_exposure() == 6.00


def test_exploration_notional_uses_same_resolver_both_scan_paths(monkeypatch, tmp_path):
    """Both exploration entry points call _coinbase_exploration without external equity."""
    s = _strategy(tmp_path, monkeypatch)
    calls: list[float | None] = []

    def track_resolve(bp):
        calls.append(s._resolve_equity_for_sizing())
        return 1.00

    monkeypatch.setattr(s, "_resolve_exploration_notional", track_resolve)

    quote = MagicMock()
    quote.bid = 100.0
    quote.ask = 100.1
    quote.mid = 100.05
    quote.timestamp = datetime.now(timezone.utc)
    df = pd.DataFrame({"c": [100.0] * 100}, index=pd.date_range("2020-01-01", periods=100))

    s.current_equity = 42.0
    s._coinbase_exploration("BTC/USD", quote, df, 1000.0, "dead_chop")
    s._exploration_proposed_this_cycle = False
    s._coinbase_exploration("BTC/USD", quote, df, 1000.0, "dead_chop")

    assert len(calls) == 2
    assert calls[0] == calls[1] == 42.0


def test_sizing_helpers_are_advisory_only_not_imported_by_risk_manager():
    import risk_manager

    assert not hasattr(risk_manager.RiskManager, "get_dynamic_daily_stop_loss")
    assert not hasattr(risk_manager.RiskManager, "get_dynamic_max_exposure")


def test_exploration_proposal_uses_capped_notional(monkeypatch, tmp_path):
    s = _strategy(tmp_path, monkeypatch)
    s.current_equity = 10_000.0

    quote = MagicMock()
    quote.bid = 100.0
    quote.ask = 100.1
    quote.mid = 100.05
    quote.timestamp = datetime.now(timezone.utc)
    df = pd.DataFrame({"c": [100.0] * 100}, index=pd.date_range("2020-01-01", periods=100))

    proposal = s._coinbase_exploration("BTC/USD", quote, df, 1000.0, "dead_chop")
    assert proposal is not None
    assert proposal.notional == 1.00
    assert proposal.strategy == "coinbase_exploration"
