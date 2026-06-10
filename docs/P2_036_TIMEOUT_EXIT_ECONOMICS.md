# P2-036 Timeout-Exit Economics / Exit-Quality Diagnostics

## Purpose

P2-036 adds a read-only advisory diagnostic for analyzing historical timeout exits, take-profit exits, stop-loss exits, trade duration, gross/net P&L, fees, and optional MFE/MAE fields when available.

This patch does not change live trading behavior.

## Scope

The diagnostic script scans local historical journal/report paths and writes a timestamped JSON report under:

reports/diagnostics/

The script is advisory-only and should be used to understand whether historical timeout exits are economically damaging before any future strategy, exit, sizing, or risk change is proposed.

## Usage

Run:

python3 scripts/p2_036_timeout_exit_diagnostics.py

Optional explicit input:

python3 scripts/p2_036_timeout_exit_diagnostics.py --input reports/journals

## Auto-discovery

The script searches local repo paths such as:

- runtime/
- reports/
- reports/journals/
- data/
- logs/

It does not call broker APIs, mutate state, touch STOP_TRADING, restart services, or read secrets.

## No-data behavior

If no journal/trade JSON files are found, the script exits cleanly and writes a no-data report with:

- no_historical_trade_data_found=true
- scanned_paths
- next_action

This is expected when historical live journal files are not present locally.

## Safety

P2-036 is read-only and advisory-only.

It must not:
- place orders
- cancel orders
- close positions
- touch STOP_TRADING
- restart live services
- touch launchctl
- touch com.vadim.price-path-logger
- read or print secrets
- change strategy, exits, sizing, assets, capital, or risk caps

## Next step

Once real journal files are available, place them under reports/journals/ or run the script with --input pointing at the exported journal location. Review the generated timeout_exit_report_*.json before proposing any future strategy or exit changes.
