# Coinbase Sizing / Execution / Profitability Reconciliation Runbook — P2-006

ADVISORY ONLY. This report is read-only and must not be used to place, cancel, modify, or size live orders.

## Purpose

This report explains why Coinbase controlled-exploration transactions may look like they are canceling themselves out. It reconstructs completed buy/sell cycles from local journal data, attaches P2-003 price-path MFE/MAE data when available, and prints a fee-adjusted profitability summary.

The report is designed to answer:

- Why was a `$0.50` or `$1.00` notional used?
- Which sizing cap won?
- Did the position ever move far enough intra-hold to beat maker/taker break-even?
- Was the exit max-hold, take-profit, stop-loss, or unknown?
- What was gross P/L, fee drag, and net P/L?
- Which symbols are least bad or potentially promising?
- Is any future Class 2 tuning justified yet?

## Safety

Do not use this report to change live trading behavior directly.

This report does not:

- call Coinbase or Alpaca APIs
- read `.env`
- restart bots
- run `launchctl`
- place/cancel/modify orders
- modify configs, state, runtime, or logs
- import broker, order, risk, or main runtime modules
- connect prediction features to live trading

## Files read

Default paths:

```bash
config_coinbase_crypto.yaml
journal_coinbase_crypto.csv
logs/coinbase_price_path.csv
```

Only local files are read. Missing or empty files are tolerated.

## Run

```bash
python3 scripts/coinbase_sizing_execution_reconciliation_report.py
```

Optional explicit paths:

```bash
python3 scripts/coinbase_sizing_execution_reconciliation_report.py \
  --config config_coinbase_crypto.yaml \
  --journal journal_coinbase_crypto.csv \
  --price-path logs/coinbase_price_path.csv
```

## Validate

```bash
python3 -m py_compile scripts/coinbase_sizing_execution_reconciliation_report.py
python3 -m pytest tests/test_coinbase_sizing_execution_reconciliation_report.py -q
python3 scripts/coinbase_sizing_execution_reconciliation_report.py
```

## Interpreting the output

### Configuration snapshot

Confirms the current controlled-exploration cap stack. Current behavior should be interpreted as fixed-cap controlled exploration, not uncapped adaptive sizing.

### Trade-cycle reconstruction

Pairs recognized buy rows with later sell rows by symbol. The sell notional is treated as the close of the bought position quantity, not an independent variable sell decision.

### Fee-adjusted profitability

Shows the gap between gross move and net move after fees. At `$1.00` notional, fee drag can dominate tiny price moves.

### Symbol summary

Classifies each symbol conservatively as promising, inconclusive, or avoid for now based on limited evidence. Small samples should remain inconclusive.

### Decision gate

The report must keep Class 2 changes blocked when there are fewer than 20 completed paths, fewer than roughly 14 days of data, or no positive fee-adjusted expectancy.

## Current expected posture

Until enough evidence is collected:

- no notional increase
- no TP/SL/hold-time tuning
- no max-open-position increase
- no prediction-to-live wiring
- no paper-to-live promotion

Use this report to decide what should be tested in paper/shadow mode next, not to modify live risk directly.
