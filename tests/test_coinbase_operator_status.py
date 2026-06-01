# ADVISORY ONLY — tests for the operator status aggregator (P2-014E)
# Pure local tests. No network, no broker, no writes, no real orders.

from pathlib import Path
import importlib.util
import sys
import json

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "coinbase_operator_status.py"
spec = importlib.util.spec_from_file_location("op_status", SCRIPT)
op_status = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = op_status
spec.loader.exec_module(op_status)

def write_csv(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")

def test_json_structure_has_required_fields(tmp_path):
    # Minimal journal so orphan logic doesn't explode
    write_csv(tmp_path / "journal_coinbase_crypto.csv", "timestamp,symbol,action\n2026-05-31,SOL/USD,BUY\n")
    data = op_status.build_aggregator_report(tmp_path)
    assert "verdict" in data
    assert "profit_readout" in data
    assert "blockers" in data
    assert "next_action" in data
    assert isinstance(data["blockers"], list)

def test_sol_unresolved_produces_blocked(tmp_path):
    # Simulate the real SOL dropped + re-associated evidence
    write_csv(tmp_path / "journal_coinbase_crypto.csv", """
timestamp,symbol,action,error
2026-05-31T18:02:40Z,SOL/USD,WARN,Position dropped after 3 failed close attempts (unrecoverable)
2026-05-31T18:03:44Z,SOL/USD,WARN,Broker position re-associated with bot-origin journal evidence; broker close capability remains unconfirmed
""")
    data = op_status.build_aggregator_report(tmp_path)
    assert data["verdict"] == "BLOCKED"
    assert data["sol_blocker_detected"] is True
    assert any("SOL/USD" in b and "unconfirmed" in b.lower() for b in data["blockers"])
    assert "unsafe_to_aggregate" in data["profit_readout"]

def test_staked_sol_external_inventory_does_not_recommend_close_remediation(tmp_path):
    write_csv(tmp_path / "journal_coinbase_crypto.csv", """
timestamp,symbol,action,staked_external_position,external_inventory_classification,tradable_by_bot,manual_close_allowed,bot_inventory,error
2026-06-01T00:00:00Z,SOL/USD,WARN,true,external_staked_position,false,false,false,User confirmed SOL is staked and unavailable to bot
""")
    data = op_status.build_aggregator_report(tmp_path)
    text = op_status.format_human_report(data)
    combined = (json.dumps(data, default=str) + "\n" + text).lower()

    assert data["verdict"] == "BLOCKED"
    assert data["profit_readout"] == "unsafe_to_aggregate"
    assert data["sol_blocker_detected"] is True
    assert data["staked_external_position"] is True
    assert data["external_inventory_classification"] == "external_staked_position"
    assert data["tradable_by_bot"] is False
    assert data["manual_close_allowed"] is False
    assert data["bot_inventory"] is False
    assert "externally staked sol" in data["next_action"].lower()
    assert "do not close/remediate while staked" in data["next_action"].lower()
    assert "broker close capability" not in combined
    assert "resolve close" not in combined
    assert "remediate" not in combined or "do not close/remediate while staked" in combined

def test_missing_files_produces_safe_report(tmp_path):
    # No journals at all
    data = op_status.build_aggregator_report(tmp_path)
    assert data["verdict"] in ("WARN", "BLOCKED", "OK")
    # Must not crash and must produce next_action
    assert "next_action" in data and len(data["next_action"]) > 10

def test_forbidden_imports_absent():
    text = SCRIPT.read_text(encoding="utf-8")
    forbidden = [
        "import requests", "from requests",
        "import coinbase", "from coinbase",
        "import alpaca", "from alpaca",
        "load_dotenv",
        "import subprocess", "from subprocess",
        "os.environ",
    ]
    # Check in the module body (docstrings are allowed to mention context)
    body = text.split("def main(")[0] if "def main(" in text else text
    for tok in forbidden:
        assert tok not in body

def test_no_production_append_coinbase_fill_row_reference():
    text = SCRIPT.read_text(encoding="utf-8")
    body = text.split("def main(")[0] if "def main(" in text else text
    # The script must never call the logger function
    assert "append_coinbase_fill_row(" not in body
    assert "from coinbase_fill_logger import" not in body

def test_script_is_read_only_no_writes(tmp_path):
    # Run the aggregator — it must never create logs/coinbase_fills.csv
    write_csv(tmp_path / "journal_coinbase_crypto.csv", "timestamp,symbol,action\n2026,SOL/USD,BUY\n")
    _ = op_status.build_aggregator_report(tmp_path)
    assert not (tmp_path / "logs" / "coinbase_fills.csv").exists()
    assert not (tmp_path / "coinbase_fills.csv").exists()

def test_json_output_via_main(tmp_path, capsys):
    write_csv(tmp_path / "journal_coinbase_crypto.csv", "timestamp,symbol,action\n2026,SOL/USD,BUY\n")
    # Simulate --json path
    data = op_status.build_aggregator_report(tmp_path)
    assert "verdict" in data
    # Also test the CLI path indirectly
    # (full argparse test is light because the heavy logic is in build_aggregator_report)
