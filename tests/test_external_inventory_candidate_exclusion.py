"""
P2-021C5 tests for external/staked Coinbase inventory candidate exclusion.

No broker APIs, no .env reads, no order activity, and no state/log mutation.
"""

from __future__ import annotations

import inspect
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ALPACA_API_KEY", "test_key_placeholder")
os.environ.setdefault("ALPACA_SECRET_KEY", "test_secret_placeholder")
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("ALPACA_PAPER", "true")

from permissions import AccountPermissions
from risk_manager import AccountState, RiskManager, TradeProposal
from strategy_crypto import CryptoStrategy
from strategy_router import StrategyRouter
from utils import (
    is_external_inventory_excluded_symbol,
    load_external_inventory_excluded_symbols,
)


def _write_external_inventory(root: Path, records: dict) -> None:
    path = root / "state" / "coinbase" / "external_inventory.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"external_inventory": records}), encoding="utf-8")


def _authoritative_sol_record(**overrides) -> dict:
    record = {
        "symbol": "SOL/USD",
        "staked_external_position": True,
        "external_inventory_classification": "external_staked_position",
        "tradable_by_bot": False,
        "manual_close_allowed": False,
        "bot_inventory": False,
        "blocks_new_entries": False,
    }
    record.update(overrides)
    return record


def _fake_get_cfg(config: dict):
    def get_cfg(*keys, default=None):
        value = config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    return get_cfg


def _permissions() -> AccountPermissions:
    return AccountPermissions(
        equity=45.0,
        buying_power=45.0,
        crypto_enabled=True,
        options_enabled=False,
        margin_enabled=False,
        short_selling_enabled=False,
        account_blocked=False,
        trading_blocked=False,
        account_status="ACTIVE",
    )


def _proposal(symbol: str = "BTC/USD") -> TradeProposal:
    return TradeProposal(
        symbol=symbol,
        asset_class="crypto",
        strategy="coinbase_probe",
        side="buy",
        order_type="limit",
        notional=1.0,
        limit_price=100.0,
        confidence=0.7,
        bid=99.99,
        ask=100.01,
        price=100.0,
        quote_time=datetime.now(timezone.utc),
        stop_loss_price=98.0,
        take_profit_price=103.0,
        meta={"net_expected_edge_pct": 1.0, "worst_case_edge_pct": 0.5, "reward_risk_ratio": 1.5, "profit_thesis": {"status": "APPROVED"}},
    )


def test_authoritative_external_staked_sol_is_excluded(tmp_path):
    _write_external_inventory(tmp_path, {"SOL/USD": _authoritative_sol_record()})

    excluded = load_external_inventory_excluded_symbols(tmp_path)

    assert excluded == {"SOL/USD"}
    assert is_external_inventory_excluded_symbol("SOL-USD", excluded_symbols=excluded) is True


def test_missing_external_inventory_does_not_exclude_symbols(tmp_path):
    assert load_external_inventory_excluded_symbols(tmp_path) == set()
    assert is_external_inventory_excluded_symbol("SOL/USD", root=tmp_path) is False


def test_malformed_external_inventory_fails_closed_without_crash(tmp_path):
    path = tmp_path / "state" / "coinbase" / "external_inventory.json"
    path.parent.mkdir(parents=True)
    path.write_text("{bad", encoding="utf-8")

    assert load_external_inventory_excluded_symbols(tmp_path) == set()
    assert is_external_inventory_excluded_symbol("SOL/USD", root=tmp_path) is False


def test_non_authoritative_or_bot_owned_records_do_not_exclude(tmp_path):
    _write_external_inventory(
        tmp_path,
        {
            "SOL/USD": _authoritative_sol_record(bot_inventory=True),
            "BTC/USD": {
                "symbol": "BTC/USD",
                "external_inventory_classification": "broker_recovered_position",
                "bot_inventory": True,
                "tradable_by_bot": True,
                "manual_close_allowed": True,
            },
        },
    )

    assert load_external_inventory_excluded_symbols(tmp_path) == set()


def test_strategy_router_excludes_sol_but_keeps_btc_eth(monkeypatch):
    import strategy_router

    config = {
        "crypto": {
            "enabled": True,
            "live_symbols": ["BTC/USD", "ETH/USD", "SOL/USD"],
            "watch_only_symbols": [],
            "multi_asset_spot": {"enabled": False},
        },
        "equities": {"enabled": False, "symbols": []},
        "options": {"enabled": False},
        "short_selling": {"enabled": False},
    }
    monkeypatch.setattr(strategy_router, "get_cfg", _fake_get_cfg(config))
    monkeypatch.setattr(strategy_router, "load_external_inventory_excluded_symbols", lambda: {"SOL/USD"})

    router = StrategyRouter(MagicMock(), MagicMock())
    called: list[str] = []
    router._crypto.generate_proposals = lambda symbol, buying_power=None: called.append(symbol) or []

    router.scan(_permissions(), buying_power=45.0)

    assert called == ["BTC/USD", "ETH/USD"]


def test_strategy_router_keeps_sol_when_external_inventory_missing(monkeypatch):
    import strategy_router

    config = {
        "crypto": {
            "enabled": True,
            "live_symbols": ["BTC/USD", "ETH/USD", "SOL/USD"],
            "watch_only_symbols": [],
            "multi_asset_spot": {"enabled": False},
        },
        "equities": {"enabled": False, "symbols": []},
        "options": {"enabled": False},
        "short_selling": {"enabled": False},
    }
    monkeypatch.setattr(strategy_router, "get_cfg", _fake_get_cfg(config))
    monkeypatch.setattr(strategy_router, "load_external_inventory_excluded_symbols", lambda: set())

    router = StrategyRouter(MagicMock(), MagicMock())
    called: list[str] = []
    router._crypto.generate_proposals = lambda symbol, buying_power=None: called.append(symbol) or []

    router.scan(_permissions(), buying_power=45.0)

    assert called == ["BTC/USD", "ETH/USD", "SOL/USD"]


def test_exploration_selector_excludes_external_sol(monkeypatch, tmp_path):
    import strategy_crypto

    monkeypatch.setattr(strategy_crypto, "load_external_inventory_excluded_symbols", lambda: {"SOL/USD"})
    monkeypatch.setattr(strategy_crypto, "load_saved_positions", lambda: {})
    monkeypatch.setattr(strategy_crypto, "ROOT", tmp_path)
    monkeypatch.setattr(
        strategy_crypto,
        "get_cfg",
        _fake_get_cfg({
            "crypto": {
                "controlled_exploration": {
                    "per_symbol_cooldown_minutes": 0,
                    "max_entries_per_symbol_per_day": 4,
                }
            },
            "logging": {"journal_file": str(tmp_path / "journal_coinbase_crypto.csv")},
        }),
    )
    (tmp_path / "journal_coinbase_crypto.csv").write_text(
        "timestamp,symbol,strategy,decision\n",
        encoding="utf-8",
    )

    selected = CryptoStrategy(MagicMock())._select_exploration_symbol(["SOL/USD", "BTC/USD", "ETH/USD"])

    assert selected == "BTC/USD"


def test_active_open_position_still_blocks_normally(monkeypatch):
    import risk_manager

    monkeypatch.setattr(risk_manager, "get_mode", lambda: "paper")

    allowed, reason = RiskManager().check(
        _proposal("BTC/USD"),
        AccountState(
            equity=45.0,
            buying_power=45.0,
            open_positions=1,
            open_position_symbols=["BTC/USD"],
            open_orders=0,
            open_order_symbols=[],
            daily_realized_pnl=0.0,
            daily_trade_count=0,
            consecutive_losses=0,
            crypto_enabled=True,
            options_enabled=False,
            options_level=0,
            margin_enabled=False,
            short_selling_enabled=False,
            account_blocked=False,
            trading_blocked=False,
            api_error_count=0,
        ),
    )

    assert allowed is False
    assert reason == "already have open position in BTC/USD"


def test_candidate_exclusion_sources_have_no_forbidden_runtime_calls():
    import strategy_router
    import utils

    sources = "\n".join([
        inspect.getsource(strategy_router.StrategyRouter.scan),
        inspect.getsource(utils.load_external_inventory_excluded_symbols),
        inspect.getsource(utils.is_external_inventory_excluded_symbol),
    ])
    forbidden = (
        "broker_coinbase",
        "load_env(",
        "load_dotenv",
        ".env",
        "place_order",
        "cancel_order",
        "close_position",
        "modify_order",
        "submit_order",
        "append_coinbase_fill_row",
        "logs/coinbase_fills.csv",
        "--live-read-only",
    )

    for token in forbidden:
        assert token not in sources
