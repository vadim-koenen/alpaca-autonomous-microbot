# Coinbase Sizing / Execution / Profitability Reconciliation Runbook — P2-006

ADVISORY ONLY. This report is read-only and must not place orders, cancel orders, modify config, read `.env`, restart bots, or run `launchctl`.

## Purpose

This report explains why Coinbase controlled-exploration transactions can appear to cancel themselves out.

It reconstructs local buy/sell cycles and shows:

- configured legacy probe notional
- controlled-exploration single-trade cap
- theoretical dynamic notional, where computable from config
- final observed entry notional
- limiting cap / sizing factor
- sell fill availability
- gross and net P/L when sell proceeds are available
- max-hold / stop-loss / take-profit classification
- price-path MFE/MAE data when available
- whether any Class 2 tuning gate is justified

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

## Interpretation

The report should clearly state:

- Current behavior is fixed-cap controlled exploration, not uncapped adaptive sizing.
- The controlled-exploration cap currently prevents dynamic sizing from increasing live notional.
- Sell size closes the bought position quantity; it is not independently choosing a new variable sell value.
- Missing sell fill data is not the same as a zero-dollar exit.

## Missing exit-fill handling

Some local Coinbase journal exit/status rows can confirm that a position was closed without carrying actual sell proceeds in that row.

Required behavior:

- Do not calculate `-100%` return from a missing sell fill.
- Print an exit-fill warning.
- Leave gross/net P/L and returns unavailable until actual sell proceeds are available.
- Keep the report advisory-only.

## Evidence gate

Class 2 tuning remains blocked until the project has enough evidence. The default gate is:

- at least 20 completed observed paths
- roughly 2+ weeks of P2-003 price-path data
- evidence that fee-adjusted expectancy is positive or that a paper-only what-if model shows a defensible edge
- explicit human approval

Until then:

- no notional increase
- no TP/SL change
- no hold-time change
- no prediction-to-live wiring
- no paper-to-live promotion

Use this report to decide what should be tested in paper/shadow mode next, not to modify live risk directly.
