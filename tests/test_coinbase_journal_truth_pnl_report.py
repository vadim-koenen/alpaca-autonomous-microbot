import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "coinbase_journal_truth_pnl_report.py"
CONFIG = ROOT / "config_coinbase_crypto.yaml"

spec = importlib.util.spec_from_file_location("coinbase_journal_truth_pnl_report_p2_025c", SCRIPT)
script_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = script_module
spec.loader.exec_module(script_module)


HEADER = (
    "timestamp,mode,asset_class,symbol,strategy,action,decision,reason,confidence,"
    "price,bid,ask,spread_pct,notional,qty,order_type,order_id,client_order_id,"
    "intent_key,status,fill_price,exit_price,gross_pnl,fees_paid,pnl_usd,pnl_pct,"
    "equity,buying_power,open_positions,daily_trade_count,consecutive_losses,error"
)


def _fixture_journal(tmp_path):
    rows = [
        HEADER,
        "2026-06-01T00:00:00Z,live,crypto,BTC/USD,coinbase_probe,EXIT,PLACED,"
        "max hold time 90min exceeded (90.4min held),0,0,0,0,0,0,0,limit,"
        "oid1,cid1,key1,filled,100,99,-0.010,0.006,-0.016,-1,0,0,0,0,0,",
        "2026-06-01T01:00:00Z,live,crypto,ETH/USD,coinbase_exploration,EXIT,PLACED,"
        "take-profit hit @ 101,0,0,0,0,0,0,0,limit,oid2,cid2,key2,filled,"
        "100,101,0.100,0.020,0.080,8,0,0,0,0,0,",
        "2026-06-01T02:00:00Z,live,crypto,ETH/USD,coinbase_exploration,EXIT,PLACED,"
        "stop-loss hit @ 99,0,0,0,0,0,0,0,limit,oid3,cid3,key3,filled,"
        "100,99,-0.020,0.010,-0.030,-3,0,0,0,0,0,",
        "2026-06-01T03:00:00Z,live,crypto,LTC/USD,mean_reversion,EXIT,PLACED,"
        "max hold time 90min exceeded (91.0min held),0,0,0,0,0,0,0,limit,"
        "oid4,cid4,key4,filled,100,100,0.006,0.006,0.000,0,0,0,0,0,0,",
        "2026-06-01T04:00:00Z,live,crypto,BTC/USD,coinbase_probe,BUY,PLACED,,"
        "0,0,0,0,0,0,0,limit,oid5,cid5,key5,pending,0,0,0,0,0,0,0,0,0,0,0,",
        "2026-06-01T05:00:00Z,dry_run,crypto,BTC/USD,coinbase_probe,EXIT,PLACED,"
        "max hold time 90min exceeded,0,0,0,0,0,0,0,limit,oid6,cid6,key6,filled,"
        "100,99,-1,0,-1,-1,0,0,0,0,0,",
        "2026-06-01T06:00:00Z,live,,BTC/USD,,WARN,WARN,,0,0,0,0,0,0,0,,,,,,0,0,0,0,0,0,0,0,0,0,0,warning only",
        "",
        "short,row",
    ]
    path = tmp_path / "journal_coinbase_crypto.csv"
    path.write_text("\n".join(rows), encoding="utf-8")
    return path


def test_fixture_live_exit_rows_calculate_exact_summary(tmp_path):
    report = script_module.build_journal_truth_report(_fixture_journal(tmp_path))
    summary = report["summary"]

    assert summary["total_closed_cycles"] == 4
    assert summary["winning_cycles"] == 1
    assert summary["losing_cycles"] == 2
    assert summary["breakeven_cycles"] == 1
    assert summary["win_rate"] == pytest.approx(0.25)
    assert summary["gross_pnl_sum"] == pytest.approx(0.076)
    assert summary["fees_sum"] == pytest.approx(0.042)
    assert summary["net_pnl_sum"] == pytest.approx(0.034)
    assert report["date_range"]["start"] == "2026-06-01T00:00:00Z"
    assert report["date_range"]["end"] == "2026-06-01T03:00:00Z"


def test_breakdowns_by_strategy_symbol_and_exit_reason(tmp_path):
    report = script_module.build_journal_truth_report(_fixture_journal(tmp_path))

    assert report["by_strategy"]["coinbase_probe"]["net_pnl_sum"] == pytest.approx(-0.016)
    assert report["by_strategy"]["coinbase_exploration"]["net_pnl_sum"] == pytest.approx(0.05)
    assert report["by_strategy"]["mean_reversion"]["breakeven_cycles"] == 1

    assert report["by_symbol"]["BTC/USD"]["total_closed_cycles"] == 1
    assert report["by_symbol"]["ETH/USD"]["net_pnl_sum"] == pytest.approx(0.05)
    assert report["by_symbol"]["LTC/USD"]["net_pnl_sum"] == pytest.approx(0.0)

    assert report["by_exit_reason"]["max hold time 90min exceeded"]["total_closed_cycles"] == 2
    assert report["by_exit_reason"]["take-profit hit"]["winning_cycles"] == 1
    assert report["by_exit_reason"]["stop-loss hit"]["losing_cycles"] == 1
    assert report["dominant_exit_reason"] == "max hold time 90min exceeded"


def test_malformed_blank_warn_and_non_exit_rows_are_skipped(tmp_path):
    report = script_module.build_journal_truth_report(_fixture_journal(tmp_path))
    skipped = report["skipped_rows"]

    assert skipped["non_exit"] == 1
    assert skipped["non_live"] == 1
    assert skipped["warn_or_error"] == 1
    assert skipped["malformed_or_short"] == 1
    assert report["summary"]["total_closed_cycles"] == 4


def test_output_preserves_non_trading_permissions_and_no_forbidden_fields(tmp_path):
    report = script_module.build_journal_truth_report(_fixture_journal(tmp_path))

    assert report["readout_class"] == "journal_recorded_broker_backed"
    assert report["numeric_safe_direct_capture_available"] is False
    assert report["trade_permission"] == "none"
    assert report["risk_increase"] == "not_approved"
    assert report["scaling_allowed"] is False
    assert report["aggregation_allowed"] is False

    forbidden = {"buy", "sell", "order", "size_increase", "risk_override"}
    keys = set()

    def collect_keys(value):
        if isinstance(value, dict):
            for key, child in value.items():
                keys.add(str(key))
                collect_keys(child)
        elif isinstance(value, list):
            for child in value:
                collect_keys(child)

    collect_keys(report)
    assert forbidden.isdisjoint(keys)


def test_script_json_cli_outputs_valid_report(tmp_path):
    path = _fixture_journal(tmp_path)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--journal", str(path), "--json"],
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["schema_version"] == "p2-025c.coinbase_journal_truth_pnl.v1"
    assert payload["summary"]["total_closed_cycles"] == 4
    assert payload["trade_permission"] == "none"


def test_missing_journal_is_blocked_without_crashing(tmp_path):
    report = script_module.build_journal_truth_report(tmp_path / "missing.csv")

    assert report["journal_found"] is False
    assert report["verdict"] == "JOURNAL_NOT_FOUND"
    assert report["summary"]["total_closed_cycles"] == 0
    assert report["trade_permission"] == "none"


def test_config_disables_probe_without_changing_caps_or_symbols():
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    crypto = config["crypto"]
    global_risk = config["global_risk"]

    assert crypto["coinbase_probe_enabled"] is False
    assert float(crypto["coinbase_probe_notional_usd"]) == pytest.approx(0.50)

    assert float(crypto["max_trade_notional_usd"]) == pytest.approx(10.00)
    assert float(crypto["absolute_hard_trade_cap_usd"]) == pytest.approx(10.00)
    assert float(crypto["max_total_crypto_exposure_usd"]) == pytest.approx(10.00)
    assert global_risk["max_open_positions"] == 1
    assert global_risk["max_trades_per_day"] == 3
    assert crypto["live_symbols"] == ["BTC/USD", "ETH/USD", "ADA/USD", "AVAX/USD", "DOGE/USD", "LINK/USD", "LTC/USD"]
    assert crypto["symbols"] == ["BTC/USD", "ETH/USD", "ADA/USD", "AVAX/USD", "DOGE/USD", "LINK/USD", "LTC/USD"]
    assert crypto["fee_aware_pilot_excluded_symbols"] == ["SOL/USD"]
    assert crypto["controlled_live_symbol_expansion"]["excluded_symbols"] == ["SOL/USD"]
    assert float(crypto["stop_loss_pct"]) == pytest.approx(1.50)
    assert float(crypto["take_profit_pct"]) == pytest.approx(3.00)
    assert crypto["max_position_minutes"] == 90


def test_new_script_has_no_runtime_or_secret_hooks():
    source = SCRIPT.read_text(encoding="utf-8")
    forbidden = [
        "broker_coinbase",
        "CoinbaseBroker",
        "load_dotenv",
        "dotenv",
        "os." + "environ",
        "--live-" + "read-only",
        "create_" + "order",
        "place_" + "order",
        "cancel_" + "order",
        "close_" + "position",
        "launch" + "ctl",
        "append_coinbase_fill_row",
        "logs/coinbase_fills.csv",
    ]

    for token in forbidden:
        assert token not in source
