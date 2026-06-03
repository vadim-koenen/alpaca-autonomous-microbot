# ADVISORY ONLY - offline tests for P2-025B Coinbase market context registry.
# No broker calls, no secrets, no order activity, no runtime/process mutation.

import importlib.util
import json
import sys
from pathlib import Path

from coinbase_market_context_registry import (
    ALLOWED_ADVISORY_LABELS,
    FORBIDDEN_EXTERNAL_OUTPUTS,
    build_market_context_report,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "coinbase_market_context" / "market_context_sources_sample.json"
SCRIPT = ROOT / "scripts" / "coinbase_market_context_report.py"

spec = importlib.util.spec_from_file_location("coinbase_market_context_report_p2_025b", SCRIPT)
script_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = script_module
spec.loader.exec_module(script_module)


def _payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _report():
    return build_market_context_report(_payload())


def _source(report, source_name):
    return next(row for row in report["source_registry"] if row["source_name"] == source_name)


def _symbol(report, symbol):
    return next(row for row in report["symbol_context"] if row["symbol"] == symbol)


def test_registry_loads_fixture_default_sources():
    report = _report()

    assert report["schema_version"] == "p2-025b.coinbase_market_context_registry.v1"
    assert report["mode"] == "offline_fixture_backed_read_only_market_context"
    assert report["summary"]["source_count"] == 8
    assert report["summary"]["symbol_context_count"] == 7
    assert [row["source_name"] for row in report["source_registry"]] == [
        "coinbase_market_data",
        "coinbase_product_metadata",
        "coinbase_level2_order_book_future",
        "coinbase_order_preview_future",
        "coingecko_trending",
        "coingecko_markets",
        "crypto_news_sentiment_future",
        "all_asset_opportunity_registry_future",
    ]


def test_all_sources_and_symbols_have_no_trading_authority():
    report = _report()

    assert report["trading_authority"] == "none"
    assert report["trade_permission"] == "none"
    assert all(row["trading_authority"] == "none" for row in report["source_registry"])
    assert all(row["trading_authority"] == "none" for row in report["symbol_context"])
    assert report["summary"]["all_sources_trading_authority_none"] is True
    assert report["summary"]["all_symbol_context_trading_authority_none"] is True


def test_external_context_cannot_emit_trade_actions():
    report = _report()
    forbidden = set(FORBIDDEN_EXTERNAL_OUTPUTS)

    for row in report["symbol_context"]:
        assert row["advisory_label"] in ALLOWED_ADVISORY_LABELS
        assert row["advisory_label"] not in forbidden
        assert row["can_trigger_trade"] is False
        assert row["can_change_sizing"] is False
        assert row["can_override_risk"] is False
        assert row["can_override_strategy"] is False
        assert row["can_override_execution_quality"] is False
    assert report["advisory_policy"]["external_context_can_trigger_trades"] is False


def test_coingecko_sources_are_advisory_only():
    report = _report()
    trending = _source(report, "coingecko_trending")
    markets = _source(report, "coingecko_markets")

    assert trending["allowed_use"] == "advisory_only"
    assert markets["allowed_use"] == "advisory_only"
    assert trending["trading_authority"] == "none"
    assert "trade" in trending["forbidden_use"]


def test_coinbase_market_data_can_feed_execution_quality_but_not_orders():
    report = _report()
    market_data = _source(report, "coinbase_market_data")

    assert market_data["allowed_use"] == "execution_quality_input"
    assert market_data["category"] == "execution_venue"
    assert market_data["trading_authority"] == "none"
    assert "order" in market_data["forbidden_use"]


def test_coinbase_order_preview_is_future_disabled_not_profit_or_trade_authority():
    report = _report()
    preview = _source(report, "coinbase_order_preview_future")

    assert preview["status"] == "disabled"
    assert preview["allowed_use"] == "future_research"
    assert preview["requires_auth"] is True
    assert preview["trading_authority"] == "none"


def test_sol_remains_excluded_external_non_tradable():
    report = _report()
    sol = report["excluded_symbols"][0]

    assert sol["symbol"] == "SOL/USD"
    assert sol["external_inventory_classification"] == "external_staked_position"
    assert sol["bot_inventory"] is False
    assert sol["tradable_by_bot"] is False
    assert sol["manual_close_allowed"] is False
    assert report["summary"]["sol_excluded_non_tradable"] is True


def test_out_of_scope_markets_remain_disabled_or_future_research_only():
    report = _report()
    markets = {row["market"]: row for row in report["out_of_scope_markets"]}

    for key in ["perps", "derivatives", "prediction_markets", "stocks", "etfs"]:
        assert key in markets
        assert markets[key]["trading_authority"] == "none"
        assert markets[key]["allowed_use"] == "future_research"
        assert markets[key]["status"] in {"disabled", "future_research_only"}


def test_missing_source_data_degrades_to_insufficient_data():
    report = build_market_context_report({})

    assert len(report["symbol_context"]) == 7
    assert all(row["advisory_label"] == "insufficient_data" for row in report["symbol_context"])
    assert all("source_data_missing" in row["reasons"] for row in report["symbol_context"])
    assert report["summary"]["trend_news_context_can_trigger_trades"] is False


def test_output_is_deterministic():
    first = _report()
    second = _report()

    assert [row["source_name"] for row in first["source_registry"]] == [row["source_name"] for row in second["source_registry"]]
    assert [row["symbol"] for row in first["symbol_context"]] == [row["symbol"] for row in second["symbol_context"]]
    assert [row["advisory_label"] for row in first["symbol_context"]] == [
        "confirm_only",
        "confirm_only",
        "trend_attention",
        "watch",
        "avoid",
        "insufficient_data",
        "confirm_only",
    ]


def test_report_script_emits_valid_json_shape():
    report = script_module.build_report()

    assert report["trade_permission"] == "none"
    assert report["trading_authority"] == "none"
    assert report["summary"]["source_count"] == 8
    assert report["summary"]["sol_excluded_non_tradable"] is True
    assert report["safety"]["broker_calls_made"] is False


def test_new_runtime_files_have_no_forbidden_hooks():
    combined = "\n".join([
        (ROOT / "coinbase_market_context_registry.py").read_text(encoding="utf-8"),
        SCRIPT.read_text(encoding="utf-8"),
    ])
    forbidden = [
        "broker_coinbase",
        "CoinbaseBroker",
        "load_dotenv",
        "dotenv",
        "os.environ",
        "--live-read-only",
        "create_order(",
        "place_order(",
        "cancel_order(",
        "close_position(",
        "modify_order(",
        "launchctl",
        "append_coinbase_fill_row(",
        "logs/coinbase_fills.csv",
    ]
    for token in forbidden:
        assert token not in combined
