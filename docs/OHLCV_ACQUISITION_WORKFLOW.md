# OHLCV_ACQUISITION_WORKFLOW (P2-025I)

## Why this exists
P2-025H added the local import/validate tool (dry-run default + explicit --write) and the journal-window replay report auto-scans `data/offline_ohlcv/coinbase/`.

Real journal (48 EXIT cycles) still shows 0 coverage / all skipped with "no_ohlcv_in_window" because no local OHLCV files exist for the required symbols and actual trade windows.

This workflow (planning script + optional public fetcher + docs) makes it actionable to acquire the exact files needed, safely and offline-first.

## Current journal requirements (as of P2-025H merge at 9956488)
- Required symbols (from live EXIT cycles in journal_coinbase_crypto.csv): ALGO/USD, BTC/USD, ETH/USD, SOL/USD
- Needed approximate date range: 2026-05-25 through 2026-06-03 (earliest entry ~2026-05-25T12:55, latest exit ~2026-06-03T01:31)
- Granularity target: 5m (300s)
- Target directory (for auto-discovery by replay report): `data/offline_ohlcv/coinbase/`
- Expected filenames (example):
  - ALGO-USD_5m_2026-05-25_2026-06-03.csv
  - BTC-USD_5m_2026-05-25_2026-06-03.csv
  - ETH-USD_5m_2026-05-25_2026-06-03.csv
  - SOL-USD_5m_2026-05-25_2026-06-03.csv

## Tools
- `scripts/coinbase_ohlcv_acquisition_plan.py` (always): reads journal, computes exact required symbols + window, lists missing files under data dir, emits the precise `--input ... --symbol ... --write` commands you should run after you obtain source data.
- `scripts/coinbase_ohlcv_import_validate.py` (P2-025H): the validator/normalizer you use to ingest a source CSV/JSON you obtained manually (or via the fetcher) and optionally write the canonical normalized form.
- `scripts/coinbase_public_ohlcv_fetch.py` (this patch, opt-in): public unauthenticated market-data-only fetcher using the legacy Coinbase exchange candles endpoint (https://api.exchange.coinbase.com/...). Never uses auth, keys, .env, or Advanced Trade brokerage endpoints. Default dry-run / no network; `--fetch` to actually call; `--write` to persist.

The plan script itself **never performs network** (network_enabled=false always). It only plans.

## Recommended workflow (manual by default)
1. Run the planner:
   ```bash
   python3 scripts/coinbase_ohlcv_acquisition_plan.py --json
   ```
   Note the required_symbols, start/end, missing_files, and the exact validate commands (with placeholder paths).

2. Obtain source OHLCV data for each symbol over the window:
   - Preferred: export from Coinbase web UI / Advanced Trade "export" or "download candles" for the product + dates (CSV).
   - Or use any public source / your own historical capture that matches the timestamp/open/high/low/close/volume schema.
   - Or (opt-in) use the public fetcher below.

3. Validate + write (dry-run first):
   ```bash
   python3 scripts/coinbase_ohlcv_import_validate.py --json \
     --input /path/to/your-BTC-USD.csv --symbol BTC/USD
   # then with --write to persist normalized
   python3 scripts/coinbase_ohlcv_import_validate.py --json \
     --input /path/to/your-BTC-USD.csv --symbol BTC/USD --write
   ```
   Repeat for ALGO, ETH, SOL. The tool normalizes symbol, timestamps, writes canonical CSV with headers `timestamp_utc,symbol,open,high,low,close,volume`.

4. Confirm coverage:
   ```bash
   python3 scripts/coinbase_journal_window_replay_report.py --json
   ```
   Expect cycles_with_ohlcv_window > 0, coverage_rate > 0, cycles_replayed > 0 (and/or reduced skips) for the covered windows. journal_recorded_net_pnl_sum will still reflect the known ~-1.09 loss.

## Opt-in public unauthenticated fetch (coinbase_public_ohlcv_fetch.py)
Only if you choose to use network for acquisition:

```bash
# See what it would do (no net)
python3 scripts/coinbase_public_ohlcv_fetch.py --json \
  --symbol BTC/USD --start 2026-05-25 --end 2026-06-03 --granularity 5m

# Actually fetch (public, no auth) + write normalized
python3 scripts/coinbase_public_ohlcv_fetch.py --json \
  --symbol BTC/USD --start 2026-05-25 --end 2026-06-03 --granularity 5m --fetch --write
```

- Uses only `https://api.exchange.coinbase.com/products/BTC-USD/candles?...` (market data, no credentials ever sent). Exchange public candles endpoint is preferred over Advanced Trade public candles when no auth is allowed, because the legacy Exchange historical candles endpoint supports unauthenticated requests for 5m (granularity=300) and other granularities without requiring API keys (Advanced Trade /brokerage/products/.../candles for full history typically needs authentication).
- Implements chunked fetching (safe 299-bar chunks to respect Exchange ~300 bar/request limit) with small throttle between requests for large windows (e.g. 9-day journal windows at 5m require ~9 chunks).
- No Coinbase Advanced Trade /brokerage/ endpoints.
- No API keys, no CB-ACCESS-*, never reads .env.
- Tests **always mock** the HTTP call; real network is opt-in and off by default in the script.
- After --write, the file appears in data/offline_ohlcv/coinbase/ and replay report will pick it up on next run.

Safety flags are emitted on every report: trade_permission=none, risk_increase=not_approved, scaling_allowed=false.

## File format expected by validator / auto-scan
See docs/OHLCV_LOCAL_IMPORT.md for details. In short: CSV or JSON with timestamp/open/high/low/close (volume optional); symbol column optional (overridden by --symbol).

The planner and fetcher produce/ expect names that the replay report auto-scans.

## Safety and constraints (standing)
- All tools in this workflow are offline by design except the explicit opt-in public fetcher.
- **No live trading, no orders, no --live-read-only, no broker clients.**
- **Never read .env or secrets.**
- **No changes to config, risk, sizing (final_trade_notional=5 etc), symbols list, SOL handling, strategy thresholds, LaunchAgent.**
- Do not commit real (large) OHLCV data files to the repo unless a future explicit approval says otherwise. Fixtures only for tests.
- No runtime restart, no launchctl, no mutation of live state.
- Review branch only for this patch; push review; do not merge.

## After you have coverage
Next likely (P2-025J): run the full journal-window replay smoke against the now-populated real windows to confirm the harness still reproduces the known loss direction (fee-drag dominant, net ~-1.09) on actual price paths. Only then consider maker fee studies or exit policy experiments.

## Exact commands to re-verify coverage
```bash
python3 scripts/coinbase_ohlcv_acquisition_plan.py --json
python3 scripts/coinbase_journal_window_replay_report.py --json
```

## References
- docs/OHLCV_LOCAL_IMPORT.md (validator usage + format)
- docs/JOURNAL_WINDOW_REPLAY_BASELINE.md (why reproduce loss first)
- docs/ACTIVE_HANDOFF.md (current status)
- scripts/coinbase_ohlcv_import_validate.py --help
- scripts/coinbase_public_ohlcv_fetch.py --help (if using)

This completes the "make it possible to populate the exact windows" gate so that future replay can stop skipping everything.
