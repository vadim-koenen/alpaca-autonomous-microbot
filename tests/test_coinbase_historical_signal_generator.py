import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from coinbase_offline_backtest import Bar
from risk_manager import TradeProposal
from scripts import coinbase_historical_signal_generator as gen


def _bars(closes):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for idx, close in enumerate(closes):
        c = Decimal(str(close))
        rows.append(
            Bar(
                t=start + timedelta(minutes=5 * idx),
                o=c,
                h=c,
                l=c,
                c=c,
                v=Decimal("100"),
                symbol="BTC/USD",
            )
        )
    return rows


def _write_csv(tmp_path: Path, closes) -> Path:
    data_dir = tmp_path / "ohlcv"
    data_dir.mkdir(parents=True)
    path = data_dir / "BTC-USD_5m_2026-01-01_2026-01-01.csv"
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    lines = ["timestamp_utc,o,h,l,c,v,symbol"]
    for idx, close in enumerate(closes):
        ts = (start + timedelta(minutes=5 * idx)).isoformat().replace("+00:00", "Z")
        lines.append(f"{ts},{close},{close},{close},{close},100,BTC/USD")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return data_dir


def _write_csv_rows(tmp_path: Path, rows) -> Path:
    data_dir = tmp_path / "ohlcv"
    data_dir.mkdir(parents=True)
    path = data_dir / "BTC-USD_5m_2026-01-01_2026-01-01.csv"
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    lines = ["timestamp_utc,o,h,l,c,v,symbol"]
    for idx, row in enumerate(rows):
        ts = (start + timedelta(minutes=5 * idx)).isoformat().replace("+00:00", "Z")
        lines.append(f"{ts},{row['o']},{row['h']},{row['l']},{row['c']},{row['v']},BTC/USD")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return data_dir


def _proposal(strategy="momentum_breakout", stop=Decimal("98"), target=Decimal("103")):
    return TradeProposal(
        symbol="BTC/USD",
        asset_class="crypto",
        strategy=strategy,
        side="buy",
        order_type="limit",
        notional=5.0,
        limit_price=100.0,
        confidence=0.8,
        price=100.0,
        stop_loss_price=float(stop),
        take_profit_price=float(target),
        meta={"regime": "uptrend"},
    )


def test_ohlcv_fixture_loading(tmp_path):
    data_dir = _write_csv(tmp_path, [100, 101, 102])
    inventory = gen._load_ohlcv_inventory(data_dir)
    assert len(inventory) == 1
    assert inventory[0]["symbol"] == "BTC/USD"
    assert inventory[0]["bar_count"] == 3


def test_no_signal_means_no_fabricated_cycle(tmp_path, monkeypatch):
    data_dir = _write_csv(tmp_path, [100] * 40)
    monkeypatch.setattr(gen, "_run_strategy_methods_for_bar", lambda **kwargs: ([], "range"))
    payload = gen.build_historical_signal_generator_report(data_dir=data_dir)
    assert payload["signal_candidates_count"] == 0
    assert payload["synthetic_cycles_count"] == 0
    assert payload["readiness"]["synthetic_cycle_journal_ready"] is False


def test_signal_produces_synthetic_cycle_and_leakage_guards(tmp_path, monkeypatch):
    data_dir = _write_csv(tmp_path, [100] * 30 + [104, 105])
    seen_history_lengths = []

    def fake_runner(**kwargs):
        seen_history_lengths.append(len(kwargs["history_bars"]))
        return [_proposal(target=Decimal("103"))], "uptrend"

    monkeypatch.setattr(gen, "_run_strategy_methods_for_bar", fake_runner)
    payload = gen.build_historical_signal_generator_report(data_dir=data_dir, max_cycles=1)
    assert payload["signal_candidates_count"] == 1
    assert payload["synthetic_cycles_count"] == 1
    cycle = payload["synthetic_cycles"][0]
    assert cycle["synthetic"] is True
    assert cycle["exit_reason"] == "take-profit hit"
    assert cycle["leakage_guard"]["no_future_bars_for_signal"] is True
    assert cycle["leakage_guard"]["exit_after_entry_only"] is True
    assert cycle["leakage_guard"]["pre_entry_features_use_only_past_bars"] is True
    assert cycle["leakage_guard"]["no_exit_reason_in_pre_entry_features"] is True
    assert cycle["leakage_guard"]["no_future_path_in_pre_entry_features"] is True
    assert seen_history_lengths[0] == 26


def test_pre_entry_returns_use_only_past_bars(tmp_path, monkeypatch):
    shared_history = [100 + idx for idx in range(26)]
    data_dir_a = _write_csv(tmp_path / "a", shared_history + [10, 10, 10])
    data_dir_b = _write_csv(tmp_path / "b", shared_history + [1000, 1000, 1000])

    monkeypatch.setattr(gen, "_run_strategy_methods_for_bar", lambda **kwargs: ([_proposal(target=Decimal("9999"))], "uptrend"))
    payload_a = gen.build_historical_signal_generator_report(data_dir=data_dir_a, max_cycles=1)
    payload_b = gen.build_historical_signal_generator_report(data_dir=data_dir_b, max_cycles=1)
    cycle_a = payload_a["synthetic_cycles"][0]
    cycle_b = payload_b["synthetic_cycles"][0]
    for field in [
        "pre_entry_return_1",
        "pre_entry_return_3",
        "pre_entry_return_6",
        "pre_entry_return_12",
        "pre_entry_momentum_bucket",
        "pre_entry_hour_utc",
        "pre_entry_day_of_week_utc",
    ]:
        assert cycle_a[field] == cycle_b[field]
    assert cycle_a["exit_price"] != cycle_b["exit_price"]


def test_volatility_atr_and_volume_features_use_only_past_bars_and_bucket_deterministically():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    history = []
    for idx in range(26):
        close = Decimal("100") + Decimal(idx % 5)
        history.append(
            Bar(
                t=start + timedelta(minutes=5 * idx),
                o=close - Decimal("0.5"),
                h=close + Decimal("1.0"),
                l=close - Decimal("1.0"),
                c=close,
                v=Decimal("100") + Decimal(idx),
                symbol="BTC/USD",
            )
        )
    future_changed = history + [
        Bar(t=start + timedelta(minutes=5 * 26), o=Decimal("1"), h=Decimal("1000"), l=Decimal("1"), c=Decimal("999"), v=Decimal("9999"), symbol="BTC/USD")
    ]
    features = gen._pre_entry_features(
        symbol="BTC/USD",
        strategy="momentum_breakout",
        history_bars=history,
        regime="uptrend",
        confidence=0.8,
    )
    features_with_future = gen._pre_entry_features(
        symbol="BTC/USD",
        strategy="momentum_breakout",
        history_bars=future_changed[:-1],
        regime="uptrend",
        confidence=0.8,
    )
    assert features == features_with_future
    assert Decimal(features["pre_entry_volatility_12"]) >= 0
    assert Decimal(features["pre_entry_atr_14"]) > 0
    assert Decimal(features["pre_entry_volume_ratio_12"]) > 0
    assert features["pre_entry_liquidity_bucket"] in {
        "thin_<0.5x",
        "below_avg_0.5x_0.9x",
        "normal_0.9x_1.1x",
        "elevated_1.1x_1.5x",
        "high_>1.5x",
    }
    assert features["order_book_spread_available"] is False
    assert features["bid_ask_depth_available"] is False
    assert features["order_book_features_missing_reason"] == "OHLCV-only dataset"


def test_adapter_invocation_with_deterministic_fixture(tmp_path, monkeypatch):
    data_dir = _write_csv(tmp_path, [100 + i * Decimal("0.1") for i in range(40)])
    calls = {"count": 0}

    def fake_momentum(self, symbol, quote, df, prefer_no_trade, buying_power, lookback, regime):
        calls["count"] += 1
        return _proposal(strategy="momentum_breakout", target=Decimal("999"))

    monkeypatch.setattr(gen.CryptoStrategy, "_momentum_breakout", fake_momentum)
    monkeypatch.setattr(gen, "classify_regime", lambda df: "uptrend")
    payload = gen.build_historical_signal_generator_report(data_dir=data_dir, max_cycles=1)
    assert calls["count"] == 1
    assert payload["synthetic_cycles_count"] == 1
    assert "OfflineMarketDataAdapter" in payload["adapter_functions_used"]


def test_exit_simulation_take_profit_stop_loss_timeout_and_end_of_data():
    bars = _bars([100, 101, 104, 104])
    idx, _, price, reason, _ = gen._simulate_exit(
        bars=bars,
        entry_index=0,
        entry_price=Decimal("100"),
        proposal=_proposal(target=Decimal("103")),
        max_hold_minutes=90,
    )
    assert idx == 2
    assert price == Decimal("104")
    assert reason == "take-profit hit"

    bars = _bars([100, 99, 97])
    idx, _, price, reason, _ = gen._simulate_exit(
        bars=bars,
        entry_index=0,
        entry_price=Decimal("100"),
        proposal=_proposal(stop=Decimal("98")),
        max_hold_minutes=90,
    )
    assert idx == 2
    assert price == Decimal("97")
    assert reason == "stop-loss hit"

    bars = _bars([100, 100, 100, 100])
    idx, _, _, reason, _ = gen._simulate_exit(
        bars=bars,
        entry_index=0,
        entry_price=Decimal("100"),
        proposal=_proposal(stop=Decimal("90"), target=Decimal("110")),
        max_hold_minutes=10,
    )
    assert idx == 2
    assert reason == "max hold time 10min exceeded"

    bars = _bars([100, 100.5])
    idx, _, _, reason, _ = gen._simulate_exit(
        bars=bars,
        entry_index=0,
        entry_price=Decimal("100"),
        proposal=_proposal(stop=Decimal("90"), target=Decimal("110")),
        max_hold_minutes=90,
    )
    assert idx == 1
    assert reason == "end_of_data"


def test_json_schema_and_authorization_flags(tmp_path, monkeypatch):
    data_dir = _write_csv(tmp_path, [100] * 30 + [104])
    monkeypatch.setattr(gen, "_run_strategy_methods_for_bar", lambda **kwargs: ([_proposal()], "uptrend"))
    payload = gen.build_historical_signal_generator_report(data_dir=data_dir, max_cycles=1)
    for key in [
        "schema_version",
        "report_class",
        "symbols_scanned",
        "bars_scanned",
        "signal_candidates_count",
        "synthetic_cycles_count",
        "gross_summary",
        "pre_entry_feature_schema",
        "generated_cycle_sample",
        "leakage_guards",
        "readiness",
        "verdict",
    ]:
        assert key in payload
    assert payload["verdict"]["implementation_authorized"] is False
    assert payload["verdict"]["paper_probe_authorized"] is False
    assert payload["verdict"]["live_probe_authorized"] is False
    assert payload["verdict"]["scaling_authorized"] is False
    assert payload["leakage_guards"]["pre_entry_features_use_only_past_bars"] is True
    assert payload["leakage_guards"]["no_exit_reason_in_pre_entry_features"] is True
    assert payload["leakage_guards"]["no_future_path_in_pre_entry_features"] is True
    cycle = payload["synthetic_cycles"][0]
    for field in gen.PRE_ENTRY_FEATURE_SCHEMA["numeric_fields"] + gen.PRE_ENTRY_FEATURE_SCHEMA["categorical_fields"]:
        assert field in cycle
    assert cycle["order_book_spread_available"] is False
    assert cycle["bid_ask_depth_available"] is False
    json.dumps(payload)


def test_write_only_when_output_is_provided(tmp_path, monkeypatch):
    data_dir = _write_csv(tmp_path, [100] * 30 + [104])
    monkeypatch.setattr(gen, "_run_strategy_methods_for_bar", lambda **kwargs: ([_proposal()], "uptrend"))
    output = tmp_path / "cycles.jsonl"
    assert not output.exists()
    gen.main(["--data-dir", str(data_dir), "--max-cycles", "1", "--json"])
    assert not output.exists()
    gen.main(["--data-dir", str(data_dir), "--max-cycles", "1", "--output", str(output), "--json"])
    assert output.exists()
    assert len(output.read_text(encoding="utf-8").strip().splitlines()) == 1


def test_no_network_auth_live_access_or_config_mutation(tmp_path, monkeypatch):
    config_path = Path("config_coinbase_crypto.yaml")
    before = config_path.read_text(encoding="utf-8")
    data_dir = _write_csv(tmp_path, [100] * 30 + [104])
    monkeypatch.setattr(gen, "_run_strategy_methods_for_bar", lambda **kwargs: ([_proposal()], "uptrend"))
    payload = gen.build_historical_signal_generator_report(data_dir=data_dir, max_cycles=1)
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
    source = Path("strategy_crypto.py").read_text(encoding="utf-8")
    assert "P2-025W" not in source
    assert "historical_signal_generator" not in source
