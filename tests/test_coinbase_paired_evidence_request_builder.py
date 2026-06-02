# ADVISORY ONLY - P2-022B offline paired evidence request builder tests.
# No broker calls, no .env reads, no order activity, no state/log writes.

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "coinbase_paired_evidence_request_builder.py"
CHECKLIST_SCRIPT = ROOT / "scripts" / "coinbase_read_only_evidence_capture_checklist.py"
FIXTURE = ROOT / "tests" / "fixtures" / "coinbase_paired_evidence_request_builder" / "journal_coinbase_crypto.csv"

spec = importlib.util.spec_from_file_location("coinbase_paired_evidence_request_builder", SCRIPT)
builder = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = builder
spec.loader.exec_module(builder)

checklist_spec = importlib.util.spec_from_file_location(
    "coinbase_read_only_evidence_capture_checklist",
    CHECKLIST_SCRIPT,
)
checklist = importlib.util.module_from_spec(checklist_spec)
sys.modules[checklist_spec.name] = checklist
checklist_spec.loader.exec_module(checklist)


def _request(max_cycles: int = 8) -> dict:
    return builder.build_request(journal=FIXTURE, max_cycles=max_cycles, lookback_days=14)


def test_builds_checklist_compatible_cycles_with_entry_exit_order_ids():
    request = _request()

    assert request["request_type"] == "coinbase_paired_order_evidence_capture"
    assert request["summary"]["paired_cycles_count"] == 3
    assert len(request["cycles"]) == 3
    for cycle in request["cycles"]:
        assert cycle["product_id"] in {"BTC-USD", "ETH-USD"}
        assert cycle["order_ids"]["entry"]
        assert cycle["order_ids"]["exit"]
        assert cycle["date_window"]["start"]
        assert cycle["date_window"]["end"]
        assert cycle["source_rows"]["entry"]["row_number"]
        assert cycle["source_rows"]["exit"]["row_number"]


def test_pairs_fifo_per_symbol():
    cycles = _request()["cycles"]
    btc_cycles = [cycle for cycle in cycles if cycle["product_id"] == "BTC-USD"]

    assert [cycle["order_ids"]["entry"] for cycle in btc_cycles] == [
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
    ]
    assert [cycle["order_ids"]["exit"] for cycle in btc_cycles] == [
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    ]


def test_excludes_sol_from_profit_aggregation_request():
    request = _request()
    combined = json.dumps(request)

    assert "SOL-USD" not in combined
    assert "33333333-3333-4333-8333-333333333333" not in combined
    assert request["summary"]["excluded_profit_symbols"] == ["SOL/USD"]
    assert request["summary"]["excluded_symbol_uuid_rows"] == 1


def test_ignores_client_order_id_only_and_missing_uuid_rows():
    request = _request()
    combined = json.dumps(request)

    assert "66666666-6666-4666-8666-666666666666" not in combined
    assert "not-a-uuid" not in combined
    assert request["summary"]["ignored_client_order_id_only_rows"] == 1
    assert request["summary"]["ignored_missing_uuid_order_id_rows"] == 1


def test_ignores_manual_review_position_open_skipped_rows():
    request = _request()

    assert request["summary"]["ignored_manual_review_rows"] == 1
    assert "manual_review_position_open" not in json.dumps(request)


def test_produces_uuid_btc_eth_rows_and_respects_max_cycles():
    request = _request(max_cycles=2)

    assert request["summary"]["uuid_btc_eth_rows"] == 7
    assert request["summary"]["candidate_paired_cycles_count"] == 3
    assert request["summary"]["paired_cycles_count"] == 2
    assert len(request["cycles"]) == 2


def test_output_passes_read_only_evidence_capture_checklist(tmp_path):
    output = tmp_path / "paired_request.json"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--journal",
            str(FIXTURE),
            "--output",
            str(output),
            "--json",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    emitted = json.loads(result.stdout)
    saved = json.loads(output.read_text(encoding="utf-8"))
    report = checklist.build_checklist_report(
        saved,
        human_approved=True,
        source_path=str(output),
    )

    assert emitted == saved
    assert report["verdict"] == "READY_FOR_HUMAN_APPROVED_READ_ONLY_CAPTURE"
    assert report["missing_requirements"] == []


def test_builder_is_offline_and_writes_only_explicit_output_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("COINBASE_API_KEY=NEVER_READ\n", encoding="utf-8")
    output = tmp_path / "paired_request.json"
    before = {path.name for path in tmp_path.iterdir()}

    request = builder.build_request(journal=FIXTURE)
    builder.write_request(request, output)
    after = {path.name for path in tmp_path.iterdir()}

    assert request["safety"]["read_only_only"] is True
    assert request["safety"]["broker_calls_made"] is False
    assert request["safety"]["live_read_only_executed"] is False
    assert request["safety"]["secrets_or_env_read"] is False
    assert request["safety"]["no_order_cancel_close_modify"] is True
    assert request["safety"]["no_risk_increase"] is True
    assert request["safety"]["no_state_or_log_mutation"] is True
    assert request["safety"]["logs_coinbase_fills_written"] is False
    assert request["safety"]["append_coinbase_fill_row_activated"] is False
    assert after == before | {"paired_request.json"}


def test_no_forbidden_runtime_hooks_or_risk_expansion():
    text = SCRIPT.read_text(encoding="utf-8")
    forbidden = [
        "import broker_coinbase",
        "from broker_coinbase",
        "load_dotenv",
        "os.environ",
        "place_order(",
        "cancel_order(",
        "close_position(",
        "modify_order(",
        "submit_order(",
        "append_coinbase_fill_row(",
        "logs/coinbase_fills.csv",
        "--live-read-only",
        "max_trade_notional",
        "max_total_crypto_exposure",
        "allow_live_trading_symbols",
        "leverage",
        "margin",
        "futures",
        "perps",
        "commodities",
        "betting",
    ]

    for token in forbidden:
        assert token not in text
