# ADVISORY ONLY — tests for the fill payload field discovery script (P2-017C)

from pathlib import Path
import importlib.util
import sys
import json
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "coinbase_fill_payload_field_discovery.py"
spec = importlib.util.spec_from_file_location("discovery", SCRIPT)
discovery = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = discovery
spec.loader.exec_module(discovery)


def _write_probe(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "probe.json"
    p.write_text(json.dumps(payload))
    return p


TARGET = "1f10a7cb-3fe5-4cbb-b990-f74c39529fc9"


def test_matched_trade_found_by_trade_id(tmp_path):
    probe = {
        "broker_read_successful": True,
        "recent_fills_sample": [
            {"trade_id": TARGET, "product_id": "SOL-USD", "side": "BUY", "size": "0.0122504", "price": "81.63", "fee": None, "filled_value": None},
            {"trade_id": "other", "product_id": "ETH-USD", "side": "SELL", "size": "0.1", "price": "3000", "fee": 1.23, "filled_value": 300.5},
        ],
    }
    probe_file = _write_probe(tmp_path, probe)
    report = discovery._build_report(probe_file)

    assert report["matched_trade_found"] is True
    assert report["matched_trade_fee_non_null"] is False
    assert report["matched_trade_filled_value_non_null"] is False
    assert report["net_pnl_available"] is False
    assert report["discovery_status"] == "matched_trade_found_but_fee_and_value_missing"


def test_fee_and_filled_value_present_but_null_are_unavailable(tmp_path):
    probe = {
        "broker_read_successful": True,
        "recent_fills_sample": [
            {"trade_id": TARGET, "product_id": "SOL-USD", "side": "BUY", "fee": None, "filled_value": None},
        ],
    }
    probe_file = _write_probe(tmp_path, probe)
    report = discovery._build_report(probe_file)

    assert report["matched_trade_fee_present"] is True
    assert report["matched_trade_fee_non_null"] is False
    assert report["matched_trade_filled_value_present"] is True
    assert report["matched_trade_filled_value_non_null"] is False
    assert report["net_pnl_available"] is False


def test_missing_fee_filled_value_fields_treated_as_unavailable(tmp_path):
    probe = {
        "broker_read_successful": True,
        "recent_fills_sample": [
            {"trade_id": TARGET, "product_id": "SOL-USD", "side": "BUY", "size": "0.01", "price": "80"},
            # no fee or filled_value keys at all
        ],
    }
    probe_file = _write_probe(tmp_path, probe)
    report = discovery._build_report(probe_file)

    assert report["matched_trade_fee_present"] is False
    assert report["matched_trade_filled_value_present"] is False


def test_nested_candidate_fields_are_detected(tmp_path):
    probe = {
        "broker_read_successful": True,
        "recent_fills_sample": [
            {
                "trade_id": TARGET,
                "product_id": "SOL-USD",
                "fee": None,
                "commission": {"amount": 0.01, "currency": "USD"},  # nested
                "filled_value": None,
                "details": {"proceeds": 1.02, "order": {"id": "ord_123"}},
            }
        ],
    }
    probe_file = _write_probe(tmp_path, probe)
    report = discovery._build_report(probe_file)

    assert any("commission" in f for f in report["candidate_fee_fields"])
    assert any("proceeds" in f for f in report["candidate_value_fields"])
    assert any("order" in f.lower() for f in report["candidate_order_id_fields"])


def test_order_id_candidate_fields_are_detected(tmp_path):
    probe = {
        "broker_read_successful": True,
        "recent_fills_sample": [
            {"trade_id": TARGET, "product_id": "SOL-USD", "order_id": "abc-123", "client_order_id": "cli-999"},
        ],
    }
    probe_file = _write_probe(tmp_path, probe)
    report = discovery._build_report(probe_file)

    assert report["matched_trade_order_id_present"] is True
    assert len(report["candidate_order_id_fields"]) > 0


def test_eth_and_sol_products_are_counted(tmp_path):
    probe = {
        "broker_read_successful": True,
        "recent_fills_sample": [
            {"product_id": "SOL-USD"},
            {"product_id": "ETH-USD"},
            {"product_id": "ETH-USD"},
        ],
    }
    probe_file = _write_probe(tmp_path, probe)
    report = discovery._build_report(probe_file)

    assert "SOL/USD" in report["products_seen"]
    assert "ETH/USD" in report["products_seen"]
    assert len(report["products_seen"]) == 2


def test_script_does_not_read_env_call_broker_or_mutate(tmp_path, monkeypatch):
    probe = {
        "broker_read_successful": True,
        "recent_fills_sample": [{"trade_id": TARGET, "product_id": "SOL-USD", "fee": None, "filled_value": None}],
    }
    probe_file = _write_probe(tmp_path, probe)

    (tmp_path / ".env").write_text("COINBASE_API_KEY=NEVER_READ\n")
    monkeypatch.chdir(tmp_path)

    imported = []
    import builtins
    orig = builtins.__import__

    def tracking_import(name, *a, **k):
        imported.append(name)
        return orig(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", tracking_import)

    before = {p.name for p in tmp_path.iterdir()}
    report = discovery._build_report(probe_file)
    after = {p.name for p in tmp_path.iterdir()}

    assert not any("broker_coinbase" in str(n) for n in imported)
    assert "NEVER_READ" not in str(report)
    assert after == before  # no files created by the script

    assert report["net_pnl_available"] is False
    assert report["profit_readout"] == "unsafe_to_aggregate"