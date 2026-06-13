# P2-041B Offline No-Trade Baseline Replay Harness

## Definition
The **no-trade baseline** represents the outcome of performing exactly zero trades over the backtest window.

## Requirement
Every candidate strategy must produce a strictly positive net profit-and-loss (PNL) after all fees and slippage are applied, beating this no-trade baseline. Strategies that lose money or merely break even after fees are inherently inferior to doing nothing.

## Baseline Metrics
* **trades**: 0
* **gross_pnl**: $0.00
* **fees**: $0.00
* **net_pnl**: $0.00

## Constraints
* The baseline simulation does **not** fetch data.
* It does **not** rely on the physical presence of `/tmp` market data files.
* It does **not** touch live configuration or mutate broker states.
* It inherently guarantees no ML training takes place (`ML_TRAINING_STARTED=false`).

## Next Steps
This baseline output will be fed directly into the `P2-041D` fee/slippage scoring layer to evaluate offline replay candidate strategies.
