import json
from decimal import Decimal
from pathlib import Path
from scripts.coinbase_candidate_filter_backtest_validation import build_candidate_filter_validation_report

def _write_fixture(tmp_path: Path, *, exit_price_fn, cycles: int = 50):
    journal = tmp_path / "journal.csv"
    ohlcv = tmp_path / "ohlcv.json"
    
    import csv
    with open(journal, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "timestamp", "mode", "symbol", "strategy", "action", "decision", "reason", 
            "confidence", "fill_price", "exit_price", "gross_pnl", "fees_paid", "pnl_usd", 
            "notional"
        ])
        writer.writeheader()
        bar_rows = []
        for idx in range(cycles):
            hour = idx * 2
            entry_ts = f"2026-01-{1 + (hour // 24):02d}T{hour % 24:02d}:00:00Z"
            mid_ts = f"2026-01-{1 + (hour // 24):02d}T{hour % 24:02d}:05:00Z"
            exit_ts = f"2026-01-{1 + (hour // 24):02d}T{hour % 24:02d}:10:00Z"
            symbol = "BTC/USD" if idx % 2 == 0 else "ETH/USD"
            strategy = "momentum" if idx % 2 == 0 else "mean_reversion"
            exit_p = Decimal(exit_price_fn(idx))
            gross = (exit_p - Decimal("100")) * (Decimal("5") / Decimal("100"))
            
            writer.writerow({
                "timestamp": exit_ts,
                "mode": "live",
                "symbol": symbol,
                "strategy": strategy,
                "action": "EXIT",
                "reason": "max hold time 10min exceeded",
                "confidence": "0.75",
                "fill_price": "100",
                "exit_price": str(exit_p),
                "gross_pnl": str(gross),
                "fees_paid": "0.01",
                "pnl_usd": str(gross - Decimal("0.01")),
                "notional": "5"
            })
            
            for ts, close in [(entry_ts, "100"), (mid_ts, "100.5"), (exit_ts, str(exit_p))]:
                bar_rows.append({
                    "timestamp_utc": ts,
                    "o": "100",
                    "h": "105",
                    "l": "95",
                    "c": str(close),
                    "symbol": symbol,
                })
    ohlcv.write_text(json.dumps(bar_rows), encoding="utf-8")
    return journal, ohlcv

def test_filter_validation_math(tmp_path):
    # BTC/USD all winners (102), ETH/USD all losers (98)
    def price_fn(idx):
        return "102" if idx % 2 == 0 else "98"
    
    journal, ohlcv = _write_fixture(tmp_path, exit_price_fn=price_fn, cycles=60)
    payload = build_candidate_filter_validation_report(
        journal_path=journal,
        ohlcv_fixture=ohlcv,
        max_hold_minutes=10,
    )
    
    # baseline should have 60 cycles, gross 0 (30*0.1 + 30*-0.1)
    baseline = next(s for s in payload["scenarios"] if s["scenario_name"] == "baseline_all_cycles")
    assert baseline["sample_size"] == 60
    assert Decimal(baseline["predictive_gross_total"]) == Decimal("0")
    assert baseline["candidate_filter_validated"] is False
    
    # exclude_symbol_ETH/USD should have 30 cycles, gross positive
    exclude_eth = next(s for s in payload["scenarios"] if s["scenario_name"] == "exclude_symbol_ETH/USD")
    assert exclude_eth["sample_size"] == 30
    assert Decimal(exclude_eth["predictive_gross_total"]) > 0
    # WR should be 1.0
    assert exclude_eth["win_rate"] == 1.0
    # status should be validated if it passed all gates
    # Note: Preferred is 50, so 30 might be "provisional" or "validated" depending on how I coded it.
    # In my code: count < 50 failed_gates.append(sample_size < 50) -> provisional.
    assert exclude_eth["status"] == "provisional"

def test_validation_gates_fail_small_sample(tmp_path):
    def price_fn(idx): return "102"
    journal, ohlcv = _write_fixture(tmp_path, exit_price_fn=price_fn, cycles=10)
    payload = build_candidate_filter_validation_report(journal_path=journal, ohlcv_fixture=ohlcv, max_hold_minutes=10)
    
    baseline = next(s for s in payload["scenarios"] if s["scenario_name"] == "baseline_all_cycles")
    assert baseline["sample_size"] == 10
    assert baseline["status"] == "weak/exploratory"
    assert baseline["candidate_filter_validated"] is False

def test_validation_gates_fail_negative_gross(tmp_path):
    def price_fn(idx): return "98"
    journal, ohlcv = _write_fixture(tmp_path, exit_price_fn=price_fn, cycles=60)
    payload = build_candidate_filter_validation_report(journal_path=journal, ohlcv_fixture=ohlcv, max_hold_minutes=10)
    
    baseline = next(s for s in payload["scenarios"] if s["scenario_name"] == "baseline_all_cycles")
    assert baseline["candidate_filter_validated"] is False
    assert any("predictive_gross <= 0" in g for g in baseline["failed_gates"])

def test_safety_and_no_mutation(tmp_path):
    def price_fn(idx): return "100"
    journal, ohlcv = _write_fixture(tmp_path, exit_price_fn=price_fn)
    
    config_path = Path("config_coinbase_crypto.yaml")
    before = config_path.read_text(encoding="utf-8")
    
    payload = build_candidate_filter_validation_report(journal_path=journal, ohlcv_fixture=ohlcv)
    
    after = config_path.read_text(encoding="utf-8")
    assert after == before
    
    text = json.dumps(payload).lower()
    for phrase in ["create_order", "place_order", ".env", "api_key"]:
        assert phrase not in text

def test_json_schema(tmp_path):
    def price_fn(idx): return "100"
    journal, ohlcv = _write_fixture(tmp_path, exit_price_fn=price_fn)
    payload = build_candidate_filter_validation_report(journal_path=journal, ohlcv_fixture=ohlcv)
    
    for key in ["scenarios", "validated_filters", "verdict", "acquisition_plan_for_larger_history"]:
        assert key in payload
    assert payload["verdict"]["implementation_authorized"] is False
