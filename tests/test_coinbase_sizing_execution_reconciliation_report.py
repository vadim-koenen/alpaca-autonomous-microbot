# ADVISORY ONLY — tests for read-only diagnostics, no live trading calls.
from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'coinbase_sizing_execution_reconciliation_report.py'
spec = importlib.util.spec_from_file_location('coinbase_sizing_execution_reconciliation_report', MODULE_PATH)
report = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = report
assert spec.loader is not None
spec.loader.exec_module(report)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text('', encoding='utf-8')
        return
    with path.open('w', encoding='utf-8', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_config(path: Path) -> None:
    path.write_text(
        '''
account:
  expected_starting_equity: 40.00
controlled_exploration:
  max_single_trade_notional_usd: 1.00
  max_total_exploration_exposure_usd: 6.00
  max_open_positions: 2
coinbase_probe_notional_usd: 0.50
dynamic_sizing:
  position_size_pct: 2.5
  min_notional_usd: 1.00
  max_notional_usd: 25.00
  scaling_threshold_usd: 20.00
fees:
  maker_fee_pct: 0.006
  taker_fee_pct: 0.012
''',
        encoding='utf-8',
    )


def sample_journal(path: Path) -> None:
    write_csv(
        path,
        [
            {
                'timestamp': '2026-05-30T10:00:00Z',
                'symbol': 'BTC/USD',
                'side': 'buy',
                'quantity': '0.00001',
                'price': '100000',
                'notional': '1.00',
                'fee_usd': '0.006',
                'reason': 'controlled_exploration_entry',
            },
            {
                'timestamp': '2026-05-30T11:30:00Z',
                'symbol': 'BTC/USD',
                'side': 'sell',
                'quantity': '0.00001',
                'price': '100500',
                'notional': '1.005',
                'fee_usd': '0.00603',
                'reason': 'max_hold_exit',
            },
        ],
    )


def sample_price_path(path: Path) -> None:
    write_csv(
        path,
        [
            {
                'timestamp_utc': '2026-05-30T10:15:00Z',
                'symbol': 'BTC/USD',
                'position_id': 'BTC-1',
                'entry_timestamp': '2026-05-30T10:00:00+00:00',
                'entry_price': '100000',
                'current_price': '100700',
                'unrealized_pct': '0.70',
                'hold_minutes': '15',
            },
            {
                'timestamp_utc': '2026-05-30T10:45:00Z',
                'symbol': 'BTC/USD',
                'position_id': 'BTC-1',
                'entry_timestamp': '2026-05-30T10:00:00+00:00',
                'entry_price': '100000',
                'current_price': '99700',
                'unrealized_pct': '-0.30',
                'hold_minutes': '45',
            },
            {
                'timestamp_utc': '2026-05-30T11:00:00Z',
                'symbol': 'BTC/USD',
                'position_id': 'BTC-1',
                'entry_timestamp': '2026-05-30T10:00:00+00:00',
                'entry_price': '100000',
                'current_price': '101300',
                'unrealized_pct': '1.30',
                'hold_minutes': '60',
            },
        ],
    )


def test_missing_journal_is_tolerated(tmp_path):
    config = tmp_path / 'config.yaml'
    write_config(config)
    output = report.build_report(config, tmp_path / 'missing.csv', tmp_path / 'missing_path.csv')
    assert 'Journal warning: missing:' in output
    assert 'Completed cycles: 0' in output


def test_empty_journal_is_tolerated(tmp_path):
    config = tmp_path / 'config.yaml'
    journal = tmp_path / 'journal.csv'
    price_path = tmp_path / 'path.csv'
    write_config(config)
    write_csv(journal, [])
    write_csv(price_path, [])
    output = report.build_report(config, journal, price_path)
    assert 'no recognized buy/sell rows' in output
    assert 'Completed cycles: 0' in output


def test_missing_price_path_is_tolerated(tmp_path):
    config = tmp_path / 'config.yaml'
    journal = tmp_path / 'journal.csv'
    write_config(config)
    sample_journal(journal)
    output = report.build_report(config, journal, tmp_path / 'missing_path.csv')
    assert 'Price-path warning: missing:' in output
    assert 'Cycle 1: BTC/USD' in output


def test_one_completed_cycle_gross_fee_net(tmp_path):
    config = tmp_path / 'config.yaml'
    journal = tmp_path / 'journal.csv'
    price_path = tmp_path / 'path.csv'
    write_config(config)
    sample_journal(journal)
    write_csv(price_path, [])
    output = report.build_report(config, journal, price_path)
    assert 'Entry notional: $1.0000 | Exit notional: $1.0050' in output
    assert 'Gross P/L: $0.0050 | Fees: $0.0120 | Net P/L: $-0.0070' in output


def test_max_hold_classification(tmp_path):
    config = tmp_path / 'config.yaml'
    journal = tmp_path / 'journal.csv'
    write_config(config)
    sample_journal(journal)
    output = report.build_report(config, journal, tmp_path / 'missing.csv')
    assert 'Exit kind: max_hold | Max-hold exit: yes' in output
    assert 'Max-hold exits: 1' in output


def test_symbol_summary_present(tmp_path):
    config = tmp_path / 'config.yaml'
    journal = tmp_path / 'journal.csv'
    write_config(config)
    sample_journal(journal)
    output = report.build_report(config, journal, tmp_path / 'missing.csv')
    assert 'BTC/USD: cycles=1' in output
    assert 'status=inconclusive' in output


def test_threshold_crossing_merge_with_price_path(tmp_path):
    config = tmp_path / 'config.yaml'
    journal = tmp_path / 'journal.csv'
    path = tmp_path / 'logs' / 'coinbase_price_path.csv'
    write_config(config)
    sample_journal(journal)
    sample_price_path(path)
    output = report.build_report(config, journal, path)
    assert 'MFE: +1.300%' in output
    assert 'MAE: -0.300%' in output
    assert '+0.60%=yes at 15.0m' in output
    assert '+1.20%=yes at 60.0m' in output


def test_dynamic_sizing_explanation_hard_cap_wins(tmp_path):
    config = tmp_path / 'config.yaml'
    journal = tmp_path / 'journal.csv'
    write_config(config)
    sample_journal(journal)
    output = report.build_report(config, journal, tmp_path / 'missing.csv')
    assert 'Dynamic theoretical: $1.0000' in output
    assert 'Limiting factor: controlled_exploration.max_single_trade_notional_usd' in output
    assert 'Current behavior is fixed-cap controlled exploration' in output


def test_decision_gate_blocks_with_small_sample(tmp_path):
    config = tmp_path / 'config.yaml'
    journal = tmp_path / 'journal.csv'
    write_config(config)
    sample_journal(journal)
    output = report.build_report(config, journal, tmp_path / 'missing.csv')
    assert 'Class 2 tuning: BLOCKED' in output
    assert 'Notional increase: BLOCKED' in output
    assert 'Prediction/betting: SHADOW ONLY' in output


def test_reconstructs_notional_from_quantity_price(tmp_path):
    config = tmp_path / 'config.yaml'
    journal = tmp_path / 'journal.csv'
    write_config(config)
    write_csv(
        journal,
        [
            {'timestamp': '2026-05-30T10:00:00Z', 'symbol': 'ETH/USD', 'side': 'buy', 'quantity': '0.01', 'price': '100', 'fee_usd': '0.01', 'reason': 'entry'},
            {'timestamp': '2026-05-30T10:10:00Z', 'symbol': 'ETH/USD', 'side': 'sell', 'quantity': '0.01', 'price': '101', 'fee_usd': '0.01', 'reason': 'tp'},
        ],
    )
    output = report.build_report(config, journal, tmp_path / 'missing.csv')
    assert 'Entry notional: $1.0000 | Exit notional: $1.0100' in output
    assert 'Exit kind: take_profit' in output


def test_forbidden_live_imports_absent():
    source = MODULE_PATH.read_text(encoding='utf-8')
    forbidden_patterns = [
        'import broker',
        'from broker',
        'import order_manager',
        'from order_manager',
        'import risk_manager',
        'from risk_manager',
        'from main import',
        'import main',
    ]
    for pattern in forbidden_patterns:
        assert pattern not in source
