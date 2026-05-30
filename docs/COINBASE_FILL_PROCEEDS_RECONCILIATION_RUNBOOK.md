# Coinbase Fill / Proceeds Reconciliation Runbook

## Purpose

P2-007 is an advisory-only, read-only diagnostic patch.

It checks whether local files contain enough Coinbase fill/proceeds evidence to safely reconstruct realized gross and net P/L. It exists because prior reconciliation showed that exit rows may confirm exits while still lacking actual sell proceeds.

## Safety classification

Class 1: advisory/read-only.

This patch does not:

- call Coinbase APIs
- read `.env`
- place, cancel, or modify orders
- restart bots
- run `launchctl`
- edit config files
- change risk caps
- touch `state/`, `runtime/`, or `launchd/`
- connect predictions to live trading

## Files inspected

The report intentionally limits itself to local CSVs in:

- `journal_coinbase_crypto.csv`
- `logs/`
- `reports/`

It does not scan secrets, runtime state, broker modules, or live API endpoints.

## Run

`python3 scripts/coinbase_fill_proceeds_reconciliation_report.py`

Optional root override:

`python3 scripts/coinbase_fill_proceeds_reconciliation_report.py --root /path/to/repo`

## Validate

`python3 -m py_compile scripts/coinbase_fill_proceeds_reconciliation_report.py`

`python3 -m pytest tests/test_coinbase_fill_proceeds_reconciliation_report.py -q`

`python3 scripts/coinbase_fill_proceeds_reconciliation_report.py`

## What the report answers

1. Which local CSV files contain Coinbase buy/sell/fill-like rows.
2. Whether entry rows include buy cost or notional.
3. Whether exit rows include direct sell proceeds.
4. Whether fees are available for net P/L.
5. Whether rows can be paired by strategy/cycle/order identifiers.
6. Whether fallback symbol/time FIFO pairing is possible.
7. Which rows lack required fields.
8. Whether actual gross or net P/L can be reconstructed safely.

## Interpretation

If an exit row lacks direct proceeds, realized P/L must remain unavailable for that cycle.

Do not infer realized P/L from exit intent alone.

A safe realized net P/L cycle requires:

- entry buy cost / notional
- exit sell proceeds
- fee fields
- enough identifiers or timestamps to pair entry and exit

A safe realized gross P/L cycle requires:

- entry buy cost / notional
- exit sell proceeds
- enough identifiers or timestamps to pair entry and exit

## Expected next step after P2-007

If proceeds are still missing, the likely later fix is a logging patch that writes one immutable Coinbase fill record with:

- order ID
- client order ID
- product ID / symbol
- side
- status
- filled size
- average filled price
- gross quote value / proceeds
- fee
- created timestamp
- filled timestamp
- strategy position or cycle ID

Do not use this report to tune notional, TP/SL, hold time, or prediction-to-live behavior.
