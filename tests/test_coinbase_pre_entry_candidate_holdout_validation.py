import json
from decimal import Decimal
from pathlib import Path

from scripts import coinbase_pre_entry_candidate_holdout_validation as report


def _cycle(
    gross,
    *,
    idx=0,
    symbol="BTC/USD",
    strategy="momentum_breakout",
    ret3="0.004000",
    exit_reason="max hold time 90min exceeded",
):
    day = idx // 24 + 1
    hour = idx % 24
    return {
        "symbol": symbol,
        "strategy": strategy,
        "entry_time": f"2026-01-{day:02d}T{hour:02d}:00:00+00:00",
        "exit_time": f"2026-01-{day:02d}T{(hour + 1) % 24:02d}:00:00+00:00",
        "gross_pnl": str(gross),
        "pnl_usd": str(gross),
        "exit_reason": exit_reason,
        "pre_entry_return_3": ret3,
        "pre_entry_symbol_strategy_key": f"{symbol}|{strategy}",
    }


def _payload(cycles):
    return {
        "bars_scanned": len(cycles) * 10,
        "synthetic_cycles_count": len(cycles),
        "synthetic_cycles": cycles,
        "leakage_guards": {
            "no_future_bars_for_signal": True,
            "exit_after_entry_only": True,
            "no_journal_exit_leakage": True,
            "pre_entry_features_use_only_past_bars": True,
            "no_exit_reason_in_pre_entry_features": True,
            "no_future_path_in_pre_entry_features": True,
        },
    }


def _stable_fixture():
    cycles = []
    symbols = ["BTC/USD", "ETH/USD"]
    strategies = ["momentum_breakout", "mean_reversion"]
    for idx in range(100):
        symbol = symbols[idx % len(symbols)]
        strategy = strategies[(idx // 2) % len(strategies)]
        if idx % 5 == 0:
            cycles.append(
                _cycle(
                    "-0.030000",
                    idx=idx,
                    symbol=symbol,
                    strategy=strategy,
                    ret3="0.013000",
                    exit_reason="stop-loss hit",
                )
            )
        else:
            cycles.append(_cycle("0.020000", idx=idx, symbol=symbol, strategy=strategy, ret3="0.004000"))
    return cycles


def _unstable_fixture():
    cycles = []
    for idx in range(70):
        if idx < 50 and idx % 5 == 0:
            cycles.append(
                _cycle("-0.030000", idx=idx, symbol="ALGO/USD", ret3="0.013000", exit_reason="stop-loss hit")
            )
        else:
            cycles.append(_cycle("0.010000", idx=idx, symbol="BTC/USD", ret3="0.004000"))
    for idx in range(70, 100):
        cycles.append(_cycle("-0.010000", idx=idx, symbol="ETH/USD", ret3="0.004000"))
    return cycles


def _build(cycles, **kwargs):
    return report.build_holdout_validation_report(
        source_payload=_payload(cycles),
        synthetic_cycles=cycles,
        **kwargs,
    )


def test_candidate_rule_uses_only_pre_entry_return_3():
    payload = _build(_stable_fixture())
    assert payload["candidate"]["rule_name"] == report.RULE_NAME
    assert payload["candidate"]["input_field"] == "pre_entry_return_3"
    assert payload["candidate"]["operator"] == ">"
    assert payload["candidate"]["threshold"] == "0.011338"
    assert payload["candidate"]["pre_entry_only"] is True
    assert payload["candidate"]["leakage_risk"] is False


def test_exit_reason_cannot_be_used_as_input():
    row = report.evaluate_candidate_result(
        label="bad_input",
        cycles=_stable_fixture(),
        input_field="exit_reason",
        threshold=Decimal("0"),
    )
    assert row["passes_gate"] is False
    assert "leakage_risk=true" in row["failed_gates"]
    assert "pre_entry_only=false" in row["failed_gates"]


def test_chronological_split_is_deterministic():
    cycles = list(reversed(_stable_fixture()))
    train, holdout = report.chronological_split(cycles)
    assert len(train) == 70
    assert len(holdout) == 30
    assert train[0]["entry_time"] < train[-1]["entry_time"]
    assert train[-1]["entry_time"] < holdout[0]["entry_time"]


def test_holdout_threshold_is_fixed_and_not_reoptimized():
    payload = _build(_stable_fixture())
    assert payload["chronological_train_result"]["threshold"] == "0.011338"
    assert payload["chronological_holdout_result"]["threshold"] == "0.011338"
    thresholds = {row["threshold"] for row in payload["threshold_sensitivity"]}
    assert "0.011338" in thresholds
    assert "0.014000" in thresholds


def test_rolling_folds_are_contiguous_and_deterministic():
    folds = report.rolling_folds(list(reversed(_stable_fixture())), folds=4)
    assert [len(fold) for fold in folds] == [25, 25, 25, 25]
    for left, right in zip(folds, folds[1:]):
        assert left[-1]["entry_time"] < right[0]["entry_time"]


def test_full_sample_math():
    payload = _build(_stable_fixture())
    row = payload["full_sample_result"]
    assert row["sample_size_before"] == 100
    assert row["sample_size_after"] == 80
    assert row["trades_removed"] == 20
    assert row["percent_trades_removed"] == "0.200000"
    assert Decimal(row["gross_before"]) == Decimal("1.00000000")
    assert Decimal(row["gross_after"]) == Decimal("1.60000000")
    assert Decimal(row["gross_delta"]) == Decimal("0.60000000")


def test_holdout_math():
    payload = _build(_stable_fixture())
    row = payload["chronological_holdout_result"]
    assert row["sample_size_before"] == 30
    assert row["sample_size_after"] == 24
    assert row["trades_removed"] == 6
    assert Decimal(row["gross_delta"]) == Decimal("0.18000000")
    assert row["passes_gate"] is True


def test_threshold_sensitivity_math():
    payload = _build(_stable_fixture())
    rows = {row["threshold"]: row for row in payload["threshold_sensitivity"]}
    assert Decimal(rows["0.010000"]["gross_delta"]) == Decimal("0.60000000")
    assert Decimal(rows["0.011338"]["gross_delta"]) == Decimal("0.60000000")
    assert Decimal(rows["0.014000"]["gross_delta"]) == Decimal("0E-8")


def test_symbol_stability_math():
    payload = _build(_stable_fixture())
    rows = {row["group_key"]: row for row in payload["symbol_stability"]}
    assert set(rows) == {"BTC/USD", "ETH/USD"}
    assert all(row["trades_removed"] == 10 for row in rows.values())
    assert all(Decimal(row["gross_delta"]) == Decimal("0.30000000") for row in rows.values())


def test_strategy_stability_math():
    payload = _build(_stable_fixture())
    rows = {row["group_key"]: row for row in payload["strategy_stability"]}
    assert set(rows) == {"mean_reversion", "momentum_breakout"}
    assert all(Decimal(row["gross_delta"]) == Decimal("0.30000000") for row in rows.values())


def test_verdict_gate_logic_holdout_validated_and_unstable():
    stable = _build(_stable_fixture())
    assert stable["stability_verdict"]["verdict"] == "holdout_validated"
    assert stable["stability_verdict"]["implementation_proposal_authorized"] is True
    unstable = _build(_unstable_fixture())
    assert unstable["stability_verdict"]["verdict"] == "unstable_or_overfit"
    assert unstable["stability_verdict"]["likely_overfit"] is True
    assert unstable["stability_verdict"]["implementation_proposal_authorized"] is False


def test_json_schema_and_deterministic_fixture():
    payload = _build(_stable_fixture())
    for key in [
        "schema_version",
        "report_class",
        "candidate",
        "source_synthetic_summary",
        "full_sample_result",
        "chronological_train_result",
        "chronological_holdout_result",
        "rolling_fold_results",
        "symbol_stability",
        "strategy_stability",
        "symbol_strategy_stability",
        "threshold_sensitivity",
        "percentile_sensitivity_diagnostic",
        "stability_verdict",
        "next_step_recommendation",
    ]:
        assert key in payload
    assert payload["report_class"] == "pre_entry_candidate_holdout_validation"
    assert len(payload["rolling_fold_results"]) == 4
    json.dumps(payload)


def test_no_network_auth_live_access_or_config_mutation(tmp_path):
    config_path = Path("config_coinbase_crypto.yaml")
    before = config_path.read_text(encoding="utf-8")
    payload = _build(_stable_fixture())
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
    assert "P2-026C" not in strategy_source
    assert "pre_entry_candidate_holdout" not in strategy_source
    assert "exclude_pre_entry_return_3_above_p80" not in strategy_source
    assert "P2-026C" not in config_source


def test_write_only_when_output_is_provided(tmp_path, monkeypatch):
    output = tmp_path / "report.json"

    def fake_generator(**kwargs):
        return _payload(_stable_fixture())

    monkeypatch.setattr(report, "build_historical_signal_generator_report", fake_generator)
    assert not output.exists()
    report.main(["--data-dir", str(tmp_path), "--json"])
    assert not output.exists()
    report.main(["--data-dir", str(tmp_path), "--output", str(output), "--json"])
    assert output.exists()
