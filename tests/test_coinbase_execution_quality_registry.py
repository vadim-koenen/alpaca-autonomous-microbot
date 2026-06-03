# ADVISORY ONLY - offline tests for P2-025A Coinbase execution-quality registry.
# No broker calls, no .env reads, no order activity, no runtime/process mutations.

import importlib.util
import json
import sys
from pathlib import Path

from coinbase_execution_quality_registry import (
    build_execution_quality_report,
    evaluate_symbol_execution_quality,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "coinbase_execution_quality" / "expanded_basket_execution_quality_sample.json"
SCRIPT = ROOT / "scripts" / "coinbase_execution_quality_report.py"

spec = importlib.util.spec_from_file_location("coinbase_execution_quality_report_p2_025a", SCRIPT)
script_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = script_module
spec.loader.exec_module(script_module)


def _payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _report():
    return build_execution_quality_report(_payload())


def _by_symbol(report, symbol):
    rows = report["ranked_symbols"] + report["out_of_scope_symbols"]
    return next(row for row in rows if row["symbol"] == symbol)


def test_tight_spread_maker_maker_passes():
    report = _report()
    btc = _by_symbol(report, "BTC/USD")

    assert btc["verdict"] == "pass"
    assert btc["assumed_entry_liquidity_type"] == "maker"
    assert btc["assumed_exit_liquidity_type"] == "maker"
    assert btc["round_trip_fee_rate"] == "0.012000"
    assert btc["required_break_even_move_rate"] == "0.013200"
    assert btc["preview_pnl"]["advisory_only"] is True
    assert btc["preview_pnl"]["usable_for_final_profitability"] is False


def test_taker_taker_can_fail_even_when_spread_is_acceptable():
    ada = _by_symbol(_report(), "ADA/USD")

    assert ada["spread_pct"] == "0.0666"
    assert ada["assumed_entry_liquidity_type"] == "taker"
    assert ada["assumed_exit_liquidity_type"] == "taker"
    assert ada["round_trip_fee_rate"] == "0.024000"
    assert "spread_too_wide" not in ada["reasons"]
    assert "expected_gross_move_below_required_break_even" in ada["reasons"]
    assert ada["verdict"] == "fail"


def test_wide_spread_fails():
    avax = _by_symbol(_report(), "AVAX/USD")

    assert avax["verdict"] == "fail"
    assert "spread_too_wide" in avax["reasons"]


def test_insufficient_expected_gross_move_fails():
    doge = _by_symbol(_report(), "DOGE/USD")

    assert doge["verdict"] == "fail"
    assert "expected_gross_move_below_required_break_even" in doge["reasons"]


def test_missing_expected_move_is_observe_only_not_pass():
    link = _by_symbol(_report(), "LINK/USD")

    assert link["verdict"] == "observe_only"
    assert "expected_gross_move_rate_missing" in link["reasons"]


def test_preview_pnl_cannot_override_fee_spread_slippage_model():
    ada = _by_symbol(_report(), "ADA/USD")

    assert ada["preview_pnl"]["provided"] is True
    assert ada["preview_pnl"]["reason"] == "coinbase_preview_pnl_excludes_fees_and_slippage"
    assert "preview_pnl_advisory_only" in ada["reasons"]
    assert ada["verdict"] == "fail"


def test_sol_and_out_of_scope_products_are_excluded():
    report = _report()
    sol = _by_symbol(report, "SOL/USD")
    perp = next(row for row in report["out_of_scope_symbols"] if row["product_id"] == "BTC-PERP")

    assert sol["verdict"] == "fail"
    assert "symbol_excluded_external_inventory" in sol["reasons"]
    assert perp["verdict"] == "fail"
    assert "product_out_of_scope" in perp["reasons"]
    assert all(row["symbol"] != "SOL/USD" for row in report["ranked_symbols"])
    assert report["summary"]["sol_excluded"] is True


def test_ranking_is_deterministic_for_controlled_live_basket():
    report = _report()
    symbols = [row["symbol"] for row in report["ranked_symbols"]]

    assert symbols == ["BTC/USD", "ETH/USD", "LTC/USD", "LINK/USD", "AVAX/USD", "ADA/USD", "DOGE/USD"]
    assert [row["rank"] for row in report["ranked_symbols"]] == list(range(1, 8))
    assert report["summary"]["best_symbol"] == "BTC/USD"


def test_report_script_default_fixture_outputs_read_only_registry():
    report = script_module.build_report()

    assert report["mode"] == "offline_fixture_backed_read_only"
    assert report["trade_permission"] == "none"
    assert report["preview_pnl_policy"]["usable_for_final_profitability"] is False
    assert report["safety"]["broker_calls_made"] is False
    assert report["safety"]["orders_cancels_closes_modifications"] is False
    assert report["summary"]["profit_readout"] == "unsafe_to_aggregate"


def test_single_symbol_evaluator_handles_invalid_quote():
    row = {
        "symbol": "BTC/USD",
        "product_id": "BTC-USD",
        "bid": "0",
        "ask": "100.00",
        "expected_gross_move_rate": "0.0500",
    }
    result = evaluate_symbol_execution_quality(row)

    assert result["verdict"] == "fail"
    assert "invalid_or_stale_quote" in result["reasons"]


def test_new_script_and_registry_have_no_forbidden_runtime_hooks():
    combined = "\n".join([
        (ROOT / "coinbase_execution_quality_registry.py").read_text(encoding="utf-8"),
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
        "place_market_order(",
        "submit_order(",
        "cancel_order(",
        "close_position(",
        "modify_order(",
        "launchctl",
        "append_coinbase_fill_row(",
        "logs/coinbase_fills.csv",
    ]
    for token in forbidden:
        assert token not in combined
