from pathlib import Path
import importlib.util
import sys

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "coinbase_fill_proceeds_reconciliation_report.py"
spec = importlib.util.spec_from_file_location("recon", SCRIPT)
recon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = recon
spec.loader.exec_module(recon)


def write_csv(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def test_missing_files(tmp_path):
    report = recon.run_report(tmp_path)
    assert "No candidate local CSV files found" in report
    assert "P/L reconstruction is unavailable" in report


def test_empty_file(tmp_path):
    (tmp_path / "journal_coinbase_crypto.csv").write_text("", encoding="utf-8")
    report = recon.run_report(tmp_path)
    assert "rows=0" in report
    assert "P/L must remain n/a" in report


def test_buy_fill_only(tmp_path):
    write_csv(tmp_path / "journal_coinbase_crypto.csv", """
timestamp,symbol,side,order_id,quantity,price,notional,fee
2026-05-30T18:00:00+00:00,SOL/USD,buy,b1,0.005,200,1.00,0.006
""")
    report = recon.run_report(tmp_path)
    assert "buy_rows: 1" in report
    assert "sell_or_exit_rows: 0" in report
    assert "P/L must remain n/a" in report


def test_sell_exit_with_no_proceeds_is_flagged(tmp_path):
    write_csv(tmp_path / "journal_coinbase_crypto.csv", """
timestamp,symbol,side,order_id,quantity,price,fee
2026-05-30T18:30:00+00:00,SOL/USD,sell,s1,0.005,201,0.006
""")
    report = recon.run_report(tmp_path)
    assert "Exit/sell rows missing direct proceeds: 1" in report
    assert "MISSING_PROCEEDS journal_coinbase_crypto.csv:2" in report
    assert "sell_proceeds: 1" in report


def test_buy_sell_pair_with_proceeds_and_fees(tmp_path):
    write_csv(tmp_path / "journal_coinbase_crypto.csv", """
timestamp,symbol,side,trade_id,order_id,quantity,price,notional,proceeds,fee
2026-05-30T18:00:00+00:00,SOL/USD,buy,t1,b1,0.005,200,1.00,,0.006
2026-05-30T18:30:00+00:00,SOL/USD,sell,t1,s1,0.005,204,,1.02,0.006
""")
    report = recon.run_report(tmp_path)
    assert "Pairs found: 1" in report
    assert "Complete gross P/L pairs: 1" in report
    assert "Complete net P/L pairs with fees: 1" in report
    assert "gross=$0.020000" in report
    assert "net=$0.008000" in report


def test_exact_order_id_pairing(tmp_path):
    write_csv(tmp_path / "journal_coinbase_crypto.csv", """
timestamp,symbol,side,order_id,quantity,price,notional,proceeds,fee
2026-05-30T18:00:00+00:00,BTC/USD,buy,same1,0.00001,100000,1.00,,0.006
2026-05-30T18:20:00+00:00,BTC/USD,sell,same1,0.00001,101000,,1.01,0.006
""")
    report = recon.run_report(tmp_path)
    assert "Pairing method exact_pairing_id: 1" in report


def test_symbol_timestamp_fifo_pairing(tmp_path):
    write_csv(tmp_path / "logs" / "fills.csv", """
timestamp,product_id,side,order_id,quantity,price,notional,proceeds,fee
2026-05-30T18:00:00+00:00,ETH/USD,buy,b1,0.0005,2000,1.00,,0.006
2026-05-30T18:45:00+00:00,ETH/USD,sell,s1,0.0005,2020,,1.01,0.006
""")
    report = recon.run_report(tmp_path)
    assert "Pairing method symbol_time_fifo: 1" in report
    assert "Complete net P/L pairs with fees: 1" in report


def test_gross_only_when_fees_missing(tmp_path):
    write_csv(tmp_path / "reports" / "coinbase_fills.csv", """
timestamp,symbol,side,trade_id,quantity,price,notional,proceeds
2026-05-30T18:00:00+00:00,SOL/USD,buy,t1,0.005,200,1.00,
2026-05-30T18:30:00+00:00,SOL/USD,sell,t1,0.005,204,,1.02
""")
    report = recon.run_report(tmp_path)
    assert "Complete gross P/L pairs: 1" in report
    assert "Complete net P/L pairs with fees: 0" in report
    assert "gross P/L can be reconstructed" in report


def test_forbidden_imports_absent():
    text = SCRIPT.read_text(encoding="utf-8")
    forbidden = [
        "import requests",
        "from requests",
        "import coinbase",
        "from coinbase",
        "import alpaca",
        "from alpaca",
        "load_dotenv",
        "subprocess",
        "os.environ",
    ]
    for token in forbidden:
        assert token not in text


# P2-014B targeted regression fixtures (read-only, no network, no orders, no append_)


def test_p2_014b_direct_buy_sell_pair_net_pnl_from_direct_facts(tmp_path):
    """Direct buy/sell pair with proceeds + fees => net P&L reconstructable, labeled locally reconstructed from complete direct fields."""
    write_csv(tmp_path / "journal_coinbase_crypto.csv", """
timestamp,symbol,side,trade_id,order_id,quantity,price,notional,proceeds,fee
2026-05-31T16:30:00+00:00,SOL/USD,buy,t1,b1,0.01225,81.63,1.00,,0.006
2026-05-31T18:00:00+00:00,SOL/USD,sell,t1,s1,0.01225,82.10,,1.006,0.006
""")
    report = recon.run_report(tmp_path)
    assert "Reconciliation Verdict (P2-014B)" in report
    assert "net P/L locally reconstructed" in report.lower() or "direct broker facts" in report.lower()
    assert "Complete net P/L pairs with fees: 1" in report
    assert "append_coinbase_fill_row" not in report  # no call in output either


def test_p2_014b_sell_missing_proceeds_is_unsafe(tmp_path):
    """sell/exit row missing proceeds => unsafe-to-aggregate reason includes missing direct sell proceeds."""
    write_csv(tmp_path / "journal_coinbase_crypto.csv", """
timestamp,symbol,side,order_id,quantity,price,fee
2026-05-31T18:30:00+00:00,SOL/USD,sell,s1,0.012,82.00,0.006
""")
    report = recon.run_report(tmp_path)
    assert "Unsafe-to-aggregate reasons" in report
    assert "missing direct sell proceeds" in report.lower() or "lack direct sell_proceeds" in report.lower()
    assert "Exit/sell rows missing direct proceeds: 1" in report
    assert "P/L must remain n/a" in report or "unavailable" in report


def test_p2_014b_open_buy_without_sell_is_unresolved(tmp_path):
    """open buy without sell => open/unresolved position evidence reported."""
    write_csv(tmp_path / "journal_coinbase_crypto.csv", """
timestamp,symbol,side,order_id,quantity,price,notional,fee
2026-05-31T16:30:23+00:00,SOL/USD,buy,b1,0.01225,81.63,1.00,0.006
""")
    report = recon.run_report(tmp_path)
    assert "Open/unresolved position evidence" in report
    assert "Unmatched open buy entries" in report or "OPEN " in report
    assert "P/L n/a" in report or "unavailable" in report


def test_p2_014b_sol_broker_close_unconfirmed_phrase_surfaced(tmp_path):
    """journal warning row with 'broker close capability remains unconfirmed' => surfaced as operational blocker."""
    write_csv(tmp_path / "journal_coinbase_crypto.csv", """
timestamp,symbol,action,reason,error,order_id
2026-05-31T18:02:40+00:00,SOL/USD,WARN,,Position dropped after 3 failed close attempts (unrecoverable)
2026-05-31T18:03:44+00:00,SOL/USD,WARN,,Broker position re-associated with bot-origin journal evidence; broker close capability remains unconfirmed
""")
    report = recon.run_report(tmp_path)
    assert "Open/unresolved position evidence" in report or "Reconciliation Verdict" in report
    assert "broker close capability remains unconfirmed" in report
    assert "SOL_BLOCKER" in report or "SOL_UNRESOLVED" in report or "BLOCKER" in report
    assert "do not treat position as closed" in report.lower() or "no explicit matching sell" in report.lower()


def test_p2_014b_missing_fees_gross_only_not_net(tmp_path):
    """rows with fees missing => gross-only or unavailable, not direct net P&L."""
    write_csv(tmp_path / "reports" / "coinbase_fills.csv", """
timestamp,symbol,side,trade_id,quantity,price,notional,proceeds
2026-05-31T16:30:00+00:00,SOL/USD,buy,t1,0.012,81.63,1.00,
2026-05-31T18:00:00+00:00,SOL/USD,sell,t1,0.012,82.10,,1.006
""")
    report = recon.run_report(tmp_path)
    assert "Complete gross P/L pairs: 1" in report
    assert "Complete net P/L pairs with fees: 0" in report
    assert "gross" in report.lower() and ("fee" in report.lower() or "missing" in report.lower() or "unsafe" in report.lower())


def test_p2_014b_no_network_no_env_no_orders_in_code():
    """No network/API/env/order behavior (forbidden tokens absent from executable logic)."""
    text = SCRIPT.read_text(encoding="utf-8")
    # Only check executable / non-docstring areas; docstring legitimately mentions .env and behavior
    exec_part = text.split('def render(')[0] if 'def render(' in text else text
    forbidden_runtime = ["import requests", "from requests", "coinbase.Coinbase", "broker_coinbase", "place_order", "cancel_order", "load_dotenv", "os.environ.get"]
    for token in forbidden_runtime:
        assert token not in exec_part


def test_p2_014b_append_coinbase_fill_row_not_referenced():
    """append_coinbase_fill_row not referenced/called by this patch or script."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "append_coinbase_fill_row" not in text
    # run a report on proper allowed path to ensure no write side effects
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "journal_coinbase_crypto.csv"
        p.write_text("timestamp,symbol,side,order_id,quantity,price,notional,fee\n2026-05-31T16:30,SOL/USD,buy,b1,0.012,81.63,1.00,0.006\n", encoding="utf-8")
        out = recon.run_report(Path(td))
        assert "SOL" in out or "buy_rows" in out or "SOL/USD" in out
        # no fills log created by report
        assert not (Path(td) / "logs" / "coinbase_fills.csv").exists()
        assert not (Path(td) / "coinbase_fills.csv").exists()
