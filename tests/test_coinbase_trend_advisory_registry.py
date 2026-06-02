# ADVISORY ONLY - offline tests for P2-024A Coinbase trend advisory registry.
# No broker calls, no .env reads, no order activity, no strategy/risk overrides.

import importlib.util
import sys
from pathlib import Path

from scripts.coinbase_trend_signal_registry import (
    ELIGIBLE_SYMBOLS,
    EXCLUDED_SYMBOLS,
    SCHEMA_VERSION,
    build_advisory_snapshot,
    source_definitions,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "trend_advisory"
SNAPSHOT_SCRIPT = ROOT / "scripts" / "coinbase_trend_advisory_snapshot.py"
REGISTRY_SCRIPT = ROOT / "scripts" / "coinbase_trend_signal_registry.py"

spec = importlib.util.spec_from_file_location("coinbase_trend_advisory_snapshot", SNAPSHOT_SCRIPT)
snapshot_cli = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = snapshot_cli
spec.loader.exec_module(snapshot_cli)


def _sample_snapshot(symbols=("BTC/USD", "ETH/USD", "SOL/USD")):
    return build_advisory_snapshot(
        symbols=symbols,
        source_json=FIXTURES / "coinbase_local_market_context_sample.json",
    )


def test_schema_output_is_valid_and_advisory_only():
    snapshot = _sample_snapshot()

    assert snapshot["schema_version"] == SCHEMA_VERSION
    assert snapshot["mode"] == "read_only_advisory"
    assert snapshot["trade_permission"] == "none"
    assert snapshot["risk_increase"] == "not_approved"
    assert snapshot["safety"]["advisory_only"] is True
    assert snapshot["safety"]["order_actions_allowed"] is False
    assert snapshot["safety"]["sizing_changes_allowed"] is False
    assert snapshot["safety"]["risk_override_allowed"] is False


def test_btc_eth_only_and_sol_excluded_from_symbols():
    snapshot = _sample_snapshot()

    symbols = [row["symbol"] for row in snapshot["symbols"]]
    assert symbols == ["BTC/USD", "ETH/USD"]
    assert set(symbols) == set(ELIGIBLE_SYMBOLS)
    assert "SOL/USD" in EXCLUDED_SYMBOLS
    assert "SOL/USD" not in symbols
    assert any("SOL remains excluded" in item["message"] for item in snapshot["global_narratives"])


def test_downtrend_local_context_returns_avoid_or_watch_not_buy():
    snapshot = _sample_snapshot(symbols=("BTC/USD", "ETH/USD"))

    for row in snapshot["symbols"]:
        assert row["trend_bias"] == "bearish"
        assert row["advisory_action"] in {"avoid", "watch"}
        assert row["eligible_for_live_trade_trigger"] is False
        assert "local_regime=downtrend" in row["reasons"]
        assert "allowed_strategies_empty" in row["reasons"]


def test_positive_external_trend_does_not_create_live_trade_permission():
    snapshot = _sample_snapshot(symbols=("BTC/USD", "ETH/USD"))

    for row in snapshot["symbols"]:
        assert row["advisory_action"] == "avoid"
        assert row["eligible_for_live_trade_trigger"] is False
        assert "external_positive_does_not_override_local_downtrend" in row["reasons"]
    assert snapshot["trade_permission"] == "none"


def test_external_only_positive_trend_can_only_be_confirm_only():
    snapshot = build_advisory_snapshot(
        symbols=("BTC/USD", "ETH/USD", "SOL/USD"),
        source_json=FIXTURES / "coingecko_trending_sample.json",
    )

    symbols = {row["symbol"]: row for row in snapshot["symbols"]}
    assert symbols["BTC/USD"]["advisory_action"] == "confirm_only"
    assert symbols["ETH/USD"]["advisory_action"] == "confirm_only"
    assert symbols["BTC/USD"]["eligible_for_live_trade_trigger"] is False
    assert snapshot["trade_permission"] == "none"
    assert "SOL/USD" not in symbols


def test_unavailable_source_does_not_crash():
    snapshot = build_advisory_snapshot(symbols=("BTC/USD", "ETH/USD"))

    assert snapshot["source_status"]["coinbase_local_market_context"] == "unavailable"
    assert snapshot["source_status"]["coingecko_trending"] == "unavailable"
    assert snapshot["source_status"]["coindesk_rss_news"] == "unavailable"
    assert len(snapshot["symbols"]) == 2
    assert all(row["advisory_action"] == "unknown" for row in snapshot["symbols"])


def test_source_registry_has_expected_read_only_sources():
    sources = {row["source_id"]: row for row in source_definitions()}

    assert sources["coinbase_local_market_context"]["enabled_by_default"] is True
    assert sources["coingecko_trending"]["enabled_by_default"] is False
    assert sources["coindesk_rss_news"]["enabled_by_default"] is False
    assert all(row["network_default"] is False for row in sources.values())
    assert all(row["requires_api_key"] is False for row in sources.values())


def test_snapshot_cli_builds_without_network_or_side_effects(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("COINBASE_API_KEY=NEVER\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    before = {p.name for p in tmp_path.iterdir()}

    snapshot = build_advisory_snapshot(
        symbols=("BTC/USD", "ETH/USD"),
        source_json=FIXTURES / "coindesk_rss_sample.json",
    )
    after = {p.name for p in tmp_path.iterdir()}

    assert snapshot["safety"]["broker_calls_made"] is False
    assert snapshot["safety"]["live_read_only_used"] is False
    assert snapshot["safety"]["secrets_or_env_read"] is False
    assert snapshot["safety"]["network_used"] is False
    assert after == before


def test_scripts_have_no_forbidden_runtime_hooks():
    combined = "\n".join([
        REGISTRY_SCRIPT.read_text(encoding="utf-8"),
        SNAPSHOT_SCRIPT.read_text(encoding="utf-8"),
    ])
    forbidden = [
        "broker_coinbase",
        "CoinbaseBroker",
        "load_dotenv",
        "dotenv",
        "os.environ",
        "append_coinbase_fill_row(",
        "logs/coinbase_fills.csv",
        "place_order(",
        "place_market_order(",
        "submit_order(",
        "preview_order(",
        "cancel_order(",
        "close_position(",
        "modify_order(",
        "strategy_crypto",
        "risk_manager",
        "order_manager",
        "prediction_market",
        "perpetual",
        "perps",
    ]
    for token in forbidden:
        assert token not in combined
