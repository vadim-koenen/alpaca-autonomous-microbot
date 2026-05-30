from pathlib import Path
import importlib.util
import sys

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "coinbase_fill_logging_contract_check.py"
spec = importlib.util.spec_from_file_location("fill_contract", SCRIPT)
fill_contract = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fill_contract
spec.loader.exec_module(fill_contract)


def write_csv(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def valid_header():
    return ",".join(fill_contract.REQUIRED_COLUMNS)


def valid_row(**overrides):
    row = {
        "schema_version": "1",
        "logged_at": "2026-05-30T19:30:00Z",
        "source": "coinbase_advanced",
        "environment": "live",
        "strategy": "coinbase_exploration",
        "cycle_id": "cycle-1",
        "position_id": "pos-1",
        "client_order_id": "client-1",
        "exchange_order_id": "exchange-1",
        "product_id": "BTC-USD",
        "symbol": "BTC/USD",
        "side": "buy",
        "order_type": "limit",
        "order_status": "filled",
        "fill_status": "filled",
        "filled_size": "0.00001",
        "average_filled_price": "100000",
        "gross_quote_value": "1.00",
        "fee_amount": "0.006",
        "fee_currency": "USD",
        "net_quote_value": "1.006",
        "created_at": "2026-05-30T19:29:30Z",
        "filled_at": "2026-05-30T19:30:00Z",
        "raw_event_type": "order_fill",
        "notes": "",
    }
    row.update(overrides)
    return ",".join(row[column] for column in fill_contract.REQUIRED_COLUMNS)


def test_missing_fill_log_is_advisory(tmp_path):
    result = fill_contract.validate_fill_log(tmp_path / "logs" / "coinbase_fills.csv")
    assert result.status == "MISSING"
    assert result.row_count == 0
    assert "Fill log does not exist yet" in result.warnings[0]


def test_empty_file_fails_contract(tmp_path):
    path = tmp_path / "logs" / "coinbase_fills.csv"
    path.parent.mkdir(parents=True)
    path.write_text("", encoding="utf-8")

    result = fill_contract.validate_fill_log(path)
    assert result.status == "FAIL"
    assert "schema_version" in result.missing_columns


def test_valid_fill_log_passes(tmp_path):
    path = tmp_path / "logs" / "coinbase_fills.csv"
    write_csv(path, valid_header() + "\n" + valid_row())

    result = fill_contract.validate_fill_log(path)
    assert result.status == "PASS"
    assert result.row_count == 1
    assert result.errors == ()


def test_missing_required_column_fails(tmp_path):
    columns = [column for column in fill_contract.REQUIRED_COLUMNS if column != "fee_amount"]
    path = tmp_path / "logs" / "coinbase_fills.csv"
    write_csv(path, ",".join(columns) + "\n" + ",".join("x" for _ in columns))

    result = fill_contract.validate_fill_log(path)
    assert result.status == "FAIL"
    assert "fee_amount" in result.missing_columns


def test_invalid_side_fails(tmp_path):
    path = tmp_path / "logs" / "coinbase_fills.csv"
    write_csv(path, valid_header() + "\n" + valid_row(side="hold"))

    result = fill_contract.validate_fill_log(path)
    assert result.status == "FAIL"
    assert any("invalid side" in error for error in result.errors)


def test_invalid_numeric_field_fails(tmp_path):
    path = tmp_path / "logs" / "coinbase_fills.csv"
    write_csv(path, valid_header() + "\n" + valid_row(fee_amount="not-a-number"))

    result = fill_contract.validate_fill_log(path)
    assert result.status == "FAIL"
    assert any("invalid numeric field fee_amount" in error for error in result.errors)


def test_missing_order_ids_fails(tmp_path):
    path = tmp_path / "logs" / "coinbase_fills.csv"
    write_csv(path, valid_header() + "\n" + valid_row(client_order_id="", exchange_order_id=""))

    result = fill_contract.validate_fill_log(path)
    assert result.status == "FAIL"
    assert any("missing both exchange_order_id and client_order_id" in error for error in result.errors)


def test_missing_cycle_id_warns_but_passes(tmp_path):
    path = tmp_path / "logs" / "coinbase_fills.csv"
    write_csv(path, valid_header() + "\n" + valid_row(cycle_id=""))

    result = fill_contract.validate_fill_log(path)
    assert result.status == "PASS"
    assert any("missing cycle_id" in warning for warning in result.warnings)


def test_strict_missing_returns_zero(tmp_path):
    code = fill_contract.main(["--path", str(tmp_path / "logs" / "coinbase_fills.csv"), "--strict"])
    assert code == 0


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
        "os.environ",
        "subprocess",
    ]
    for token in forbidden:
        assert token not in text
