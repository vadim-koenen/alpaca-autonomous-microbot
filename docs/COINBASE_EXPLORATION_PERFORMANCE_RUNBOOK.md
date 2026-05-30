# Coinbase Exploration Performance Runbook

## Overview

The **Coinbase Exploration Performance Report** is a read-only advisory tool that analyzes controlled exploration trades executed on Coinbase. It answers the critical question:

> **Can $1.00 trades overcome Coinbase fee drag?**

This runbook explains how to use the report and interpret its results.

## Quick Start

### Run the Report

```bash
python3 scripts/coinbase_exploration_performance_report.py
```

Output will print to stdout. Optionally save to a file:

```bash
python3 scripts/coinbase_exploration_performance_report.py > reports/exploration_report_$(date +%Y-%m-%d).txt
```

### Run Tests

```bash
python3 -m pytest tests/test_coinbase_exploration_performance_report.py -v
```

### Validate Script

```bash
python3 -m py_compile scripts/coinbase_exploration_performance_report.py
```

## Data Sources (Priority Order)

The report searches for journal data in this order:

1. **`logs/coinbase_journal.csv`** — Coinbase-specific journal
2. **`state/coinbase/journal.csv`** — Broker state
3. **`journal.csv`** — Root journal (fallback)

If none exist, the report will output an error. Ensure the bot has run and recorded at least one controlled exploration trade.

## Report Sections

### 1. Summary

Provides the highest-level metrics:

- **Gross win rate** — Percentage of trades with positive P/L before fees
- **Net win rate** — Percentage of trades with positive P/L after fees
- **Total gross P/L** — Sum of all gross gains/losses
- **Total estimated fees** — Sum of Coinbase execution fees
- **Total net P/L** — Sum of net gains/losses
- **Average gross/net per trade** — Mean P/L metrics

**Interpretation:**
- If **net win rate < gross win rate**, fee drag is reducing profitability.
- If **average net per trade is negative**, the strategy is currently learning-mode only.

### 2. By Symbol

Breaks down performance by symbol (BTC/USD, ETH/USD, SOL/USD, etc.):

- **Trade count** — Number of round trips for this symbol
- **Gross/Net P/L** — Aggregate and fee-adjusted P/L
- **Win rates** — Percentage of profitable trades
- **Average net per trade** — Mean net P/L

**Interpretation:**
- Symbols with high average net per trade are candidates for increased position size.
- Symbols with negative average net should be investigated for signal quality.

### 3. Exit Type Distribution

Categorizes exits by how the position was closed:

- **max_hold** — Exited after max hold time (90 min default)
- **stop_loss** — Exited due to stop-loss trigger
- **take_profit** — Exited due to take-profit threshold
- **unknown** — Reason not parsed

**Interpretation:**
- If **all exits are max_hold**, stop-loss and take-profit mechanics are not participating. Consider:
  - Reviewing stop/take-profit thresholds
  - Checking if conditions are ever met
- Exit types with negative average net should be reviewed.

### 4. Fee Breakeven Analysis

Compares average fee per trade to average gross move:

- **Average fee per trade** — Mean of fees paid per round trip
- **Minimum gross move needed** — Equals the average fee (threshold to break even)
- **Average actual gross move** — Actual mean gross P/L
- **Status** — Whether breakeven is viable

**Interpretation:**
- If **Status = ✓ Breakeven viable**, gross move exceeds average fee.
- If **Status = ✗ Below breakeven**, average gross move does not cover fees. This suggests:
  - Entry/exit quality needs improvement
  - Spread slippage is high
  - Fee structure may be disadvantageous

### 5. Regime Breakdown (if available)

If regime labels exist in the journal, performance is split by market regime:

- **dead_chop** — Choppy/sideways market
- **range** — Ranging behavior
- **uptrend** — Upward trending market
- **downtrend** — Downward trending market

**Interpretation:**
- Some regimes may have positive average net; others negative.
- Focus exploration improvements on low-performing regimes.

### 6. Warnings & Diagnostics

Two key warnings:

**Warning 1: Negative Net P/L**
```
⚠ Net P/L is negative. Exploration is useful for learning but NOT YET PROFITABLE.
```
This means the strategy is not yet ready for capital allocation. Continue development.

**Warning 2: All Max-Hold Exits**
```
⚠ All exits are max_hold. Stop-loss/take-profit thresholds are NOT PARTICIPATING.
```
This means the configured stops and targets are never being hit. Review parameters.

**No Issues**
```
✓ No issues detected.
```
Strategy is learning-mode profitable or performing well.

## Interpretation Guide

### Scenario 1: Negative Net P/L

```
Total net P/L: $-0.45
Average net/trade: $-0.005
```

**Action:**
- Exploration is in learning mode. Not yet ready for live capital.
- Review entry/exit signal quality in strategy_crypto.py.
- Check if regime detection is working.
- Consider tightening entry confidence thresholds.

### Scenario 2: Positive Gross, Negative Net

```
Total gross P/L: $0.30
Total estimated fees: $0.50
Total net P/L: $-0.20
```

**Action:**
- Fee drag is eating profits. Entry/exit execution needs improvement.
- Check fill slippage vs bid-ask spread.
- Consider whether $1.00 notional is too small for the bid-ask spread.
- Evaluate Coinbase fee tier (maker vs taker).

### Scenario 3: Positive Net P/L

```
Total net P/L: $0.15
Average net/trade: $0.002
Breakeven viable: ✓
```

**Action:**
- Exploration is learning-mode profitable!
- Monitor for consistency over more trades.
- Consider small live allocation if metrics remain stable.
- Scale gradually.

## Constraints & Safety

✓ **Read-only** — No trades are placed or modified.
✓ **No broker imports** — No live account state is accessed.
✓ **No secrets** — No .env is read, no credentials used.
✓ **No mutations** — Runtime state and live config are unchanged.
✓ **Advisory only** — Report is informational; no automation triggered.

## Testing

The report includes comprehensive tests:

```bash
python3 -m pytest tests/test_coinbase_exploration_performance_report.py -q
```

Tests cover:

- Fee reconstruction math
- Gross/net P/L calculation
- Breakeven threshold calculation
- Exit type classification (max_hold, stop_loss, take_profit)
- Empty/no-data handling
- Report structure and content

## Common Issues

### No Journal Found

```
ERROR: Could not load journal
```

**Solution:**
- Check that `journal.csv`, `logs/coinbase_journal.csv`, or `state/coinbase/journal.csv` exists.
- Ensure the bot has run at least one controlled exploration cycle.
- Run: `ls -la journal*.csv logs/coinbase*.csv state/coinbase/journal.csv`

### Empty Journal

```
No controlled_exploration trades found
```

**Solution:**
- No trades with `strategy='controlled_exploration'` exist yet.
- Check that controlled exploration is enabled: `config_coinbase_crypto.yaml`
- Check that the bot has been running long enough to propose trades.
- Monitor `logs/coinbase.launchd.out.log` for exploration proposal logs.

### Import Errors

```
ModuleNotFoundError: No module named 'pandas'
```

**Solution:**
```bash
pip install pandas
# or
pip install -r requirements.txt
```

## Next Steps

Once you have a solid report showing **positive net P/L and breakeven viable**:

1. **Increase trade size** — Bump `max_single_trade_notional_usd` from $1.00 to $2.00–$5.00
2. **Tighten entry filters** — Adjust `min_confidence_to_trade` if signal quality allows
3. **Review regime thresholds** — Ensure regime labels match market conditions
4. **Monitor for consistency** — Run the report weekly; ensure metrics stay stable
5. **Expand symbols** — Add additional symbols to `approved_symbols` if current ones succeed

If metrics degrade:

- Revert to $1.00 notional
- Review entry/exit signal quality
- Check Coinbase API status and fee changes
- Consider market structure changes (vol, spreads)

## Support

For detailed logs, check:

```bash
tail -f logs/coinbase.launchd.out.log
```

For journal inspection:

```bash
head -20 journal.csv | cut -d',' -f1-15
```

Questions? Refer to `BOT_EVALUATION_FOR_AI.md` or check recent session logs.
