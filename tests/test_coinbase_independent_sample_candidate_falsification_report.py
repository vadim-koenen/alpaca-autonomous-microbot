import json
from pathlib import Path

from scripts import coinbase_independent_sample_candidate_falsification_report as report


def _cycle(
    gross,
    *,
    idx=0,
    source="ADA-USD_5m_2026-04-01_2026-04-30.csv",
    ret3="0.004000",
    symbol="BTC/USD",
    strategy="momentum_breakout",
    exit_reason="max hold time 90min exceeded",
):
    return {
        "symbol": symbol,
        "strategy": strategy,
        "entry_time": f"2026-04-{(idx // 24) + 1:02d}T{idx % 24:02d}:00:00+00:00",
        "exit_time": f"2026-04-{(idx // 24) + 1:02d}T{(idx + 1) % 24:02d}:00:00+00:00",
        "gross_pnl": str(gross),
        "pnl_usd": str(gross),
        "exit_reason": exit_reason,
        "source_ohlcv_file": source,
        "pre_entry_return_3": ret3,
        "pre_entry_symbol_strategy_key": f"{symbol}|{strategy}",
    }


def _source_payload(cycles):
    return {
        "bars_scanned": len(cycles) * 10,
        "synthetic_cycles_count": len(cycles),
        "synthetic_cycles": cycles,
        "data_dir": "fixture",
        "leakage_guards": {
            "no_future_bars_for_signal": True,
            "exit_after_entry_only": True,
            "no_journal_exit_leakage": True,
            "pre_entry_features_use_only_past_bars": True,
            "no_exit_reason_in_pre_entry_features": True,
            "no_future_path_in_pre_entry_features": True,
        },
    }


def _write_coverage_files(tmp_path):
    data_dir = tmp_path / "coinbase"
    data_dir.mkdir()
    for symbol in report.DEFAULT_SYMBOLS:
        fname = f"{symbol.replace('/', '-')}_5m_2026-04-01_2026-04-30.csv"
        path = data_dir / fname
        with path.open("w", encoding="utf-8") as f:
            f.write("timestamp_utc,symbol,open,high,low,close,volume\n")
            for idx in range(4):
                f.write(f"2026-04-01T00:{idx*5:02d}:00+00:00,{symbol},100,101,99,100,10\n")
    return data_dir


def _falsified_cycles():
    cycles = []
    for idx in range(40):
        cycles.append(_cycle("0.010000", idx=idx, ret3="0.004000", symbol="BTC/USD"))
    for idx in range(40, 60):
        cycles.append(_cycle("0.020000", idx=idx, ret3="0.013000", symbol="ETH/USD"))
    return cycles


def _unstable_cycles():
    cycles = []
    for idx in range(80):
        if idx % 5 == 0:
            cycles.append(_cycle("-0.030000", idx=idx, ret3="0.013000", symbol="BTC/USD", exit_reason="stop-loss hit"))
        else:
            cycles.append(_cycle("0.020000", idx=idx, ret3="0.004000", symbol="ETH/USD"))
    for idx in range(80, 110):
        cycles.append(
            _cycle(
                "0.020000",
                idx=idx,
                source="BTC-USD_5m_2026-05-01_2026-05-25.csv",
                ret3="0.013000",
                symbol="BTC/USD",
            )
        )
    return cycles


def _validated_cycles():
    cycles = []
    symbols = ["BTC/USD", "ETH/USD"]
    strategies = ["momentum_breakout", "mean_reversion"]
    for idx in range(120):
        symbol = symbols[idx % 2]
        strategy = strategies[(idx // 2) % 2]
        if idx % 5 == 0:
            cycles.append(
                _cycle(
                    "-0.030000",
                    idx=idx,
                    ret3="0.013000",
                    symbol=symbol,
                    strategy=strategy,
                    exit_reason="stop-loss hit",
                )
            )
        else:
            cycles.append(_cycle("0.020000", idx=idx, ret3="0.004000", symbol=symbol, strategy=strategy))
    return cycles


def _build(tmp_path, cycles):
    data_dir = _write_coverage_files(tmp_path)
    return report.build_independent_sample_falsification_report(
        data_dir=data_dir,
        source_payload=_source_payload(cycles),
        synthetic_cycles=cycles,
    )


def test_prior_result_summary(tmp_path):
    payload = _build(tmp_path, _validated_cycles())
    prior = payload["prior_result_summary"]
    assert prior["p2_026b_same_sample_result"]["hypotheses_evaluated"] == 172
    assert prior["p2_026b_same_sample_result"]["best_candidate"] == report.RULE_NAME
    assert prior["p2_026c_holdout_verdict"]["verdict"] == "unstable_or_overfit"


def test_independent_window_labeling(tmp_path):
    payload = _build(tmp_path, _validated_cycles())
    row = payload["independent_window_result"]
    assert row["label"] == "independent_window_2026-04-01_2026-04-30"
    assert row["sample_size_before"] == 120


def test_candidate_fixed_threshold_application(tmp_path):
    payload = _build(tmp_path, _validated_cycles())
    assert payload["candidate"]["threshold"] == "0.011338"
    assert payload["candidate_expanded_result"]["threshold"] == "0.011338"
    assert payload["independent_window_result"]["threshold"] == "0.011338"


def test_no_threshold_reoptimization_on_independent_sample(tmp_path):
    payload = _build(tmp_path, _validated_cycles())
    thresholds = {row["threshold"] for row in payload["threshold_sensitivity"]}
    assert "0.011338" in thresholds
    assert payload["independent_window_result"]["threshold"] == "0.011338"


def test_falsified_verdict_logic(tmp_path):
    payload = _build(tmp_path, _falsified_cycles())
    verdict = payload["falsification_verdict"]
    assert verdict["verdict"] == "falsified"
    assert verdict["falsified"] is True
    assert verdict["implementation_proposal_authorized"] is False


def test_still_unstable_verdict_logic(tmp_path):
    payload = _build(tmp_path, _unstable_cycles())
    verdict = payload["falsification_verdict"]
    assert verdict["verdict"] == "still_unstable"
    assert verdict["likely_overfit"] is True
    assert verdict["implementation_authorized"] is False


def test_independently_validated_verdict_logic(tmp_path):
    payload = _build(tmp_path, _validated_cycles())
    verdict = payload["falsification_verdict"]
    assert verdict["verdict"] == "independently_validated"
    assert verdict["independently_validated"] is True
    assert verdict["implementation_proposal_authorized"] is False


def test_json_schema_and_deterministic_fixture(tmp_path):
    payload = _build(tmp_path, _validated_cycles())
    for key in [
        "schema_version",
        "report_class",
        "candidate",
        "prior_result_summary",
        "independent_data_summary",
        "expanded_synthetic_summary",
        "candidate_expanded_result",
        "independent_window_result",
        "chronological_holdout_result",
        "rolling_fold_results",
        "symbol_stability",
        "strategy_stability",
        "threshold_sensitivity",
        "falsification_verdict",
        "next_step_recommendation",
    ]:
        assert key in payload
    assert payload["report_class"] == "independent_sample_candidate_falsification"
    json.dumps(payload)


def test_no_network_auth_live_access_or_config_mutation(tmp_path):
    config_path = Path("config_coinbase_crypto.yaml")
    before = config_path.read_text(encoding="utf-8")
    payload = _build(tmp_path, _validated_cycles())
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
    assert "P2-026D" not in strategy_source
    assert "independent_sample_candidate_falsification" not in strategy_source
    assert "exclude_pre_entry_return_3_above_p80" not in strategy_source
    assert "P2-026D" not in config_source


def test_write_only_when_output_is_provided(tmp_path, monkeypatch):
    data_dir = _write_coverage_files(tmp_path)
    output = tmp_path / "report.json"

    def fake_generator(**kwargs):
        return _source_payload(_validated_cycles())

    monkeypatch.setattr(report, "build_historical_signal_generator_report", fake_generator)
    assert not output.exists()
    report.main(["--data-dir", str(data_dir), "--json"])
    assert not output.exists()
    report.main(["--data-dir", str(data_dir), "--output", str(output), "--json"])
    assert output.exists()
