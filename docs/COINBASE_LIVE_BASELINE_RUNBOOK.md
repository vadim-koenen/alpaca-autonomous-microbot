# ADVISORY ONLY — read-only analysis, no live trading calls.
# Do not import from: broker, order_manager, risk_manager, main.

# Coinbase Live-Only Baseline Report Runbook — P2-001H

## Overview

The Coinbase Live-Only Baseline Report (`scripts/coinbase_live_baseline_report.py`) is a read-only diagnostic tool that provides a clean performance baseline for the `coinbase_exploration` strategy.

It strictly filters out data that contaminates high-fidelity performance metrics:
- **Excludes `dry_run`**: Only real capital trades are analyzed.
- **Excludes non-exploration symbols**: Only BTC/USD, ETH/USD, and SOL/USD are included.
- **Excludes `coinbase_probe`**: Removes early low-confidence probe trades.
- **Excludes `recovered` positions**: Removes positions adopted after bot restarts where exact entry context might be missing.

---

## Quick Start

```bash
# 1. Run the baseline report
python3 scripts/coinbase_live_baseline_report.py

# 2. Run unit tests
python3 -m pytest tests/test_coinbase_live_baseline_report.py -v

# 3. Validate syntax
python3 -m py_compile scripts/coinbase_live_baseline_report.py
```

---

## What It Analyzes

### 1. Performance Summary
- Gross and Net win rates.
- Total Gross P/L vs Total Fees vs Total Net P/L.
- Average Net P/L per trade.

### 2. Exit Quality
- Distribution of exit types (`max_hold`, `stop_loss`, `take_profit`, `other`).
- Average Net P/L per exit type.
- **MFE/MAE Realized Proxy**: Price move from fill to exit.
- **Hold-Time Analysis**: Average hold duration parsed from logs.

### 3. Break-Even Comparison
- Compares realized MFE against Maker (1.2%) and Taker (2.4%) round-trip break-even targets.
- Indicates if current volatility/moves are sufficient to overcome fee drag.

### 4. Per-Symbol Baseline
- Clean win rate and average net percentage per symbol.
- Identifies if one symbol is performing materially better in a live environment.

---

## Interpretation Guide

- **Expectancy < 0**: If the clean baseline shows negative expectancy, do not tighten TP/SL yet. Focus on entry quality or fee reduction.
- **100% Max Hold**: If all exits are time-based, your TP/SL thresholds are effectively invisible to the current market regime.
- **Max MFE > 1.2%**: If price moves in your favor by more than 1.2% on average but you are still net negative, fee drag (taker fees) is the likely primary bottleneck.

---

**Last Updated:** 2026-05-30
**Status:** ACTIVE — Performance baseline tool.
