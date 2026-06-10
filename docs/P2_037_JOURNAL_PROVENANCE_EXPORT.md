# P2-037 Journal Provenance / Closed-Trade Export Diagnostic

## Purpose

P2-037 introduces a read-only utility to parse the bot's historical, append-only CSV journal files and export their closed-trade lifecycle records into normalized JSON files.

These normalized JSON exports can then be natively read by the P2-036 timeout-exit economic diagnostic script, allowing it to produce real, factual economic reports about historical live trading behavior.

## Scope

The script exclusively searches the local repository for matching `*journal*.csv` files, parses their rows to identify filled entries and their eventual exits, pairs these events logically, and exports JSON representations of the closed trades. 

It does not:
- Place, cancel, or modify orders
- Communicate with broker APIs
- Read or manipulate `.env` files or secrets
- Touch the `STOP_TRADING` killswitch
- Restart the bot process

## Usage

```bash
python3 scripts/p2_037_journal_provenance_export.py
```

The script will:
1. Search local paths for `*journal*.csv` files (e.g. `journal.csv`, `journal_coinbase_crypto.csv`, etc).
2. Print a provenance summary outlining which paths were scanned, schemas found, and closed trades extracted.
3. Write exported files to `reports/journals/export_<source>.json`.

## No-Data Behavior

If no CSV files are found, or if no closed trades exist in the found files, the script exits cleanly and reports 0 exported records. A no-data report is printed to standard output.

## Exported JSON Schema

The P2-036 diagnostic script expects the exported trades to follow this schema:
```json
{
    "entry_time": "2026-05-25T14:26:07.625Z",
    "exit_time": "2026-05-25T15:56:07.625Z",
    "exit_reason": "max hold time 90min exceeded (90.0min held)",
    "gross_pnl": 0.0015,
    "net_pnl": -0.0200,
    "fees": 0.0215,
    "symbol": "ALGO/USD",
    "qty": 16.21,
    "entry_price": 0.1144,
    "exit_price": 0.1145
}
```
