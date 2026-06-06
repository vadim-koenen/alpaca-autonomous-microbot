import json
from pathlib import Path

from scripts import coinbase_redesigned_entry_independent_holdout_validation as report


def _cycle(
    gross,
    *,
    idx=0,
    hour=None,
    symbol="BTC/USD",
    strategy="momentum_breakout",
    exit_reason="take-profit hit",
    session=None,
):
    selected_hour = idx % 24 if hour is None else hour
    day = (idx // 24) + 1
    bucket = session
    if bucket is None:
        if selected_hour <= 5:
            bucket = "00-05"
        elif selected_hour <= 11:
            bucket = "06-11"
        elif selected_hour <= 17:
            bucket = "12-17"
        else:
            bucket = "18-23"
    return {
        "symbol": symbol,
        "strategy": strategy,
        "entry_time": f"2026-04-{day:02d}T{selected_hour:02d}:00:00+00:00",
        "exit_time": f"2026-04-{day:02d}T{(selected_hour + 1) % 24:02d}:00:00+00:00",
        "gross_pnl": str(gross),
        "pnl_usd": str(gross),
        "exit_reason": exit_reason,
        "pre_entry_hour_utc": selected_hour,
        "pre_entry_session_bucket": bucket,
        "source_ohlcv_file": "fixture.csv",
    }


def _source_payload(cycles):
    return {
        "bars_scanned": len(cycles) * 10,
        "synthetic_cycles_count": len(cycles),
        "synthetic_cycles": cycles,
        "data_dir": "fixture",
        "date_range": {
            "start": cycles[0]["entry_time"] if cycles else None,
            "end": cycles[-1]["entry_time"] if cycles else None,
        },
    }


def _validated_cycles(days=8):
    cycles = []
    idx = 0
    symbols = ["BTC/USD", "ETH/USD"]
    strategies = ["momentum_breakout", "mean_reversion"]
    for day in range(days):
        for hour in range(24):
            excluded = hour in report.EXCLUDED_UTC_HOURS
            cycles.append(
                _cycle(
                    "-0.030000" if excluded else "0.020000",
                    idx=day * 24,
                    hour=hour,
                    symbol=symbols[(day + hour) % 2],
                    strategy=strategies[(day + hour // 2) % 2],
                    exit_reason="stop-loss hit" if excluded else "take-profit hit",
                )
            )
            idx += 1
    return cycles


def _falsified_cycles(days=8):
    cycles = []
    for day in range(days):
        for hour in range(24):
            excluded = hour in report.EXCLUDED_UTC_HOURS
            cycles.append(
                _cycle(
                    "0.030000" if excluded else "-0.020000",
                    idx=day * 24,
                    hour=hour,
                    symbol="BTC/USD" if hour % 2 == 0 else "ETH/USD",
                    exit_reason="take-profit hit" if excluded else "stop-loss hit",
                )
            )
    return cycles


def _build(cycles=None):
    rows = cycles or _validated_cycles()
    return report.build_redesigned_entry_independent_holdout_validation(
        source_payload=_source_payload(rows),
        synthetic_cycles=rows,
        generated_at_utc="2026-06-06T00:00:00+00:00",
    )


def _stability(rate):
    return {
        "rolling_folds": {"group_count": 4, "positive_effect_count": 4, "positive_effect_rate": rate},
        "symbols": {"group_count": 2, "positive_effect_count": 2, "positive_effect_rate": rate},
        "strategies": {"group_count": 2, "positive_effect_count": 2, "positive_effect_rate": rate},
        "symbol_strategies": {"group_count": 4, "positive_effect_count": 4, "positive_effect_rate": rate},
        "sessions": {"group_count": 4, "positive_effect_count": 4, "positive_effect_rate": rate},
    }


def test_json_schema_and_deterministic_fixture():
    payload = _build()
    for key in [
        "schema_version",
        "report_class",
        "generated_at_utc",
        "candidate",
        "prior_result_summary",
        "data_summary",
        "baseline_performance",
        "candidate_full_sample_result",
        "chronological_holdout_result",
        "independent_window_result",
        "rolling_fold_results",
        "symbol_stability",
        "strategy_stability",
        "symbol_strategy_stability",
        "session_stability",
        "sensitivity_analysis",
        "timeout_reduction_diagnostics",
        "stop_loss_reduction_diagnostics",
        "overfit_risk_summary",
        "holdout_verdict",
        "next_step_recommendation",
    ]:
        assert key in payload
    assert payload["report_class"] == "redesigned_entry_independent_holdout_validation"
    assert payload["generated_at_utc"] == "2026-06-06T00:00:00+00:00"
    json.dumps(payload)


def test_fixed_session_candidate_excludes_only_hours_06_and_17():
    cycles = [
        _cycle("-0.03", idx=0, hour=6),
        _cycle("-0.03", idx=0, hour=17),
        _cycle("0.02", idx=0, hour=7),
        _cycle("0.02", idx=0, hour=16),
    ]
    row = report.evaluate_candidate_result(label="fixture", cycles=cycles, min_after=1)
    assert row["excluded_utc_hours"] == [6, 17]
    assert row["trades_removed"] == 2
    assert row["sample_size_after"] == 2
    assert row["gross_after"] == "0.04000000"


def test_pre_entry_hour_is_primary_and_entry_timestamp_is_fallback():
    primary = _cycle("-0.03", idx=0, hour=6)
    primary["entry_time"] = "2026-04-01T07:00:00+00:00"
    fallback = _cycle("-0.03", idx=0, hour=8)
    fallback.pop("pre_entry_hour_utc")
    fallback["entry_time"] = "2026-04-01T17:00:00+00:00"
    kept = _cycle("0.02", idx=0, hour=8)
    row = report.evaluate_candidate_result(
        label="field_precedence",
        cycles=[primary, fallback, kept],
        min_after=1,
    )
    assert row["trades_removed"] == 2


def test_candidate_is_fixed_and_never_reoptimized():
    payload = _build()
    assert payload["candidate"]["excluded_utc_hours"] == [6, 17]
    assert payload["candidate"]["threshold_reoptimized"] is False
    assert payload["candidate"]["pre_entry_only"] is True
    assert payload["candidate"]["leakage_risk"] is False
    assert all(row["candidate_reoptimized"] is False for row in payload["sensitivity_analysis"])
    selected = [row for row in payload["sensitivity_analysis"] if row["selected_candidate"]]
    assert len(selected) == 1
    assert selected[0]["excluded_utc_hours"] == [6, 17]


def test_chronological_holdout_split_is_ordered_and_deterministic():
    cycles = list(reversed(_validated_cycles(days=5)))
    train, holdout = report.chronological_split(cycles)
    assert len(train) == 84
    assert len(holdout) == 36
    assert train[-1]["entry_time"] < holdout[0]["entry_time"]


def test_independent_recent_window_is_labeled_and_not_claimed_pristine():
    payload = _build()
    row = payload["independent_window_result"]
    assert row["label"] == "independent_recent_window_30d"
    assert row["window_start_utc"]
    assert row["window_end_utc"]
    assert row["window_is_pristine_unseen_sample"] is False


def test_rolling_folds_are_contiguous_and_cover_all_cycles():
    cycles = list(reversed(_validated_cycles(days=5)))
    folds = report.rolling_folds(cycles, folds=4)
    assert len(folds) == 4
    assert sum(len(fold) for fold in folds) == len(cycles)
    assert all(folds[idx][-1]["entry_time"] < folds[idx + 1][0]["entry_time"] for idx in range(3))


def test_symbol_strategy_and_session_stability_calculations():
    payload = _build()
    assert {row["symbol"] for row in payload["symbol_stability"]} == {"BTC/USD", "ETH/USD"}
    assert {row["strategy"] for row in payload["strategy_stability"]} == {
        "mean_reversion",
        "momentum_breakout",
    }
    assert payload["symbol_strategy_stability"]
    assert {row["session"] for row in payload["session_stability"]} == {
        "00-05",
        "06-11",
        "12-17",
        "18-23",
    }


def test_timeout_and_stop_loss_reduction_calculations():
    payload = _build()
    full = payload["candidate_full_sample_result"]
    assert full["stop_loss_count_before"] == 16
    assert full["stop_loss_count_after"] == 0
    assert float(full["stop_loss_rate_reduction"]) > 0
    assert float(full["timeout_rate_reduction"]) == 0
    assert payload["stop_loss_reduction_diagnostics"]["full_sample"]["reduction"] == full[
        "stop_loss_rate_reduction"
    ]


def test_falsified_verdict_logic():
    payload = _build(_falsified_cycles())
    verdict = payload["holdout_verdict"]
    assert verdict["verdict"] == "falsified"
    assert verdict["falsified"] is True
    assert verdict["independently_validated"] is False


def test_still_unstable_verdict_logic():
    verdict = report._holdout_verdict(
        full_result={"passes_gate": True},
        holdout_result={"passes_gate": False},
        independent_result={"passes_gate": False},
        stability=_stability(0.25),
    )
    assert verdict["verdict"] == "still_unstable"
    assert verdict["likely_overfit"] is True


def test_provisionally_stable_verdict_logic():
    verdict = report._holdout_verdict(
        full_result={"passes_gate": True},
        holdout_result={"passes_gate": True},
        independent_result={"passes_gate": False},
        stability=_stability(0.50),
    )
    assert verdict["verdict"] == "provisionally_stable_needs_more_data"
    assert verdict["independently_validated"] is False


def test_independently_validated_verdict_logic_still_authorizes_nothing():
    payload = _build()
    verdict = payload["holdout_verdict"]
    assert verdict["verdict"] == "independently_validated"
    assert verdict["independently_validated"] is True
    assert verdict["implementation_proposal_authorized"] is False
    assert verdict["implementation_authorized"] is False
    assert verdict["paper_probe_authorized"] is False
    assert verdict["live_probe_authorized"] is False
    assert verdict["scaling_authorized"] is False


def test_p2_028_prior_result_and_definition_caveat_are_preserved():
    prior = _build()["prior_result_summary"]
    assert prior["p2_028_status"] == "validation_ready"
    assert prior["p2_028_gross_delta_vs_baseline"] == "0.55992776"
    assert prior["p2_028_win_rate"] == 0.533333
    assert prior["p2_028_sample_size"] == 90
    assert "broad 06-11 and 12-17" in prior["definition_caveat"]


def test_no_network_auth_live_access_or_config_mutation():
    config_path = Path("config_coinbase_crypto.yaml")
    before = config_path.read_text(encoding="utf-8")
    payload = _build()
    after = config_path.read_text(encoding="utf-8")
    assert after == before
    source = Path(report.__file__).read_text(encoding="utf-8").lower()
    for phrase in [
        "import requests",
        "import broker",
        "coinbaseadvancedtradeapi",
        "create_order(",
        "place_order(",
        "cancel_order(",
        "close_position(",
        "launchctl",
        "live-read-only",
        "dotenv",
        "os.environ",
    ]:
        assert phrase not in source
    assert payload["data_summary"]["data_offline_ohlcv_untracked_expected"] is True


def test_no_live_filter_strategy_threshold_or_stop_loss_exclusion_changes():
    strategy_source = Path("strategy_crypto.py").read_text(encoding="utf-8")
    config_source = Path("config_coinbase_crypto.yaml").read_text(encoding="utf-8")
    assert "P2-029" not in strategy_source
    assert report.CANDIDATE_NAME not in strategy_source
    assert "P2-029" not in config_source
    assert report.CANDIDATE_NAME not in config_source


def test_write_only_when_output_is_provided(tmp_path, monkeypatch):
    output = tmp_path / "report.json"

    def fake_generator(**kwargs):
        return _source_payload(_validated_cycles())

    monkeypatch.setattr(report, "build_historical_signal_generator_report", fake_generator)
    assert not output.exists()
    report.main(["--data-dir", str(tmp_path), "--json"])
    assert not output.exists()
    report.main(["--data-dir", str(tmp_path), "--output", str(output), "--json"])
    assert output.exists()
