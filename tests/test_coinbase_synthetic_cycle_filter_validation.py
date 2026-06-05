import json
from decimal import Decimal
from pathlib import Path

from scripts import coinbase_synthetic_cycle_filter_validation as val


def _cycle(
    gross,
    *,
    symbol="BTC/USD",
    strategy="momentum_breakout",
    exit_reason="max hold time 90min exceeded",
    idx=0,
):
    return {
        "synthetic": True,
        "symbol": symbol,
        "strategy": strategy,
        "entry_time": f"2026-01-01T00:{idx:02d}:00+00:00",
        "exit_time": f"2026-01-01T01:{idx:02d}:00+00:00",
        "gross_pnl": str(gross),
        "pnl_usd": str(gross),
        "exit_reason": exit_reason,
        "leakage_guard": {
            "no_future_bars_for_signal": True,
            "exit_after_entry_only": True,
            "no_journal_exit_leakage": True,
        },
    }


def _payload(cycles):
    wins = sum(1 for c in cycles if Decimal(str(c["gross_pnl"])) > 0)
    gross_total = sum((Decimal(str(c["gross_pnl"])) for c in cycles), Decimal("0"))
    return {
        "bars_scanned": len(cycles) * 10,
        "synthetic_cycles_count": len(cycles),
        "symbols_scanned": sorted({c["symbol"] for c in cycles}),
        "gross_summary": {
            "gross_total": str(gross_total),
            "win_rate": round(wins / len(cycles), 6) if cycles else 0,
        },
        "synthetic_cycles": cycles,
        "leakage_guards": {
            "no_future_bars_for_signal": True,
            "exit_after_entry_only": True,
            "no_journal_exit_leakage": True,
        },
    }


def _report(cycles, top_n=20):
    return val.build_synthetic_cycle_filter_validation_report(
        source_payload=_payload(cycles),
        synthetic_cycles=cycles,
        top_n=top_n,
    )


def _scenario(payload, name):
    return next(row for row in payload["scenario_results"] if row["scenario"] == name)


def test_baseline_scenario_math():
    cycles = [
        _cycle("0.10", idx=0),
        _cycle("-0.05", idx=1),
        _cycle("0.00", idx=2),
    ]
    payload = _report(cycles)
    baseline = _scenario(payload, "baseline_all_synthetic_cycles")
    assert baseline["sample_size"] == 3
    assert Decimal(baseline["synthetic_gross_total"]) == Decimal("0.05000000")
    assert Decimal(baseline["avg_gross"]) == Decimal("0.01666667")
    assert Decimal(baseline["median_gross"]) == Decimal("0E-8")
    assert baseline["win_rate"] == 0.333333
    assert baseline["sample_size_status"] == "weak"


def test_exclude_symbol_filter_math():
    cycles = []
    for idx in range(30):
        cycles.append(_cycle("0.02", symbol="BTC/USD", idx=idx))
        cycles.append(_cycle("-0.01", symbol="ETH/USD", idx=idx))
    payload = _report(cycles)
    baseline = _scenario(payload, "baseline_all_synthetic_cycles")
    exclude_eth = _scenario(payload, "exclude_symbol_ETH/USD")
    assert baseline["sample_size"] == 60
    assert Decimal(baseline["synthetic_gross_total"]) == Decimal("0.30000000")
    assert exclude_eth["sample_size"] == 30
    assert Decimal(exclude_eth["synthetic_gross_total"]) == Decimal("0.60000000")
    assert Decimal(exclude_eth["gross_delta_vs_baseline"]) == Decimal("0.30000000")
    assert exclude_eth["sample_size_status"] == "provisional"


def test_exclude_strategy_filter_math():
    cycles = []
    for idx in range(50):
        cycles.append(_cycle("0.01", strategy="momentum_breakout", idx=idx))
    for idx in range(10):
        cycles.append(_cycle("-0.03", strategy="mean_reversion", idx=idx))
    payload = _report(cycles)
    exclude_mean_reversion = _scenario(payload, "exclude_strategy_mean_reversion")
    assert exclude_mean_reversion["sample_size"] == 50
    assert Decimal(exclude_mean_reversion["synthetic_gross_total"]) == Decimal("0.50000000")
    assert exclude_mean_reversion["sample_size_status"] == "preferred"


def test_exclude_exit_reason_filter_math():
    cycles = []
    for idx in range(40):
        cycles.append(_cycle("0.01", exit_reason="max hold time 90min exceeded", idx=idx))
    for idx in range(20):
        cycles.append(_cycle("-0.02", exit_reason="stop-loss hit", idx=idx))
    payload = _report(cycles)
    exclude_stop = _scenario(payload, "exclude_stop_loss")
    assert exclude_stop["sample_size"] == 40
    assert Decimal(exclude_stop["synthetic_gross_total"]) == Decimal("0.40000000")
    assert exclude_stop["validation_status"] == "provisional_positive"
    assert exclude_stop["candidate_filter_validated"] is False


def test_combination_filter_math():
    cycles = []
    for idx in range(30):
        cycles.append(_cycle("0.02", symbol="BTC/USD", strategy="momentum_breakout", idx=idx))
    for idx in range(20):
        cycles.append(_cycle("-0.02", symbol="ALGO/USD", strategy="momentum_breakout", idx=idx))
    for idx in range(20):
        cycles.append(_cycle("-0.01", symbol="ETH/USD", strategy="mean_reversion", idx=idx))
    payload = _report(cycles)
    combo = _scenario(payload, "exclude_ALGO_and_ETH")
    assert combo["exploratory"] is True
    assert combo["sample_size"] == 30
    assert Decimal(combo["synthetic_gross_total"]) == Decimal("0.60000000")
    assert combo["validation_status"] == "provisional_positive"


def test_sample_size_statuses_and_validation_limit():
    weak = _report([_cycle("0.01", idx=i) for i in range(29)])
    provisional = _report([_cycle("0.01", idx=i) for i in range(30)])
    preferred = _report([_cycle("0.01", idx=i) for i in range(50)])
    assert _scenario(weak, "baseline_all_synthetic_cycles")["sample_size_status"] == "weak"
    assert _scenario(provisional, "baseline_all_synthetic_cycles")["sample_size_status"] == "provisional"
    assert _scenario(preferred, "baseline_all_synthetic_cycles")["sample_size_status"] == "preferred"
    assert _scenario(provisional, "baseline_all_synthetic_cycles")["candidate_filter_validated"] is False
    assert _scenario(provisional, "baseline_all_synthetic_cycles")["validation_status"] == "provisional_positive"


def test_rejected_when_gross_remains_negative():
    payload = _report([_cycle("-0.01", idx=i) for i in range(60)])
    baseline = _scenario(payload, "baseline_all_synthetic_cycles")
    assert baseline["validation_status"] == "rejected"
    assert baseline["candidate_filter_validated"] is False
    assert any("synthetic_gross_total <= 0" in gate for gate in baseline["failed_gates"])


def test_concentration_warning_logic():
    cycles = [_cycle("1.00", idx=0)]
    cycles.extend(_cycle("0.001", idx=i + 1) for i in range(49))
    payload = _report(cycles)
    baseline = _scenario(payload, "baseline_all_synthetic_cycles")
    assert baseline["concentration_warning"] is True
    assert baseline["candidate_filter_validated"] is False


def test_json_schema_and_verdict():
    payload = _report([_cycle("0.01", idx=i) for i in range(50)])
    for key in [
        "schema_version",
        "report_class",
        "source_generator_summary",
        "baseline_summary",
        "scenario_results",
        "best_scenarios_by_gross_delta",
        "validated_filters",
        "provisional_positive_filters",
        "rejected_filters",
        "sample_size_limitations",
        "leakage_guard_summary",
        "verdict",
        "next_step_recommendation",
    ]:
        assert key in payload
    assert payload["report_class"] == "synthetic_cycle_filter_validation"
    assert payload["verdict"]["implementation_authorized"] is False
    assert payload["verdict"]["paper_probe_authorized"] is False
    assert payload["verdict"]["live_probe_authorized"] is False
    assert payload["verdict"]["scaling_authorized"] is False
    json.dumps(payload)


def test_deterministic_fixture_synthetic_cycles():
    cycles = [
        _cycle("0.03", symbol="BTC/USD", strategy="momentum_breakout", idx=0),
        _cycle("-0.02", symbol="ETH/USD", strategy="mean_reversion", idx=1),
        _cycle("-0.01", symbol="ETH/USD", strategy="mean_reversion", idx=2),
    ]
    payload = _report(cycles, top_n=2)
    assert payload["source_generator_summary"]["synthetic_cycles_count"] == 3
    assert payload["best_scenarios_by_gross_delta"][0]["scenario"] in {
        "exclude_symbol_ETH/USD",
        "dynamic_exclude_symbol_ETH/USD",
        "exclude_strategy_mean_reversion",
        "dynamic_exclude_strategy_mean_reversion",
    }


def test_no_network_auth_live_access_or_config_mutation(tmp_path, monkeypatch):
    config_path = Path("config_coinbase_crypto.yaml")
    before = config_path.read_text(encoding="utf-8")
    called = {"generator": False}

    def fake_generator(**kwargs):
        called["generator"] = True
        return _payload([_cycle("0.01", idx=i) for i in range(30)])

    monkeypatch.setattr(val, "build_historical_signal_generator_report", fake_generator)
    payload = val.build_synthetic_cycle_filter_validation_report(data_dir=tmp_path)
    after = config_path.read_text(encoding="utf-8")
    assert called["generator"] is True
    assert after == before
    text = json.dumps(payload).lower()
    for phrase in [
        "create_order",
        "place_order",
        "cancel_order",
        "close_position",
        "launchctl",
        "live-read-only",
        ".env",
        "authorization",
        "bearer",
        "cb-access",
        "api_key",
        "jwt",
    ]:
        assert phrase not in text


def test_no_live_strategy_filter_threshold_changes():
    source = Path("strategy_crypto.py").read_text(encoding="utf-8")
    assert "P2-025X" not in source
    assert "synthetic_cycle_filter_validation" not in source
    assert "exclude_ALGO_and_ETH" not in source


def test_write_only_when_output_is_provided(tmp_path, monkeypatch):
    output = tmp_path / "report.json"

    def fake_generator(**kwargs):
        return _payload([_cycle("0.01", idx=i) for i in range(30)])

    monkeypatch.setattr(val, "build_historical_signal_generator_report", fake_generator)
    assert not output.exists()
    val.main(["--data-dir", str(tmp_path), "--json"])
    assert not output.exists()
    val.main(["--data-dir", str(tmp_path), "--output", str(output), "--json"])
    assert output.exists()
    loaded = json.loads(output.read_text(encoding="utf-8"))
    assert loaded["report_class"] == "synthetic_cycle_filter_validation"
