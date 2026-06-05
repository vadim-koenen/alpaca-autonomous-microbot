import json
from decimal import Decimal
from pathlib import Path

from scripts import coinbase_stop_loss_diagnostics_report as diag


def _cycle(
    gross,
    *,
    symbol="BTC/USD",
    strategy="momentum_breakout",
    exit_reason="max hold time 90min exceeded",
    confidence=0.90,
    regime="uptrend",
    spread="0.000000",
    idx=0,
):
    return {
        "synthetic": True,
        "symbol": symbol,
        "strategy": strategy,
        "entry_time": f"2026-01-01T{idx % 24:02d}:00:00+00:00",
        "exit_time": f"2026-01-01T{(idx + 1) % 24:02d}:00:00+00:00",
        "entry_price": "100.00000000",
        "exit_price": "101.00000000",
        "notional": "5.00000000",
        "gross_pnl": str(gross),
        "pnl_usd": str(gross),
        "confidence": confidence,
        "regime": regime,
        "exit_reason": exit_reason,
        "hold_duration_minutes": "60.000000",
        "entry_spread_pct": spread,
        "entry_basis": "close",
        "source_ohlcv_file": "fixture.csv",
        "pre_entry_return_1": "0.001000",
        "pre_entry_return_3": "0.003000",
        "pre_entry_return_6": "0.006000",
        "pre_entry_return_12": "0.012000",
        "pre_entry_volatility_6": "0.002000",
        "pre_entry_volatility_12": "0.004000",
        "pre_entry_atr_14": "0.006000",
        "pre_entry_range_pct_1": "0.002000",
        "pre_entry_range_pct_3": "0.003000",
        "pre_entry_volume": "100.00000000",
        "pre_entry_volume_sma_12": "100.00000000",
        "pre_entry_volume_ratio_12": "1.000000",
        "pre_entry_liquidity_bucket": "normal_0.9x_1.1x",
        "pre_entry_volatility_bucket": "0.25%-0.5%",
        "pre_entry_momentum_bucket": ">=1%",
        "pre_entry_atr_bucket": "0.5%-1%",
        "pre_entry_hour_utc": idx % 24,
        "pre_entry_day_of_week_utc": "Thu",
        "pre_entry_session_bucket": "00-05" if idx % 24 < 6 else "06-11" if idx % 24 < 12 else "12-17" if idx % 24 < 18 else "18-23",
        "pre_entry_regime": regime,
        "pre_entry_confidence": str(confidence),
        "pre_entry_symbol_strategy_key": f"{symbol}|{strategy}",
        "order_book_spread_available": False,
        "bid_ask_depth_available": False,
        "order_book_features_missing_reason": "OHLCV-only dataset",
        "leakage_guard": {
            "no_future_bars_for_signal": True,
            "exit_after_entry_only": True,
            "no_journal_exit_leakage": True,
            "pre_entry_features_use_only_past_bars": True,
            "no_exit_reason_in_pre_entry_features": True,
            "no_future_path_in_pre_entry_features": True,
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
    return diag.build_stop_loss_diagnostics_report(
        source_payload=_payload(cycles),
        synthetic_cycles=cycles,
        top_n=top_n,
    )


def test_stop_loss_versus_non_stop_loss_math():
    cycles = [
        _cycle("-0.10", exit_reason="stop-loss hit", idx=0),
        _cycle("-0.20", exit_reason="stop-loss hit", idx=1),
        _cycle("0.30", exit_reason="take-profit hit", idx=2),
        _cycle("0.05", exit_reason="max hold time 90min exceeded", idx=3),
    ]
    payload = _report(cycles)
    summary = payload["stop_loss_summary"]
    assert summary["stop_loss_count"] == 2
    assert summary["non_stop_loss_count"] == 2
    assert Decimal(summary["stop_loss_gross_total"]) == Decimal("-0.30000000")
    assert Decimal(summary["non_stop_loss_gross_total"]) == Decimal("0.35000000")
    assert Decimal(summary["stop_loss_avg_gross"]) == Decimal("-0.15000000")
    assert Decimal(summary["stop_loss_median_gross"]) == Decimal("-0.15000000")


def test_stop_loss_concentration_by_symbol_strategy_and_pair():
    cycles = [
        _cycle("-0.10", symbol="ALGO/USD", strategy="momentum_breakout", exit_reason="stop-loss hit", idx=0),
        _cycle("-0.20", symbol="ALGO/USD", strategy="momentum_breakout", exit_reason="stop-loss hit", idx=1),
        _cycle("-0.05", symbol="ETH/USD", strategy="mean_reversion", exit_reason="stop-loss hit", idx=2),
        _cycle("0.30", symbol="BTC/USD", strategy="momentum_breakout", idx=3),
    ]
    concentration = _report(cycles)["stop_loss_concentration"]
    assert concentration["by_symbol"]["ALGO/USD"]["stop_loss_count"] == 2
    assert concentration["by_strategy"]["momentum_breakout"]["stop_loss_count"] == 2
    assert concentration["by_symbol_strategy"]["ALGO/USD|momentum_breakout"]["stop_loss_count"] == 2


def test_direct_stop_loss_exclusion_is_post_outcome_and_not_implementable():
    payload = _report([
        _cycle("-0.10", exit_reason="stop-loss hit", idx=0),
        _cycle("0.30", idx=1),
    ])
    leakage = payload["leakage_assessment"]
    assert leakage["exclude_stop_loss_is_post_outcome"] is True
    assert leakage["direct_live_filter_implementable"] is False
    assert leakage["pre_entry_predictor_required"] is True
    post_outcome = next(row for row in payload["pre_entry_hypothesis_results"] if row["hypothesis"] == "exclude_stop_loss_post_outcome")
    assert post_outcome["leakage_risk"] is True
    assert post_outcome["pre_entry_implementable"] is False
    assert post_outcome["implementation_candidate"] is False


def test_pre_entry_hypothesis_can_be_candidate_only_from_pre_entry_fields():
    cycles = []
    for idx in range(30):
        cycles.append(_cycle("-0.02", symbol="ETH/USD", exit_reason="stop-loss hit", idx=idx))
    for idx in range(50):
        cycles.append(_cycle("0.03", symbol="BTC/USD", exit_reason="take-profit hit", idx=idx))
    payload = _report(cycles, top_n=50)
    symbol_rule = next(row for row in payload["pre_entry_hypothesis_results"] if row["hypothesis"] == "avoid_symbol_ETH/USD")
    assert symbol_rule["pre_entry_implementable"] is True
    assert symbol_rule["leakage_risk"] is False
    assert symbol_rule["sample_size_remaining"] == 50
    assert symbol_rule["stop_loss_cycles_removed"] == 30
    assert symbol_rule["implementation_candidate"] is True
    assert payload["implementability_verdict"]["any_pre_entry_candidate_found"] is True
    assert payload["implementability_verdict"]["implementation_authorized"] is False


def test_exit_reason_hypothesis_is_marked_leakage():
    payload = _report([
        _cycle("-0.10", exit_reason="stop-loss hit", idx=0),
        _cycle("0.20", exit_reason="take-profit hit", idx=1),
        _cycle("0.05", idx=2),
    ])
    row = next(item for item in payload["pre_entry_hypothesis_results"] if item["hypothesis"] == "exclude_stop_loss_post_outcome")
    assert row["feature"] == "exit_reason"
    assert row["leakage_risk"] is True
    assert row["implementation_candidate"] is False


def test_json_schema_and_verdict_flags():
    payload = _report([_cycle("0.01", idx=i) for i in range(5)])
    for key in [
        "schema_version",
        "report_class",
        "source_synthetic_summary",
        "stop_loss_summary",
        "leakage_assessment",
        "pre_entry_feature_availability",
        "enriched_pre_entry_feature_availability",
        "stop_loss_concentration",
        "pre_entry_hypothesis_results",
        "enriched_pre_entry_hypothesis_results",
        "best_enriched_pre_entry_candidate",
        "any_enriched_pre_entry_candidate_found",
        "implementability_verdict",
        "next_step_recommendation",
    ]:
        assert key in payload
    assert payload["report_class"] == "stop_loss_diagnostics"
    verdict = payload["implementability_verdict"]
    assert verdict["implementation_authorized"] is False
    assert verdict["paper_probe_authorized"] is False
    assert verdict["live_probe_authorized"] is False
    assert verdict["scaling_authorized"] is False
    assert payload["enriched_pre_entry_feature_availability"]["enough_for_enriched_pre_entry_diagnostics"] is True
    json.dumps(payload)


def test_deterministic_fixture_synthetic_cycles():
    cycles = [
        _cycle("-0.02", symbol="ETH/USD", strategy="mean_reversion", exit_reason="stop-loss hit", confidence=0.70, idx=0),
        _cycle("0.04", symbol="BTC/USD", strategy="momentum_breakout", confidence=0.95, idx=1),
        _cycle("0.03", symbol="BTC/USD", strategy="momentum_breakout", confidence=0.90, idx=2),
    ]
    payload = _report(cycles, top_n=5)
    assert payload["source_synthetic_summary"]["synthetic_cycles_count"] == 3
    assert payload["stop_loss_summary"]["stop_loss_symbols"] == ["ETH/USD"]
    assert "confidence" in payload["pre_entry_feature_availability"]["available_features"]
    assert "pre_entry_return_12" in payload["enriched_pre_entry_feature_availability"]["available"]


def test_enriched_diagnostics_consume_pre_entry_features_without_leakage():
    cycles = []
    for idx in range(20):
        row = _cycle("-0.02", exit_reason="stop-loss hit", idx=idx)
        row["pre_entry_return_12"] = "-0.012000"
        row["pre_entry_momentum_bucket"] = "<=-1%"
        cycles.append(row)
    for idx in range(55):
        row = _cycle("0.03", exit_reason="take-profit hit", idx=idx)
        row["pre_entry_return_12"] = "0.012000"
        row["pre_entry_momentum_bucket"] = ">=1%"
        cycles.append(row)
    payload = _report(cycles, top_n=100)
    enriched = payload["enriched_pre_entry_hypothesis_results"]
    row = next(item for item in enriched if item["hypothesis"] == "avoid_pre_entry_return_12_bucket_<=-1%")
    assert row["feature"] == "pre_entry_return_12_bucket"
    assert row["leakage_risk"] is False
    assert row["pre_entry_implementable"] is True
    assert row["implementation_authorized"] is False
    assert payload["implementability_verdict"]["implementation_authorized"] is False


def test_enriched_output_keeps_exit_reason_as_leakage_only():
    payload = _report([
        _cycle("-0.10", exit_reason="stop-loss hit", idx=0),
        _cycle("0.20", exit_reason="take-profit hit", idx=1),
        _cycle("0.05", idx=2),
    ])
    post_row = next(item for item in payload["pre_entry_hypothesis_results"] if item["hypothesis"] == "exclude_stop_loss_post_outcome")
    assert post_row["leakage_risk"] is True
    assert all(row["feature"] != "exit_reason" for row in payload["enriched_pre_entry_hypothesis_results"])
    assert all(row["leakage_risk"] is False for row in payload["enriched_pre_entry_hypothesis_results"])


def test_no_network_auth_live_access_or_config_mutation(tmp_path, monkeypatch):
    config_path = Path("config_coinbase_crypto.yaml")
    before = config_path.read_text(encoding="utf-8")
    called = {"generator": False}

    def fake_generator(**kwargs):
        called["generator"] = True
        return _payload([_cycle("0.01", idx=i) for i in range(30)])

    monkeypatch.setattr(diag, "build_historical_signal_generator_report", fake_generator)
    payload = diag.build_stop_loss_diagnostics_report(data_dir=tmp_path)
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


def test_no_live_strategy_filter_or_threshold_changes():
    strategy_source = Path("strategy_crypto.py").read_text(encoding="utf-8")
    config_source = Path("config_coinbase_crypto.yaml").read_text(encoding="utf-8")
    assert "P2-025Z" not in strategy_source
    assert "stop_loss_diagnostics" not in strategy_source
    assert "avoid_symbol_ETH" not in strategy_source
    assert "P2-025Z" not in config_source


def test_write_only_when_output_is_provided(tmp_path, monkeypatch):
    output = tmp_path / "report.json"

    def fake_generator(**kwargs):
        return _payload([_cycle("0.01", idx=i) for i in range(30)])

    monkeypatch.setattr(diag, "build_historical_signal_generator_report", fake_generator)
    assert not output.exists()
    diag.main(["--data-dir", str(tmp_path), "--json"])
    assert not output.exists()
    diag.main(["--data-dir", str(tmp_path), "--output", str(output), "--json"])
    assert output.exists()
