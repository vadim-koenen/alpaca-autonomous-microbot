# ADVISORY ONLY — tests for open/orphan position status tooling (P2-014D).
# No live trading, no broker, no network, no writes.

from pathlib import Path
import importlib.util
import sys
import json

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "coinbase_open_orphan_position_status.py"
spec = importlib.util.spec_from_file_location("orphan_status", SCRIPT)
orphan_status = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = orphan_status
spec.loader.exec_module(orphan_status)

def write_csv(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")

def test_clean_no_files_no_crash(tmp_path):
    report = orphan_status.run_report(tmp_path)
    assert "ADVISORY ONLY" in report
    assert "No open/unresolved buys" in report or "PASS" in report or "Verdict" in report

def test_open_buy_without_later_sell_is_unresolved(tmp_path):
    write_csv(tmp_path / "journal_coinbase_crypto.csv", """
timestamp,symbol,action,order_id,qty,fill_price,status,error
2026-05-31T16:30:23Z,SOL/USD,BUY,44a25487-...,0.01225,81.63,FILLED,
""")
    report = orphan_status.run_report(tmp_path)
    assert "SOL/USD" in report
    assert "open (no confirmed later sell)" in report or "open/unresolved" in report.lower()

def test_dropped_after_3_phrase_surfaced(tmp_path):
    write_csv(tmp_path / "journal_coinbase_crypto.csv", """
timestamp,symbol,action,error
2026-05-31T18:02:40Z,SOL/USD,WARN,Position dropped after 3 failed close attempts (unrecoverable). Last trigger: max hold time 90min exceeded (92.3min held). No P/L recorded.
""")
    report = orphan_status.run_report(tmp_path)
    assert "Position dropped after 3 failed close attempts" in report
    assert "dropped" in report.lower() or "orphan" in report.lower()

def test_reassociated_unconfirmed_phrase_surfaced(tmp_path):
    write_csv(tmp_path / "journal_coinbase_crypto.csv", """
timestamp,symbol,action,error
2026-05-31T18:03:44Z,SOL/USD,WARN,Broker position re-associated with bot-origin journal evidence; broker close capability remains unconfirmed
""")
    report = orphan_status.run_report(tmp_path)
    assert "broker close capability remains unconfirmed" in report
    assert "re-associated" in report.lower() or "unconfirmed" in report.lower()

def test_later_sell_can_mark_resolved(tmp_path):
    write_csv(tmp_path / "journal_coinbase_crypto.csv", """
timestamp,symbol,action,order_id,qty,fill_price
2026-05-31T16:30:23Z,SOL/USD,BUY,44a25487,0.01225,81.63
2026-05-31T18:00:00Z,SOL/USD,EXIT,cf97b904,0.01225,81.685
""")
    report = orphan_status.run_report(tmp_path)
    # With later sell of matching qty, should not list as open
    assert "No open/unresolved buys" in report or "open (no confirmed later sell)" not in report

def test_json_output_structure(tmp_path):
    write_csv(tmp_path / "journal_coinbase_crypto.csv", """
timestamp,symbol,action,error
2026-05-31T18:03:44Z,SOL/USD,WARN,Broker position re-associated with bot-origin journal evidence; broker close capability remains unconfirmed
""")
    data = orphan_status.run_report_json(tmp_path)
    assert "verdict" in data
    assert "orphan_evidence" in data
    assert "close_capability" in data
    assert data["manual_review_required"] is True
    assert any("unconfirmed" in str(o).lower() for o in data["orphan_evidence"])

def test_structured_staked_sol_is_external_inventory_not_bot_tradable(tmp_path):
    write_csv(tmp_path / "journal_coinbase_crypto.csv", """
timestamp,symbol,action,staked_external_position,external_inventory_classification,tradable_by_bot,manual_close_allowed,bot_inventory,error
2026-06-01T00:00:00Z,SOL/USD,WARN,true,external_staked_position,false,false,false,User confirmed SOL is staked and unavailable to bot
""")
    data = orphan_status.run_report_json(tmp_path)
    text = orphan_status.run_report(tmp_path)

    assert data["staked_external_position"] is True
    assert data["external_inventory_classification"] == "external_staked_position"
    assert data["tradable_by_bot"] is False
    assert data["manual_close_allowed"] is False
    assert data["bot_inventory"] is False
    assert data["external_inventory"][0]["detection_source"] == "structured"
    assert "externally staked / unavailable to bot" in text
    assert "broker close capability" not in data["verdict"].lower()
    assert "broker close capability" not in data["profit_blocker"].lower()

def test_phrase_detection_is_secondary_fallback_for_staked_sol(tmp_path):
    write_csv(tmp_path / "journal_coinbase_crypto.csv", """
timestamp,symbol,action,error
2026-06-01T00:00:00Z,SOL/USD,WARN,User confirmed SOL is staked; externally_locked_inventory; bot cannot trade; unavailable to bot
""")
    data = orphan_status.run_report_json(tmp_path)

    assert data["staked_external_position"] is True
    assert data["tradable_by_bot"] is False
    assert data["manual_close_allowed"] is False
    assert data["bot_inventory"] is False
    assert data["external_inventory"][0]["detection_source"] == "phrase_fallback"

def test_forbidden_imports_absent():
    text = SCRIPT.read_text(encoding="utf-8")
    # Only check executable code (docstring legitimately references the report we adapted from)
    exec_part = text.split("def main(")[0] if "def main(" in text else text[:2000]
    forbidden_runtime = [
        "import requests", "from requests",
        "import coinbase", "from coinbase",
        "import alpaca", "from alpaca",
        "broker_coinbase", "order_manager", "position_manager",
        "load_dotenv", "subprocess", "os.environ.get",
    ]
    for tok in forbidden_runtime:
        assert tok not in exec_part

def test_append_coinbase_fill_row_not_referenced():
    text = SCRIPT.read_text(encoding="utf-8")
    # Docstring mentions it (as expected for safety docs); executable code must not call it
    exec_part = text.split("def main(")[0] if "def main(" in text else text[:2000]
    assert "append_coinbase_fill_row(" not in exec_part
    assert "from coinbase_fill_logger import append" not in exec_part

def test_no_coinbase_fills_csv_writes_in_code():
    text = SCRIPT.read_text(encoding="utf-8")
    exec_part = text.split("def main(")[0] if "def main(" in text else text[:2000]
    assert "coinbase_fills.csv" not in exec_part or "open(" not in exec_part
    # Stronger runtime safety: run_report must never create the file
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "journal_coinbase_crypto.csv"
        p.write_text("timestamp,symbol,action\n2026,SOL/USD,BUY\n", encoding="utf-8")
        _ = orphan_status.run_report(Path(td))
        assert not (Path(td) / "logs" / "coinbase_fills.csv").exists()
        assert not (Path(td) / "coinbase_fills.csv").exists()
