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
