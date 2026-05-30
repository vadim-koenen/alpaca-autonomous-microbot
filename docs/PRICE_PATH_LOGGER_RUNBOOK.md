# ADVISORY ONLY — read-only analysis, no live trading calls.
# Do not import from: broker, order_manager, risk_manager, main.

# Coinbase Intra-Hold Price Path Logger Runbook — P2-003

## Overview
The Intra-Hold Price Path Logger (`scripts/coinbase_price_path_logger.py`) is a Class 1 advisory tool designed to capture real-time price snapshots for open `coinbase_exploration` positions. 

By logging prices every 60 seconds, this tool enables the calculation of true Maximum Favorable Excursion (MFE) and Maximum Adverse Excursion (MAE). This data is critical for statistically grounding future Class 2 tuning of Stop-Loss (SL) and Take-Profit (TP) thresholds.

## How It Works
1. **State Inspection**: Reads `state/coinbase/open_positions.json` to find active exploration trades.
2. **Public API Fetch**: For each trade, fetches the current spot price from Coinbase's public (unauthenticated) REST API.
3. **Metrics Calculation**: Computes `unrealized_pct` and current `hold_minutes`.
4. **Data Persistence**: Appends a row to `logs/coinbase_price_path.csv`.

## Manual Execution
To run a single snapshot:
```bash
python3 scripts/coinbase_price_path_logger.py
```

## Launchd Installation (Manual Step)
Once approved and committed, the logger should be installed as a background service:
```bash
# 1. Copy the plist
cp launchd/com.vadim.price-path-logger.plist ~/Library/LaunchAgents/

# 2. Load the agent
launchctl load ~/Library/LaunchAgents/com.vadim.price-path-logger.plist
```

## Monitoring
- **Main Log**: `logs/coinbase_price_path.csv` (contains the data snapshots)
- **Standard Out**: `logs/price_path_logger.out.log`
- **Standard Error**: `logs/price_path_logger.err.log`

## Troubleshooting
- **No data in CSV**: Ensure there are open positions with `strategy: "coinbase_exploration"` in `state/coinbase/open_positions.json`.
- **API Errors**: Check `logs/price_path_logger.out.log` for network or timeout warnings. The logger uses public endpoints and does not require API keys.

## Safety Mandates
- **Read-Only**: This tool never writes to `state/` or places orders.
- **Standalone**: It does not import from core bot modules.
- **Rate-Limited**: The 60-second interval is well within Coinbase public API limits.

---
**Last Updated**: 2026-05-30
**Status**: ACTIVE — Data collection in progress.
