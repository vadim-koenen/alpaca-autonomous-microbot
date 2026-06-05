import json
from decimal import Decimal
from pathlib import Path

from scripts import coinbase_enriched_pre_entry_hypothesis_report as report


def _cycle(
    gross,
    *,
    symbol="BTC/USD",
    strategy="momentum_breakout",
    exit_reason="max hold time 90min exceeded",
    idx=0,
    momentum=">=1%",
    volatility="0-0.25%",
    atr="0.25%-0.5%",
    liquidity="normal_0.9x_1.1x",
    vol12="0.001000",
    atr14="0.003000",
    ret3="0.004000",
    ret6="0.006000",
    range3="0.003000",
    volume_ratio="1.000000",
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
        "confidence": 0.90,
        "regime": "uptrend",
        "exit_reason": exit_reason,
        "hold_duration_minutes": "60.000000",
        "entry_spread_pct": "0.000000",
        "entry_basis": "close",
        "source_ohlcv_file": "fixture.csv",
        "pre_entry_return_1": "0.001000",
        "pre_entry_return_3": ret3,
        "pre_entry_return_6": ret6,
        "pre_entry_return_12": "0.012000" if momentum == ">=1%" else "-0.012000",
        "pre_entry_volatility_6": "0.001000",
        "pre_entry_volatility_12": vol12,
        "pre_entry_atr_14": atr14,
        "pre_entry_range_pct_1": "0.002000",
        "pre_entry_range_pct_3": range3,
        "pre_entry_volume": "100.00000000",
        "pre_entry_volume_sma_12": "100.00000000",
        "pre_entry_volume_ratio_12": volume_ratio,
        "pre_entry_liquidity_bucket": liquidity,
        "pre_entry_volatility_bucket": volatility,
        "pre_entry_momentum_bucket": momentum,
        "pre_entry_atr_bucket": atr,
        "pre_entry_hour_utc": idx % 24,
        "pre_entry_day_of_week_utc": "Thu",
        "pre_entry_session_bucket": "00-05" if idx % 24 < 6 else "06-11" if idx % 24 < 12 else "12-17" if idx % 24 < 18 else "18-23",
        "pre_entry_regime": "uptrend",
        "pre_entry_confidence": "0.900000",
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
    wins = sum(1 for cycle in cycles if Decimal(str(cycle["gross_pnl"])) > 0)
    gross_total = sum((Decimal(str(cycle["gross_pnl"])) for cycle in cycles), Decimal("0"))
    return {
        "bars_scanned": len(cycles) * 10,
        "synthetic_cycles_count": len(cycles),
        "gross_summary": {
            "gross_total": str(gross_total),
            "win_rate": round(wins / len(cycles), 6) if cycles else 0.0,
        },
        "synthetic_cycles": cycles,
        "leakage_guards": {
            "pre_entry_features_use_only_past_bars": True,
            "no_exit_reason_in_pre_entry_features": True,
            "no_future_path_in_pre_entry_features": True,
        },
    }


def _report(cycles, top_n=20):
    return report.build_enriched_pre_entry_hypothesis_report(
        source_payload=_payload(cycles),
        synthetic_cycles=cycles,
        top_n=top_n,
    )


def _strong_fixture():
    cycles = []
    for idx in range(20):
        cycles.append(
            _cycle(
                "-0.02",
                symbol="ETH/USD",
                exit_reason="stop-loss hit",
                idx=idx,
                momentum="<=-1%",
                volatility="0.5%-1%",
                atr="0.5%-1%",
                liquidity="thin_<0.5x",
                vol12="0.020000",
                atr14="0.020000",
                ret3="-0.020000",
                ret6="-0.020000",
                range3="0.020000",
                volume_ratio="0.200000",
            )
        )
    for idx in range(60):
        cycles.append(_cycle("0.03", symbol="BTC/USD", exit_reason="take-profit hit", idx=idx + 20))
    return cycles


def test_single_field_hypothesis_math_and_validated_candidate():
    payload = _report(_strong_fixture(), top_n=100)
    row = next(item for item in payload["hypothesis_results"] if item["hypothesis_name"] == "exclude_symbol_ETH/USD")
    assert row["sample_size_before"] == 80
    assert row["sample_size_after"] == 60
    assert row["trades_removed"] == 20
    assert row["stop_loss_removed"] == 20
    assert Decimal(row["gross_after"]) == Decimal("1.80000000")
    assert row["status"] == "validated_candidate"
    assert row["implementation_candidate"] is True
    assert payload["implementation_verdict"]["implementation_authorized"] is False


def test_numeric_threshold_hypothesis_math():
    payload = _report(_strong_fixture(), top_n=200)
    rows = [item for item in payload["hypothesis_results"] if item["hypothesis_name"].startswith("exclude_pre_entry_volatility_12_above")]
    assert rows
    best = max(rows, key=lambda item: Decimal(item["gross_delta"]))
    assert best["input_fields_used"] == ["pre_entry_volatility_12"]
    assert best["leakage_risk"] is False
    assert Decimal(best["gross_delta"]) > 0
    assert best["stop_loss_removed"] >= 1


def test_combination_hypothesis_math():
    payload = _report(_strong_fixture(), top_n=200)
    row = next(
        item for item in payload["hypothesis_results"]
        if item["hypothesis_name"] == "exclude_pre_entry_symbol_strategy_key_ETH/USD|momentum_breakout__pre_entry_momentum_bucket_<=-1%"
    )
    assert row["input_fields_used"] == ["pre_entry_symbol_strategy_key", "pre_entry_momentum_bucket"]
    assert row["sample_size_after"] == 60
    assert row["leakage_risk"] is False


def test_stop_loss_target_allowed_only_as_outcome_and_exit_reason_input_rejected():
    payload = _report(_strong_fixture(), top_n=200)
    leakage_row = next(item for item in payload["hypothesis_results"] if item["hypothesis_name"] == "reject_exit_reason_stop_loss_as_input")
    assert leakage_row["input_fields_used"] == ["exit_reason"]
    assert leakage_row["leakage_risk"] is True
    assert leakage_row["pre_entry_only"] is False
    assert leakage_row["status"] == "rejected"
    assert payload["leakage_controls"]["stop_loss_outcome_used_only_as_target"] is True
    assert payload["leakage_controls"]["exit_reason_filter_input_rejected"] is True


def test_pre_entry_hypotheses_mark_leakage_false():
    payload = _report(_strong_fixture(), top_n=50)
    pre_entry_rows = [row for row in payload["hypothesis_results"] if row["family"] != "leakage_control"]
    assert pre_entry_rows
    assert all(row["leakage_risk"] is False for row in pre_entry_rows)
    assert all(row["pre_entry_only"] is True for row in pre_entry_rows)


def test_sample_size_percent_removed_stop_loss_and_gross_gates():
    cycles = [_cycle("-0.02", symbol="ETH/USD", exit_reason="stop-loss hit", idx=i) for i in range(45)]
    cycles += [_cycle("0.03", symbol="BTC/USD", exit_reason="take-profit hit", idx=i + 45) for i in range(35)]
    payload = _report(cycles, top_n=100)
    row = next(item for item in payload["hypothesis_results"] if item["hypothesis_name"] == "exclude_symbol_ETH/USD")
    assert row["sample_size_after"] == 35
    assert row["percent_trades_removed"] == "0.562500"
    assert "percent_trades_removed > 40%" in row["failed_gates"]
    assert row["status"] != "validated_candidate"


def test_win_rate_median_and_avg_gross_gates():
    cycles = [_cycle("-0.02", symbol="ETH/USD", exit_reason="stop-loss hit", idx=i) for i in range(20)]
    cycles += [_cycle("-0.01", symbol="BTC/USD", idx=i + 20) for i in range(40)]
    cycles += [_cycle("0.01", symbol="BTC/USD", idx=i + 60) for i in range(20)]
    payload = _report(cycles, top_n=100)
    row = next(item for item in payload["hypothesis_results"] if item["hypothesis_name"] == "exclude_symbol_ETH/USD")
    assert "avg_gross_after <= 0" in row["failed_gates"]
    assert "median_gross_after < 0" in row["failed_gates"]
    assert "win_rate_after < 0.52" in row["failed_gates"]


def test_overfit_and_concentration_warnings():
    cycles = [_cycle("-0.02", symbol="ETH/USD", exit_reason="stop-loss hit", idx=i) for i in range(5)]
    cycles += [_cycle("0.50", symbol="BTC/USD", exit_reason="take-profit hit", idx=10)]
    cycles += [_cycle("0.01", symbol="BTC/USD", exit_reason="take-profit hit", idx=i + 20) for i in range(10)]
    payload = _report(cycles, top_n=100)
    row = next(item for item in payload["hypothesis_results"] if item["hypothesis_name"] == "exclude_symbol_ETH/USD")
    assert row["overfit_warning"] is True
    assert row["concentration_warning"] is True
    assert row["status"] == "likely_overfit"


def test_json_schema_and_deterministic_fixture():
    payload = _report(_strong_fixture())
    for key in [
        "schema_version",
        "report_class",
        "source_synthetic_summary",
        "feature_schema",
        "hypothesis_results",
        "top_candidates_by_gross_delta",
        "top_candidates_by_stop_loss_reduction",
        "validated_candidates",
        "provisional_candidates",
        "diagnostic_only_candidates",
        "rejected_candidates_count",
        "likely_overfit_count",
        "best_candidate",
        "implementation_verdict",
        "next_step_recommendation",
    ]:
        assert key in payload
    assert payload["report_class"] == "enriched_pre_entry_hypothesis_testing"
    assert payload["source_synthetic_summary"]["baseline_stop_loss_count"] == 20
    assert payload["source_synthetic_summary"]["baseline_stop_loss_rate"] == "0.250000"
    assert payload["implementation_verdict"]["implementation_authorized"] is False
    json.dumps(payload)


def test_no_network_auth_live_access_or_config_mutation(tmp_path):
    config_path = Path("config_coinbase_crypto.yaml")
    before = config_path.read_text(encoding="utf-8")
    payload = _report(_strong_fixture())
    after = config_path.read_text(encoding="utf-8")
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
    assert "P2-026B" not in strategy_source
    assert "enriched_pre_entry_hypothesis" not in strategy_source
    assert "exclude_pre_entry" not in strategy_source
    assert "P2-026B" not in config_source


def test_write_only_when_output_is_provided(tmp_path, monkeypatch):
    output = tmp_path / "report.json"

    def fake_generator(**kwargs):
        return _payload(_strong_fixture())

    monkeypatch.setattr(report, "build_historical_signal_generator_report", fake_generator)
    assert not output.exists()
    report.main(["--data-dir", str(tmp_path), "--json"])
    assert not output.exists()
    report.main(["--data-dir", str(tmp_path), "--output", str(output), "--json"])
    assert output.exists()
