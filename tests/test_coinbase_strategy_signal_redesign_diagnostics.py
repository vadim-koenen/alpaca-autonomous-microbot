import json
from decimal import Decimal
from pathlib import Path

from scripts import coinbase_strategy_signal_redesign_diagnostics as diag


def _cycle(
    gross,
    *,
    idx=0,
    symbol="BTC/USD",
    strategy="momentum_breakout",
    exit_reason="max hold time 90min exceeded",
    ret3="0.004000",
    regime="uptrend",
    confidence="0.90",
    volatility_bucket="0.25%-0.5%",
    liquidity_bucket="normal_0.9x_1.1x",
    session_bucket="00-05",
):
    return {
        "synthetic": True,
        "symbol": symbol,
        "strategy": strategy,
        "entry_time": f"2026-04-{(idx // 24) + 1:02d}T{idx % 24:02d}:00:00+00:00",
        "exit_time": f"2026-04-{(idx // 24) + 1:02d}T{(idx + 1) % 24:02d}:00:00+00:00",
        "entry_price": "100.00000000",
        "exit_price": "101.00000000",
        "notional": "5.00000000",
        "gross_pnl": str(gross),
        "pnl_usd": str(gross),
        "confidence": confidence,
        "regime": regime,
        "exit_reason": exit_reason,
        "hold_duration_minutes": "90.000000",
        "entry_spread_pct": "0.000000",
        "entry_basis": "close",
        "source_ohlcv_file": "ADA-USD_5m_2026-04-01_2026-04-30.csv",
        "pre_entry_return_1": "0.001000",
        "pre_entry_return_3": ret3,
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
        "pre_entry_liquidity_bucket": liquidity_bucket,
        "pre_entry_volatility_bucket": volatility_bucket,
        "pre_entry_momentum_bucket": ">=1%" if Decimal(str(ret3)) >= Decimal("0.01") else "0-0.5%",
        "pre_entry_atr_bucket": "0.5%-1%",
        "pre_entry_hour_utc": idx % 24,
        "pre_entry_day_of_week_utc": "Thu",
        "pre_entry_session_bucket": session_bucket,
        "pre_entry_regime": regime,
        "pre_entry_confidence": confidence,
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


def _cycles():
    return [
        _cycle("-0.10", idx=0, symbol="ALGO/USD", strategy="momentum_breakout", exit_reason="stop-loss hit"),
        _cycle("-0.08", idx=1, symbol="ALGO/USD", strategy="momentum_breakout", exit_reason="stop-loss hit"),
        _cycle("-0.04", idx=2, symbol="ETH/USD", strategy="mean_reversion", exit_reason="max hold time 90min exceeded"),
        _cycle("-0.02", idx=3, symbol="ETH/USD", strategy="mean_reversion", exit_reason="max hold time 90min exceeded"),
        _cycle("0.03", idx=4, symbol="BTC/USD", strategy="momentum_breakout", exit_reason="take-profit hit", ret3="0.013000"),
        _cycle("0.04", idx=5, symbol="BTC/USD", strategy="momentum_breakout", exit_reason="take-profit hit", ret3="0.013000"),
    ]


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
        "leakage_guards": {
            "no_future_bars_for_signal": True,
            "exit_after_entry_only": True,
            "no_journal_exit_leakage": True,
            "pre_entry_features_use_only_past_bars": True,
            "no_exit_reason_in_pre_entry_features": True,
            "no_future_path_in_pre_entry_features": True,
        },
    }


def _build(cycles=None):
    rows = cycles or _cycles()
    return diag.build_strategy_signal_redesign_diagnostics(
        source_payload=_payload(rows),
        synthetic_cycles=rows,
        generated_at_utc="2026-06-05T00:00:00+00:00",
    )


def _row(rows, key, value):
    return next(row for row in rows if row[key] == value)


def test_json_schema_and_deterministic_fixture():
    payload = _build()
    for key in [
        "schema_version",
        "report_class",
        "generated_at_utc",
        "data_summary",
        "baseline_performance",
        "exit_reason_summary",
        "symbol_performance",
        "strategy_performance",
        "symbol_strategy_performance",
        "regime_performance",
        "confidence_bucket_performance",
        "volatility_bucket_performance",
        "liquidity_bucket_performance",
        "session_bucket_performance",
        "timeout_diagnostics",
        "stop_loss_diagnostics",
        "concentration_risk",
        "falsified_filter_context",
        "redesign_opportunities",
        "recommended_next_patch",
        "authorization",
    ]:
        assert key in payload
    assert payload["report_class"] == "strategy_signal_redesign_diagnostics"
    json.dumps(payload)


def test_baseline_performance_calculations():
    baseline = _build()["baseline_performance"]
    assert baseline["cycles"] == 6
    assert Decimal(baseline["gross_total"]) == Decimal("-0.17000000")
    assert Decimal(baseline["avg_gross"]) == Decimal("-0.02833333")
    assert baseline["win_rate"] == 0.333333
    assert baseline["winners"] == 2
    assert baseline["losers"] == 4


def test_symbol_strategy_and_concentration_calculations():
    payload = _build()
    algo = _row(payload["symbol_performance"], "symbol", "ALGO/USD")
    assert Decimal(algo["gross_total"]) == Decimal("-0.18000000")
    assert algo["stop_loss_count"] == 2
    mean_reversion = _row(payload["strategy_performance"], "strategy", "mean_reversion")
    assert Decimal(mean_reversion["gross_total"]) == Decimal("-0.06000000")
    pair = _row(payload["symbol_strategy_performance"], "symbol_strategy", "ALGO/USD|momentum_breakout")
    assert pair["cycles"] == 2
    assert payload["concentration_risk"]["worst_symbol_strategy_pairs"][0]["symbol_strategy"] == "ALGO/USD|momentum_breakout"
    assert payload["concentration_risk"]["largest_loss_clusters"][0]["gross_total"] == "-0.18000000"


def test_timeout_and_stop_loss_diagnostics():
    payload = _build()
    timeout = payload["timeout_diagnostics"]
    assert timeout["timeout_count"] == 2
    assert timeout["timeout_rate"] == 0.333333
    assert Decimal(timeout["gross_total"]) == Decimal("-0.06000000")
    stop_loss = payload["stop_loss_diagnostics"]
    assert stop_loss["stop_loss_count"] == 2
    assert stop_loss["direct_stop_loss_exclusion_implementable"] is False
    assert Decimal(stop_loss["gross_total"]) == Decimal("-0.18000000")


def test_falsified_context_and_authorization_flags():
    payload = _build()
    context = payload["falsified_filter_context"]
    assert context["p2_026b_candidate"] == diag.P2_026B_CANDIDATE
    assert context["p2_026d_verdict"] == "falsified"
    assert context["filter_implementation_authorized"] is False
    auth = payload["authorization"]
    assert auth["implementation_proposal_authorized"] is False
    assert auth["implementation_authorized"] is False
    assert auth["paper_probe_authorized"] is False
    assert auth["live_probe_authorized"] is False
    assert auth["scaling_authorized"] is False


def test_redesign_opportunities_are_roadmap_items_not_live_winners():
    opportunities = _build()["redesign_opportunities"]
    names = [row["candidate_name"] for row in opportunities]
    assert "retire_or_redesign_weak_strategy_modules" in names
    assert "symbol_strategy_gating_based_on_independent_evidence" in names
    assert "momentum_breakout_redesign_or_retirement" in names
    assert "gross_to_net_fee_slippage_realism_after_stable_gross_edge" in names
    assert all(row["live_implementation_candidate"] is False for row in opportunities)


def test_no_network_auth_live_access_or_config_mutation():
    config_path = Path("config_coinbase_crypto.yaml")
    before = config_path.read_text(encoding="utf-8")
    payload = _build()
    after = config_path.read_text(encoding="utf-8")
    assert after == before
    source = Path("scripts/coinbase_strategy_signal_redesign_diagnostics.py").read_text(encoding="utf-8")
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
    assert "P2-027" not in strategy_source
    assert "strategy_signal_redesign_diagnostics" not in strategy_source
    assert "exclude_pre_entry_return_3_above_p80" not in strategy_source
    assert "P2-027" not in config_source


def test_write_only_when_output_is_provided(tmp_path, monkeypatch):
    output = tmp_path / "report.json"

    def fake_generator(**kwargs):
        rows = _cycles()
        return _payload(rows)

    monkeypatch.setattr(diag, "build_historical_signal_generator_report", fake_generator)
    assert not output.exists()
    diag.main(["--data-dir", str(tmp_path), "--json"])
    assert not output.exists()
    diag.main(["--data-dir", str(tmp_path), "--output", str(output), "--json"])
    assert output.exists()
