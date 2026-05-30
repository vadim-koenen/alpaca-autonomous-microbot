from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "coinbase_fill_logging_discovery.py"
    spec = importlib.util.spec_from_file_location("coinbase_fill_logging_discovery", script)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_discovery_finds_coinbase_execution_and_journal_candidates(tmp_path):
    module = load_module()

    (tmp_path / "broker_coinbase.py").write_text(
        """
def submit_order(client_order_id, product_id):
    order_id = "abc"
    filled_size = "0.01"
    average_filled_price = "100"
    fee = "0.01"
    proceeds = "1.00"
    return order_id, filled_size, average_filled_price, fee, proceeds
""",
        encoding="utf-8",
    )
    (tmp_path / "journal_writer.py").write_text(
        """
def append_journal(row):
    row["journal"] = "coinbase fill"
    return row
""",
        encoding="utf-8",
    )
    (tmp_path / "notes.md").write_text("plain docs without target words", encoding="utf-8")

    report = module.discover_repository(tmp_path)

    hit_paths = {hit.path for hit in report.file_hits}
    assert "broker_coinbase.py" in hit_paths
    assert "journal_writer.py" in hit_paths
    assert "notes.md" not in hit_paths

    categories = {hit.path: hit.category for hit in report.file_hits}
    assert categories["broker_coinbase.py"] == "broker/execution path"
    assert categories["journal_writer.py"] == "journal/logging"

    function_names = {hit.name for hit in report.function_hits}
    assert "submit_order" in function_names
    assert "append_journal" in function_names


def test_discovery_skips_env_and_runtime_state_dirs(tmp_path):
    module = load_module()

    (tmp_path / ".env").write_text("COINBASE_SECRET=do-not-read order fee fill", encoding="utf-8")
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "positions.json").write_text(
        '{"coinbase": "fill fee order"}',
        encoding="utf-8",
    )
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime" / "bot.log").write_text("Coinbase order fill fee", encoding="utf-8")
    (tmp_path / "safe.py").write_text("def cycle(): return 'coinbase order'", encoding="utf-8")

    report = module.discover_repository(tmp_path)

    assert ".env" in report.skipped_paths
    assert "state/positions.json" in report.skipped_paths
    assert "runtime/bot.log" in report.skipped_paths

    hit_paths = {hit.path for hit in report.file_hits}
    assert ".env" not in hit_paths
    assert "state/positions.json" not in hit_paths
    assert "runtime/bot.log" not in hit_paths
    assert "safe.py" in hit_paths


def test_render_markdown_contains_required_gate_language(tmp_path):
    module = load_module()

    (tmp_path / "coinbase_client.py").write_text(
        "def get_order(order_id):\n    return {'filled_size': '1', 'fee': '0.01'}\n",
        encoding="utf-8",
    )

    report = module.discover_repository(tmp_path)
    markdown = module.render_markdown(report)

    assert "Class 1 / read-only discovery" in markdown
    assert "Does not call Coinbase APIs" in markdown
    assert "Do not implement fill logging" in markdown
    assert "coinbase_client.py" in markdown

def test_discovery_skips_generated_and_volatile_project_docs(tmp_path):
    module = load_module()

    docs = tmp_path / "docs"
    docs.mkdir()

    generated = docs / "COINBASE_FILL_LOGGING_IMPLEMENTATION_DISCOVERY.md"
    handoff = docs / "ACTIVE_HANDOFF.md"

    generated.write_text("Coinbase order fill fee proceeds self output", encoding="utf-8")
    handoff.write_text("Coinbase order fill fee volatile handoff", encoding="utf-8")
    (tmp_path / "broker_coinbase.py").write_text(
        "def get_order_status(order_id):\n    return {'filled_size': '1', 'fee': '0.01'}\n",
        encoding="utf-8",
    )

    report = module.discover_repository(tmp_path)
    hit_paths = {hit.path for hit in report.file_hits}

    assert "docs/COINBASE_FILL_LOGGING_IMPLEMENTATION_DISCOVERY.md" in report.skipped_paths
    assert "docs/ACTIVE_HANDOFF.md" in report.skipped_paths
    assert "docs/COINBASE_FILL_LOGGING_IMPLEMENTATION_DISCOVERY.md" not in hit_paths
    assert "docs/ACTIVE_HANDOFF.md" not in hit_paths
    assert "broker_coinbase.py" in hit_paths

