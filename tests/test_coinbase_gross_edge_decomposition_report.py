import json
from decimal import Decimal
from pathlib import Path
from scripts.coinbase_gross_edge_decomposition_report import build_gross_edge_decomposition_report

def _write_fixture(tmp_path: Path, *, exit_price_fn, cycles: int = 50):
    journal = tmp_path / "journal.csv"
    ohlcv = tmp_path / "ohlcv.json"
    
    import csv
    with open(journal, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "timestamp", "mode", "symbol", "strategy", "action", "decision", "reason", 
            "confidence", "fill_price", "exit_price", "gross_pnl", "fees_paid", "pnl_usd", 
            "notional", "spread_pct"
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
                "reason": "max hold time 10min exceeded (10min held)",
                "confidence": "0.75" if idx % 2 == 0 else "0.65",
                "fill_price": "100",
                "exit_price": str(exit_p),
                "gross_pnl": str(gross),
                "fees_paid": "0.12",
                "pnl_usd": str(gross - Decimal("0.12")),
                "notional": "5",
                "spread_pct": "0.08" if idx % 2 == 0 else "0.18"
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

def test_gross_decomposition_math(tmp_path):
    # half winners (102), half losers (98)
    def price_fn(idx):
        return "102" if idx % 2 == 0 else "98"
    
    journal, ohlcv = _write_fixture(tmp_path, exit_price_fn=price_fn)
    payload = build_gross_edge_decomposition_report(
        journal_path=journal,
        ohlcv_fixture=ohlcv,
        max_hold_minutes=10,
    )
    
    assert payload["cycles_analyzed"] == 50
    assert Decimal(payload["predictive_gross_total"]) == Decimal("0") 
    
    assert "BTC/USD" in payload["decomposition"]["per_symbol"]
    assert "ETH/USD" in payload["decomposition"]["per_symbol"]
    assert payload["decomposition"]["per_symbol"]["BTC/USD"]["win_rate"] == 1.0
    assert payload["decomposition"]["per_symbol"]["ETH/USD"]["win_rate"] == 0.0
    
    # 10 min hold should be in 0-15min bucket
    assert "0-15min" in payload["decomposition"]["per_hold_duration"]
    # 0 min delta should be in 0-15min bucket
    assert "0-15min" in payload["decomposition"]["per_parity_delta"]

def test_concentration_analysis(tmp_path):
    # one big loser
    def price_fn(idx):
        return "50" if idx == 0 else "101"
    
    journal, ohlcv = _write_fixture(tmp_path, exit_price_fn=price_fn)
    payload = build_gross_edge_decomposition_report(
        journal_path=journal,
        ohlcv_fixture=ohlcv,
        max_hold_minutes=10,
    )
    
    assert Decimal(payload["concentration"]["worst_1_gross"]) == (Decimal("50") - Decimal("100")) * Decimal("0.05")

def test_counterfactual_filters(tmp_path):
    # ETH/USD are all losers
    def price_fn(idx):
        return "98" if idx % 2 != 0 else "102"
    
    journal, ohlcv = _write_fixture(tmp_path, exit_price_fn=price_fn)
    payload = build_gross_edge_decomposition_report(
        journal_path=journal,
        ohlcv_fixture=ohlcv,
        max_hold_minutes=10,
    )
    
    # exclude ETH/USD should result in positive gross
    assert Decimal(payload["counterfactual_filters"]["exclude_symbol_ETH/USD"]["gross_pnl_sum"]) > 0

def test_safety_and_no_mutation(tmp_path):
    def price_fn(idx): return "100"
    journal, ohlcv = _write_fixture(tmp_path, exit_price_fn=price_fn)
    
    config_path = Path("config_coinbase_crypto.yaml")
    before = config_path.read_text(encoding="utf-8")
    
    payload = build_gross_edge_decomposition_report(journal_path=journal, ohlcv_fixture=ohlcv)
    
    after = config_path.read_text(encoding="utf-8")
    assert after == before
    
    text = json.dumps(payload).lower()
    for phrase in ["create_order", "place_order", ".env", "api_key"]:
        assert phrase not in text

def test_json_schema(tmp_path):
    def price_fn(idx): return "100"
    journal, ohlcv = _write_fixture(tmp_path, exit_price_fn=price_fn)
    payload = build_gross_edge_decomposition_report(journal_path=journal, ohlcv_fixture=ohlcv)
    
    for key in ["decomposition", "counterfactual_filters", "dominant_loss_driver", "candidate_filters_for_future_backtest", "verdict"]:
        assert key in payload
    
    # Check new fields
    assert "per_hold_duration" in payload["decomposition"]
    assert "per_parity_delta" in payload["decomposition"]
    assert "hold_duration_min" in payload["top_10_winners"][0]
    assert "parity_delta_min" in payload["top_10_winners"][0]
    
    assert payload["verdict"]["implementation_authorized"] is False
