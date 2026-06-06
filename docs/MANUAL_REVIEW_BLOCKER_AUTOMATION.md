# Manual-Review Blocker Automation

## Purpose

P2-029B prevents a stale recovered-position record from silently blocking entry
scans for hours or days. It adds:

- `scripts/coinbase_manual_review_blocker_watchdog.py`
- `scripts/stop_all_verified.sh`

This patch changes no strategy, risk limit, symbol list, exit policy, or live
runtime configuration.

## Local Watchdog

Default mode reads local evidence only:

```bash
python3 scripts/coinbase_manual_review_blocker_watchdog.py --json
```

For deterministic review with an operator-captured process snapshot:

```bash
pgrep -af "main.py --mode live" > /tmp/coinbase_live_process_snapshot.txt
python3 scripts/coinbase_manual_review_blocker_watchdog.py \
  --json \
  --process-snapshot /tmp/coinbase_live_process_snapshot.txt
```

The watchdog correlates:

- `journal_coinbase_crypto.csv`
- `state/coinbase/open_positions.json`
- `state/coinbase/external_inventory.json`
- `state/coinbase/closed_positions.json`
- `runtime/coinbase.lock`
- `runtime/STOP_TRADING`
- an optional process snapshot

It reports blocker age, missed scan cycles, the last entry/fill, close failure,
re-association warning, active lock state, duplicate-process risk, and
escalation severity. Default mode does not write files.

Use `--strict-exit-code` only for later automation. It returns nonzero for
`BLOCKED` or `CRITICAL`; normal reporting remains exit code zero.

## No-Silent-Block Escalation

- Older than 30 minutes: explicit alert.
- Older than 2 hours: blocked-duration escalation.
- Older than 24 hours: critical escalation.
- More than one live PID: critical duplicate-process warning.
- Blocked while a process remains live: lifecycle warning.
- `STOP_TRADING` present while a live PID remains: stop verification failed.

External/staked inventory is reported separately and is not counted as a
bot-owned manual-review blocker.

## Verified Stop

Use:

```bash
bash scripts/stop_all_verified.sh --wait-seconds 90
```

The script creates and retains `runtime/STOP_TRADING`, waits for
`main.py --mode live` processes to exit, checks broker runtime lock PIDs,
prints any remaining PIDs, and returns nonzero if stopping is not verified.
It never restarts a bot or removes the kill switch.

By default it sends no signals. Signal escalation requires an explicit choice:

```bash
bash scripts/stop_all_verified.sh --wait-seconds 120 --term-after 90
```

`--kill-after` is also available but is intentionally never the default.

## Remediation Plan

Plan-only mode never mutates state:

```bash
python3 scripts/coinbase_manual_review_blocker_watchdog.py \
  --plan-remediation
```

The required sequence is:

1. Activate `STOP_TRADING`.
2. Verify all live PIDs have exited.
3. Verify the broker has no holding or open order for the affected symbol
   through a separately approved read-only process.
4. Supply explicit operator confirmation and a reason.
5. Clear only the matching local stale manual-review record.

## Guarded Local-State Cleanup

After manual broker verification and a verified stop:

```bash
pgrep -af "main.py --mode live" > /tmp/coinbase_live_process_snapshot.txt
python3 scripts/coinbase_manual_review_blocker_watchdog.py \
  --json \
  --process-snapshot /tmp/coinbase_live_process_snapshot.txt \
  --clear-local-stale-blocker \
  --symbol ADA/USD \
  --operator-confirmed-no-broker-position \
  --reason "operator verified no broker position or open order"
```

The operation refuses unless:

- `STOP_TRADING` exists.
- A process snapshot was supplied and has no matching live process.
- The runtime lock PID is absent or no longer alive.
- Exactly one matching manual-review position exists.
- The operator confirmation flag and a nonempty reason are present.

On success it:

- writes a timestamped backup under `state/coinbase/backups/`;
- removes only the matching symbol from open state;
- archives the removed record in `closed_positions.json`;
- writes an audit record under `reports/blocker_remediation/`;
- records that broker truth was not independently established by the script.

This is local-state cleanup, not a broker fact claim. It does not authorize a
restart, removal of `STOP_TRADING`, live trading, or any order action.

## Future Read-Only Reconciliation

`--broker-read-only-reconcile` is reserved for P2-029C and currently performs
no broker action. P2-029C should define a separately reviewed, explicit,
read-only balances/open-orders check and alert schedule. It must remain
incapable of order actions and must not clear local state without every local
safety guard above.

## Preserved Safety State

```text
implementation_authorized=false
strategy_change_authorized=false
live_trading_unblock_authorized=false
state_mutation_authorized=false by default
broker_order_authorized=false
paper_probe_authorized=false
live_probe_authorized=false
scaling_authorized=false
```
