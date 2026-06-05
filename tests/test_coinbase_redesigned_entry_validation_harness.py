import json
from decimal import Decimal
from pathlib import Path

from scripts import coinbase_redesigned_entry_validation_harness as harness


def _cycle(
    gross,
    *,
    idx=0,
    symbol="BTC/USD",
    strategy="momentum_breakout",
    exit_reason="max hold time 90min exceeded",
    ret3="0.004000",
    ret6="0.006000",
    ret12="0.012000",
    regime="uptrend",
    confidence="0.90",
    vol_bucket="0.25%-0.5%",
    liq_bucket="normal_0.9x_1.1x",
    session="00-05",
):
    return {
        "symbol": symbol,
        "strategy": strategy,
        "entry_time": f"2026-04-{(idx // 24) + 1:02d}T{idx % 24:02d}:00:00+00:00",
        "exit_time": f"2026-04-{(idx // 24) + 1:02d}T{(idx + 1) % 24:02d}:00:00+00:00",
        "gross_pnl": str(gross),
        "pnl_usd": str(gross),
        "exit_reason": exit_reason,
        "source_ohlcv_file": "fixture.csv",
        "confidence": confidence,
        "regime": regime,
        "pre_entry_return_3": ret3,
        "pre_entry_return_6": ret6,
        "pre_entry_return_12": ret12,
        "pre_entry_regime": regime,
        "pre_entry_confidence": confidence,
        "pre_entry_volatility_bucket": vol_bucket,
        "pre_entry_liquidity_bucket": liq_bucket,
        "pre_entry_session_bucket": session,
        "pre_entry_symbol_strategy_key": f"{symbol}|{strategy}",
    }


def _payload(cycles):
    gross_total = sum((Decimal(str(c["gross_pnl"])) for c in cycles), Decimal("0"))
    wins = sum(1 for c in cycles if Decimal(str(c["gross_pnl"])) > 0)
    return {
        "bars_scanned": len(cycles) * 10,
        "synthetic_cycles_count": len(cycles),
        "symbols_scanned": sorted({c["symbol"] for c in cycles}),
        "gross_summary": {
            "gross_total": str(gross_total),
            "win_rate": round(wins / len(cycles), 6) if cycles else 0,
        },
        "synthetic_cycles": cycles,
        "data_dir": "fixture",
    }


def _mixed_cycles():
    cycles = []
    for idx in range(20):
        cycles.append(
            _cycle(
                "-0.020000",
                idx=idx,
                symbol="ALGO/USD",
                strategy="momentum_breakout",
                exit_reason="stop-loss hit",
                ret3="-0.004000",
                ret6="-0.003000",
                ret12="-0.002000",
                confidence="0.70",
                vol_bucket="0.5%-1%",
                liq_bucket="elevated_1.1x_1.5x",
                session="06-11",
            )
        )
    for idx in range(20, 60):
        cycles.append(
            _cycle(
                "0.015000",
                idx=idx,
                symbol="BTC/USD" if idx % 2 == 0 else "ETH/USD",
                strategy="momentum_breakout",
                exit_reason="take-profit hit" if idx % 3 == 0 else "max hold time 90min exceeded",
                confidence="0.90",
                session="00-05",
            )
        )
    return cycles


def _validation_ready_cycles():
    cycles = []
    for idx in range(24):
        cycles.append(
            _cycle(
                "-0.015000",
                idx=idx,
                symbol="ALGO/USD",
                strategy="momentum_breakout",
                exit_reason="stop-loss hit",
                ret3="-0.003000",
                ret6="-0.003000",
                ret12="-0.003000",
                confidence="0.70",
                session="06-11",
            )
        )
    for idx in range(24, 84):
        cycles.append(
            _cycle(
                "0.020000",
                idx=idx,
                symbol="BTC/USD" if idx % 2 == 0 else "ETH/USD",
                strategy="momentum_breakout",
                exit_reason="take-profit hit",
                ret3="0.004000",
                ret6="0.004000",
                ret12="0.004000",
                confidence="0.90",
                session="00-05" if idx % 2 == 0 else "18-23",
            )
        )
    return cycles


def _promising_cycles():
    cycles = []
    for idx in range(20):
        cycles.append(
            _cycle(
                "-0.020000",
                idx=idx,
                ret3="-0.004000",
                ret6="-0.004000",
                ret12="-0.004000",
                confidence="0.70",
                exit_reason="stop-loss hit",
            )
        )
    for idx in range(20, 55):
        cycles.append(_cycle("0.020000", idx=idx, confidence="0.90"))
    return cycles


def _small_sample_cycles():
    cycles = []
    for idx in range(10):
        cycles.append(_cycle("-0.020000", idx=idx, ret3="-0.004000", ret6="-0.004000"))
    for idx in range(10, 20):
        cycles.append(_cycle("0.020000", idx=idx, ret3="0.004000", ret6="0.004000"))
    return cycles


def _build(cycles=None):
    rows = cycles or _mixed_cycles()
    return harness.build_redesigned_entry_validation_harness(
        source_payload=_payload(rows),
        synthetic_cycles=rows,
        generated_at_utc="2026-06-05T00:00:00+00:00",
    )


def _candidate(payload, name):
    return next(row for row in payload["candidates"] if row["candidate_name"] == name)


def test_json_schema_and_deterministic_fixture():
    payload = _build()
    for key in [
        "schema_version",
        "report_class",
        "generated_at_utc",
        "data_summary",
        "baseline_performance",
        "candidate_families_evaluated",
        "candidates",
        "family_summary",
        "symbol_stability",
        "strategy_stability",
        "symbol_strategy_stability",
        "regime_stability",
        "timeout_reduction_diagnostics",
        "stop_loss_reduction_diagnostics",
        "overfit_risk_summary",
        "recommended_next_patch",
        "authorization",
    ]:
        assert key in payload
    assert payload["report_class"] == "redesigned_entry_validation_harness"
    json.dumps(payload)


def test_baseline_performance_calculations():
    baseline = _build()["baseline_performance"]
    assert baseline["sample_size"] == 60
    assert Decimal(baseline["gross_total"]) == Decimal("0.20000000")
    assert Decimal(baseline["avg_gross"]) == Decimal("0.00333333")
    assert baseline["win_rate"] == 0.666667
    assert baseline["stop_loss_count"] == 20


def test_candidate_family_generation_and_fixed_threshold_behavior():
    payload = _build()
    families = set(payload["candidate_families_evaluated"])
    assert "momentum_confirmation_redesign" in families
    assert "mean_reversion_redesign" in families
    assert "timeout_risk_reduction_diagnostics" in families
    candidate = _candidate(payload, "confidence_keep_085_or_higher")
    assert candidate["rule_description"] == "Keep entries only when pre-entry confidence is at least 0.85."
    assert candidate["input_fields"] == ["pre_entry_confidence"]
    assert candidate["pre_entry_only"] is True


def test_no_post_outcome_leakage_fields_used():
    payload = _build()
    post_fields = {"exit_reason", "exit_price", "exit_time", "gross_pnl", "pnl_usd", "hold_duration_minutes"}
    for candidate in payload["candidates"]:
        assert post_fields.isdisjoint(set(candidate["input_fields"]))
        assert candidate["leakage_risk"] is False


def test_sample_size_rejection_logic():
    payload = _build(_small_sample_cycles())
    candidate = _candidate(payload, "momentum_confirmation_keep_positive_3_and_6_bar")
    assert candidate["status"] == "rejected"
    assert "sample_size < 30" in candidate["rejection_reasons"]


def test_promising_needs_holdout_logic():
    payload = _build(_promising_cycles())
    candidate = _candidate(payload, "momentum_confirmation_keep_positive_3_and_6_bar")
    assert candidate["status"] == "promising_needs_holdout"
    assert candidate["required_next_validation"] == "independent_holdout_validation_required_before_any_implementation_proposal"


def test_validation_ready_logic_still_does_not_authorize_live_change():
    payload = _build(_validation_ready_cycles())
    candidate = _candidate(payload, "momentum_confirmation_keep_positive_3_and_6_bar")
    assert candidate["status"] == "validation_ready"
    assert payload["overfit_risk_summary"]["validation_ready_count"] >= 1
    assert payload["authorization"]["implementation_authorized"] is False
    assert payload["authorization"]["live_probe_authorized"] is False


def test_timeout_and_stop_loss_reduction_calculations():
    payload = _build()
    candidate = _candidate(payload, "momentum_confirmation_keep_positive_3_and_6_bar")
    assert Decimal(candidate["stop_loss_rate_delta_vs_baseline"]) > 0
    assert "stop_loss_rate_delta_vs_baseline" in payload["stop_loss_reduction_diagnostics"][0]
    assert "timeout_rate_delta_vs_baseline" in payload["timeout_reduction_diagnostics"][0]


def test_falsified_context_and_authorization_flags():
    payload = _build()
    assert payload["falsified_filter_context"]["p2_026b_candidate"] == harness.P2_026B_CANDIDATE
    assert payload["falsified_filter_context"]["p2_026d_verdict"] == "falsified"
    assert payload["falsified_filter_context"]["do_not_implement_prior_filter"] is True
    auth = payload["authorization"]
    assert auth["implementation_proposal_authorized"] is False
    assert auth["implementation_authorized"] is False
    assert auth["paper_probe_authorized"] is False
    assert auth["live_probe_authorized"] is False
    assert auth["scaling_authorized"] is False


def test_no_network_auth_live_access_or_config_mutation():
    config_path = Path("config_coinbase_crypto.yaml")
    before = config_path.read_text(encoding="utf-8")
    payload = _build()
    after = config_path.read_text(encoding="utf-8")
    assert after == before
    source = Path("scripts/coinbase_redesigned_entry_validation_harness.py").read_text(encoding="utf-8")
    for phrase in [
        "import requests",
        "from requests",
        "broker_coinbase",
        "load_dotenv",
        "os.environ",
        "create_order",
        "place_order",
        "cancel_order",
        "close_position",
        "launchctl",
        "live-read-only",
        ".env",
        "api_key",
        "secret",
        "JWT",
    ]:
        assert phrase not in source
    text = json.dumps(payload).lower()
    for phrase in ["api_key", "jwt", "create_order", "place_order", "cancel_order", "close_position"]:
        assert phrase not in text


def test_no_live_strategy_filter_or_threshold_changes():
    strategy_source = Path("strategy_crypto.py").read_text(encoding="utf-8")
    config_source = Path("config_coinbase_crypto.yaml").read_text(encoding="utf-8")
    assert "P2-028" not in strategy_source
    assert "redesigned_entry_validation_harness" not in strategy_source
    assert "exclude_pre_entry_return_3_above_p80" not in strategy_source
    assert "P2-028" not in config_source


def test_write_only_when_output_is_provided(tmp_path, monkeypatch):
    output = tmp_path / "report.json"

    def fake_generator(**kwargs):
        rows = _mixed_cycles()
        return _payload(rows)

    monkeypatch.setattr(harness, "build_historical_signal_generator_report", fake_generator)
    assert not output.exists()
    harness.main(["--data-dir", str(tmp_path), "--json"])
    assert not output.exists()
    harness.main(["--data-dir", str(tmp_path), "--output", str(output), "--json"])
    assert output.exists()
