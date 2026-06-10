import pytest
import pathlib
from scripts.p2_037_journal_provenance_export import _infer_entry_time, parse_journal_csv

def test_infer_entry_time():
    exit_time = "2026-05-25T14:26:07.000Z"
    reason = "max hold time 90min exceeded (90.6min held)"
    entry_time = _infer_entry_time(exit_time, reason)
    assert entry_time is not None
    assert "2026-05-25T12:55:31" in entry_time
    
    # Test fallback
    assert _infer_entry_time(exit_time, "stop-loss hit") is None

def test_parse_journal_csv_with_buy_row(tmp_path):
    csv_file = tmp_path / "journal.csv"
    csv_content = """timestamp,action,decision,symbol,reason,qty,fill_price,exit_price,gross_pnl,pnl_usd,fees_paid
2026-05-25T10:00:00Z,BUY,PLACED,BTC/USD,,1.0,50000.0,,,,
2026-05-25T11:00:00Z,EXIT,PLACED,BTC/USD,tp,1.0,50000.0,51000.0,1000.0,900.0,100.0
"""
    csv_file.write_text(csv_content)
    
    trades = parse_journal_csv(csv_file)
    assert len(trades) == 1
    trade = trades[0]
    assert trade["entry_time"] == "2026-05-25T10:00:00Z"
    assert trade["exit_time"] == "2026-05-25T11:00:00Z"
    assert trade["symbol"] == "BTC/USD"
    assert trade["qty"] == 1.0
    assert trade["entry_price"] == 50000.0
    assert trade["exit_price"] == 51000.0
    assert trade["gross_pnl"] == 1000.0
    assert trade["net_pnl"] == 900.0
    assert trade["fees"] == 100.0

def test_parse_journal_csv_with_infer_entry(tmp_path):
    csv_file = tmp_path / "journal.csv"
    csv_content = """timestamp,action,decision,symbol,reason,qty,fill_price,exit_price,gross_pnl,pnl_usd,fees_paid
2026-05-25T14:26:07Z,EXIT,PLACED,ETH/USD,max hold time 90min exceeded (90.6min held),0.5,2000.0,2010.0,5.0,4.0,1.0
"""
    csv_file.write_text(csv_content)
    
    trades = parse_journal_csv(csv_file)
    assert len(trades) == 1
    trade = trades[0]
    assert trade["entry_time"] is not None
    assert "2026-05-25T12:55:31" in trade["entry_time"]
    assert trade["exit_time"] == "2026-05-25T14:26:07Z"
    assert trade["symbol"] == "ETH/USD"
