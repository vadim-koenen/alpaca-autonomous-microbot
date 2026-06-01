# ADVISORY ONLY — tests for the fill/position lifecycle reconciliation script (P2-017B)

from pathlib import Path
import importlib.util
import sys
import json
import tempfile
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "coinbase_fill_position_lifecycle_reconciliation.py"
spec = importlib.util.spec_from_file_location("lifecycle", SCRIPT)
lifecycle = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = lifecycle
spec.loader.exec_module(lifecycle)


def _write_probe(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "probe.json"
    p.write_text(json.dumps(payload))
    return p


def test_current_sol_position_matches_latest_buy_fill_by_exact_size(tmp_path):
    """Exact size match between current broker SOL position and a recent BUY fill must be detected."""
    probe = {
        "verdict": "BLOCKED",
        "profit_readout": "unsafe_to_aggregate",
        "live_read_only": True,
        "broker_calls_made": True,
        "broker_read_successful": True,
        "sol_on_broker": True,
        "open_positions_on_broker": [
            {"symbol": "SOL/USD", "qty": 0.0122504, "market_value": 1.0134755, "current_price": 82.715, "side": "long", "avg_entry_price": 0.0}
        ],
        "recent_fills_sample": [
            {"trade_id": "1f10a7cb-...", "product_id": "SOL-USD", "side": "BUY", "size": "0.0122504", "price": "81.63", "fee": None, "filled_value": None},
            {"trade_id": "bc7e...", "product_id": "SOL-USD", "side": "SELL", "size": "0.01", "price": "81.68", "fee": None, "filled_value": None},
        ],
    }
    probe_file = _write_probe(tmp_path, probe)
    report = lifecycle._build_report(probe_file)

    assert report["current_sol_qty"] == 0.0122504
    assert report["likely_current_sol_entry_size"] == 0.0122504
    assert report["likely_current_sol_entry_price"] == 81.63
    assert report["reconciliation_status"] == "current_sol_likely_matched_to_recent_buy_but_pnl_unsafe"
    assert report["fees_available_for_current_sol_entry"] is False
    assert report["net_pnl_available"] is False


def test_provisional_gross_cost_and_unrealized_pnl_are_calculated_correctly(tmp_path):
    """Gross cost (size*price) and gross unrealized PnL (mv - cost) must be computed from matched BUY."""
    probe = {
        "broker_read_successful": True,
        "sol_on_broker": True,
        "open_positions_on_broker": [
            {"symbol": "SOL/USD", "qty": 0.0122504, "market_value": 1.0134755, "current_price": 82.715}
        ],
        "recent_fills_sample": [
            {"trade_id": "match", "product_id": "SOL-USD", "side": "BUY", "size": 0.0122504, "price": 81.63, "fee": None, "filled_value": None},
        ],
    }
    probe_file = _write_probe(tmp_path, probe)
    report = lifecycle._build_report(probe_file)

    expected_cost = 0.0122504 * 81.63
    assert abs(report["likely_current_sol_entry_gross_cost_estimate"] - expected_cost) < 1e-9
    expected_pnl = 1.0134755 - expected_cost
    assert abs(report["current_sol_gross_unrealized_pnl_estimate"] - expected_pnl) < 1e-9


def test_missing_fee_and_filled_value_prevents_net_pnl_and_keeps_unsafe(tmp_path):
    """Even with perfect size match, missing fee + filled_value must force net_pnl_available=false and unsafe_to_aggregate."""
    probe = {
        "broker_read_successful": True,
        "sol_on_broker": True,
        "open_positions_on_broker": [{"symbol": "SOL/USD", "qty": 0.0122504, "market_value": 1.01}],
        "recent_fills_sample": [
            {"trade_id": "x", "product_id": "SOL-USD", "side": "BUY", "size": "0.0122504", "price": "81.63", "fee": None, "filled_value": None},
        ],
    }
    probe_file = _write_probe(tmp_path, probe)
    report = lifecycle._build_report(probe_file)

    assert report["fees_available_for_current_sol_entry"] is False
    assert report["filled_value_available_for_current_sol_entry"] is False
    assert report["net_pnl_available"] is False
    assert report["profit_readout"] == "unsafe_to_aggregate"


def test_sell_fills_are_not_treated_as_open_positions(tmp_path):
    """SELL fills must never be selected as the 'likely current entry' for a long position."""
    probe = {
        "broker_read_successful": True,
        "sol_on_broker": True,
        "open_positions_on_broker": [{"symbol": "SOL/USD", "qty": 0.0122504}],
        "recent_fills_sample": [
            {"trade_id": "sell", "product_id": "SOL-USD", "side": "SELL", "size": "0.0122504", "price": "81.63"},
        ],
    }
    probe_file = _write_probe(tmp_path, probe)
    report = lifecycle._build_report(probe_file)

    assert report["likely_current_sol_entry_trade_id"] is None
    assert report["likely_current_sol_entry_size"] is None


def test_eth_fills_are_counted_separately(tmp_path):
    """ETH fills must be tallied independently of SOL fills."""
    probe = {
        "broker_read_successful": True,
        "open_positions_on_broker": [],
        "recent_fills_sample": [
            {"product_id": "ETH-USD", "side": "BUY", "size": "0.1", "price": "3000"},
            {"product_id": "ETH-USD", "side": "SELL", "size": "0.05", "price": "3010"},
            {"product_id": "SOL-USD", "side": "BUY", "size": "1", "price": "80"},
        ],
    }
    probe_file = _write_probe(tmp_path, probe)
    report = lifecycle._build_report(probe_file)

    assert report["recent_eth_fills_count"] == 2
    assert report["recent_sol_fills_count"] == 1


def test_old_or_malformed_fill_rows_are_skipped_safely(tmp_path):
    """Malformed, missing side/size/price, or non-numeric rows must be ignored without crashing."""
    probe = {
        "broker_read_successful": True,
        "sol_on_broker": True,
        "open_positions_on_broker": [{"symbol": "SOL/USD", "qty": 0.0122504}],
        "recent_fills_sample": [
            {"product_id": "SOL-USD", "side": "BUY", "size": "0.0122504", "price": "81.63"},  # good
            None,
            {"product_id": "SOL-USD", "side": None, "size": "0.01"},  # bad side
            {"product_id": "SOL-USD", "side": "BUY", "size": "not-a-number", "price": "81.63"},
            {"product_id": "SOL-USD", "side": "BUY", "size": 0.01, "price": None},
        ],
    }
    probe_file = _write_probe(tmp_path, probe)
    report = lifecycle._build_report(probe_file)

    # Still finds the good one; None and malformed rows are skipped safely in grouping
    assert report["likely_current_sol_entry_size"] == 0.0122504
    assert report["recent_sol_fills_count"] == 4  # None entry dropped before grouping


def test_script_does_not_read_env_call_broker_or_mutate_forbidden_paths(tmp_path, monkeypatch):
    """The script must be pure read-only: no .env, no broker_coinbase import, no writes to logs/state/coinbase_fills, no append calls."""
    probe = {
        "broker_read_successful": True,
        "sol_on_broker": True,
        "open_positions_on_broker": [{"symbol": "SOL/USD", "qty": 0.01}],
        "recent_fills_sample": [],
    }
    probe_file = _write_probe(tmp_path, probe)

    # Tempting .env in isolated dir
    (tmp_path / ".env").write_text("COINBASE_API_KEY=NEVER_READ_ME\n")
    monkeypatch.chdir(tmp_path)

    imported = []
    import builtins
    orig = builtins.__import__

    def tracking_import(name, *a, **k):
        imported.append(name)
        return orig(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", tracking_import)

    # Also ensure no accidental writes by checking the call did not create forbidden files
    before = {p.name for p in tmp_path.iterdir()}

    report = lifecycle._build_report(probe_file)

    after = {p.name for p in tmp_path.iterdir()}

    # No broker import
    assert not any("broker_coinbase" in str(n) for n in imported), "must not import broker_coinbase"

    # No .env read (no secret leakage + no crash)
    assert "NEVER_READ_ME" not in str(report)

    # No new files created by the script (only the probe + .env we made)
    assert after == before, f"script created unexpected files: {after - before}"

    # Key safety flags
    assert report["net_pnl_available"] is False
    assert report["profit_readout"] == "unsafe_to_aggregate"
    assert report["zero_qty_journal_rows_are_excluded"] is True