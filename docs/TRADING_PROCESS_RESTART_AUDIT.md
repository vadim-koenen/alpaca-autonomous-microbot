# Trading Process Restart Audit

P2-023B adds a local LaunchAgent audit before any future Coinbase restart.

## Why This Exists

A previous restart attempt surfaced:

```text
com.vadim.price-path-logger.plist
```

The heartbeat PID did not change. That suggests the restart may have targeted
the price logger instead of the live Coinbase trading bot.

## Audit First

Run:

```bash
python3 scripts/coinbase_trading_process_audit.py --json
```

The audit reads local plist files and classifies each candidate as:

```text
trading_bot
price_logger
unknown
```

It recommends a restart target only when classification is `trading_bot`.

## Restart Rule

Do not restart:

- an unknown plist
- a price logger plist
- any plist without a clear Coinbase trading bot signature

Only a plist classified as `trading_bot` should be considered for a later
human-approved restart.

The audit does not run `launchctl`, kill processes, restart anything, read
`.env`, call broker APIs, or mutate state/log files.
