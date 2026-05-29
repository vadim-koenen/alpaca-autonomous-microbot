# Operations

Run commands from:

```bash
cd /Users/vadimkoenen/Documents/Claude/Projects/Investing/alpaca-autonomous-microbot
```

## Reconciliation

```bash
bash scripts/reconcile.sh
```

Use this to confirm Coinbase remains blocked by broker-recovered ETH until the asset is transferred into the Advanced Trade-visible account.

## Daily Distillation

```bash
python3 scripts/daily_distill.py
```

For a specific date:

```bash
python3 scripts/daily_distill.py --date 2026-05-26
```

Outputs:

```text
memory/distillations/daily_summary_2026-05-26.md
memory/distillations/daily_summary_2026-05-26.json
```

Daily distillation is advisory memory/reporting only. It reads local journals,
memory, heartbeat, and state files; it does not run `main.py`, trade, submit
orders, cancel orders, modify broker state, restart bots, or change risk state.

Launchd plist path:

```text
launchd/com.vadim.daily-distill.plist
```

The plist is configured to run daily at 23:55 UTC:

```text
python3 scripts/daily_distill.py
```

Do not install, load, bootstrap, start, or kickstart this plist without explicit
operator approval. To install later after approval:

```bash
cp launchd/com.vadim.daily-distill.plist ~/Library/LaunchAgents/
plutil -lint ~/Library/LaunchAgents/com.vadim.daily-distill.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.vadim.daily-distill.plist
```

To remove later after approval:

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.vadim.daily-distill.plist
rm ~/Library/LaunchAgents/com.vadim.daily-distill.plist
```

## Alpaca Paper Auth Check

```bash
LIVE_TRADING=false ALPACA_PAPER=true CONFIG_FILE=config_alpaca_stocks.yaml BROKER=alpaca \
  python3 scripts/check_alpaca_auth_config.py --mode paper
```

This prints only presence and selection metadata. It must never print API key or secret values.

Preferred paper variables are:

```text
ALPACA_PAPER_API_KEY
ALPACA_PAPER_SECRET_KEY
```

If those are missing, the bot falls back to:

```text
ALPACA_API_KEY
ALPACA_SECRET_KEY
```

## Safe One-Cycle Checks

Coinbase dry-run:

```bash
LIVE_TRADING=false CONFIG_FILE=config_coinbase_crypto.yaml BROKER=coinbase \
  python3 main.py --mode dry_run --asset-class crypto --once
```

Alpaca paper:

```bash
LIVE_TRADING=false ALPACA_PAPER=true CONFIG_FILE=config_alpaca_stocks.yaml BROKER=alpaca \
  python3 main.py --mode paper --asset-class equities --once
```

## Verify No Live Mode

Confirm command lines use `--mode dry_run` or `--mode paper`, and `LIVE_TRADING=false`.

For launchd, inspect:

```bash
launchctl print gui/$(id -u)/com.vadim.alpaca-bot
launchctl print gui/$(id -u)/com.vadim.coinbase-crypto-bot
```

## Restart Launchd Safely

Stop:

```bash
scripts/stop_all.sh
```

Start:

```bash
scripts/start_all.sh
```

Check:

```bash
scripts/status.sh
bash scripts/reconcile.sh
```

## Controlled Restart Checklist

Restart remains human-controlled. Do not stop or start launchd jobs unless the
operator explicitly approves the restart.

Before restart:

- Run the full test suite.
- Run `bash scripts/status.sh`.
- Run `bash scripts/reconcile.sh`.
- Confirm the Coinbase ETH broker-recovered exposure block is understood.
- Confirm there is no live config drift from the approved config files.
- Confirm no `.env` edits or secret exposure occurred.

Restart:

- Stop/start only by explicit human approval.
- Use the existing operational scripts or launchd commands only after approval.

After restart:

- Monitor heartbeat files for both brokers.
- Run `bash scripts/status.sh`.
- Run `bash scripts/reconcile.sh`.
- Roll back if either bot is unhealthy, exposure is unknown, or risk state is
  inconsistent.

## Manual Recovered Position Clear

Run the read-only preflight first:

```bash
bash scripts/state_maintenance_preflight.sh
```

For machine-readable output:

```bash
python3 scripts/state_maintenance_preflight.py --json
```

If expected empty state files are missing, the preflight suggests a state
initializer command. It is still read-only unless `--init-missing` is supplied:

```bash
python3 scripts/state_maintenance_preflight.py --init-missing
```

Only run the initializer after both bots are stopped. It refuses to run while a
local runtime lock or heartbeat indicates either bot may still be running, and
it creates only missing expected state files as `{}`. Existing files are never
overwritten, including invalid JSON files.

If preflight reports bot-opened positions missing explicit safety fields, use
the normalization command only after both bots are stopped:

```bash
python3 scripts/state_maintenance_preflight.py --normalize-state
```

This backfills conservative state metadata such as
`counts_toward_exposure: true` without overwriting an explicit
`counts_toward_exposure: false`, and it keeps broker-recovered positions
non-controllable.

The preflight inspects local state files, runtime locks, and heartbeat files. It
prints status categories and suggested cleanup commands, but it does not modify
state, control processes, read configuration secrets, or call broker APIs.

Use `clear_recovered_position.sh` only after the preflight and reconciliation
confirm an open state entry is stale, broker-recovered, or otherwise not
API-controllable, and after the affected bot has been stopped by the operator.
Treat `BLOCKED_MANUAL_REVIEW` as a stop-and-review condition.

```bash
bash scripts/clear_recovered_position.sh \
  --broker coinbase \
  --key 'ETH/USD' \
  --reason 'operator verified no API-controllable position remains'
```

The script refuses to modify state while the selected bot appears to be running.
It reads `state/<broker>/open_positions.json`, removes only the requested key,
and appends the removed entry to `state/<broker>/closed_positions.json` with:

- `cleared_at`
- `cleared_reason`
- `cleared_by_script: true`

The script is local state maintenance only. It does not restart bots, edit
configuration, read environment secrets, or submit broker actions. After a
manual clear, run:

```bash
bash scripts/status.sh
bash scripts/reconcile.sh
```

Restart remains manual and requires explicit human approval.

## Stable Release Snapshot

Create a local snapshot after tests pass:

```bash
bash scripts/make_release_snapshot.sh
```

The snapshot excludes `.env`, virtualenvs, caches, raw logs, the SQLite memory
database, and `secrets/`. It writes a tarball and manifest under `releases/`.
It does not deploy, restart bots, or modify live processes.

## Clearing Broker-Recovered Coinbase Positions

Before clearing any `broker_recovered` Coinbase position from state, always follow
these steps in order:

1. Run `bash scripts/state_maintenance_preflight.sh` — verify no other blocking
   conditions are present.
2. Run `python3 scripts/coinbase_position_capability_diagnose.py` — confirm whether
   the position is Advanced Trade-controllable, consumer-wallet-only, or unknown.
3. Verify the asset in Coinbase UI / account page:
   - If visible in Advanced Trade portfolio: the bot may be able to close it via API.
   - If visible only in consumer wallet: sell manually from coinbase.com first.
4. Do not clear state unless you have verified the reason and the asset disposition.
5. Never clear state solely to bypass the exposure or manual-review gate.
6. If close capability is unknown, keep the position in manual-review and
   investigate further before taking any action.

After confirming the asset is resolved, use `scripts/clear_recovered_position.sh`
(stop bots first; restart only after explicit approval).

## Manual Rollback Notes

Rollback is human-controlled.

- Stop bots only with explicit approval.
- Back up current `state/` files before changing code.
- Restore a prior release snapshot manually.
- Restore state files only if explicitly approved.
- Run the full test suite.
- Run `bash scripts/status.sh`.
- Run `bash scripts/reconcile.sh`.
- Restart only with explicit approval.
- Monitor heartbeats after restart.
- If health, exposure, or order state is uncertain, stop and reassess before any
  further live operation.
