# Manual-Review Blocker Remediation

P2-021C3 adds a local, operator-approved path for clearing stale
`manual_review_position_open` entry blockers when the blocker is proven to be
external/staked/non-bot-tradable inventory.

## Observed Failure

The Coinbase live process can be running with buying power and equity available
while producing no new transactions because every candidate entry is blocked:

```text
ENTRY_BLOCKED reason=manual_review_position_open
```

For the current case, the blocking local state is SOL/USD with
`user_action_required=true`, `api_controllable=false`,
`exit_evaluation_enabled=false`, and
`manual_review_reason=broker_close_capability_unconfirmed`.

P2-020A established the project truth that the current tiny SOL position is
user-staked external inventory:

```text
staked_external_position=true
external_inventory_classification=external_staked_position
tradable_by_bot=false
manual_close_allowed=false
bot_inventory=false
```

Indefinite suspension is unacceptable because it prevents the live bot from
learning from safe, broker-permitted entries on other opportunities. Auto-close
is also prohibited because the SOL is staked/external and cannot be traded or
closed by the bot.

## Dry Run

Dry-run is the default and makes no writes:

```bash
python3 scripts/coinbase_manual_review_blocker_remediation.py \
  --json \
  --state-root tests/fixtures/coinbase_manual_review_blocker/manual_review_sol_state \
  --assertion-json tests/fixtures/coinbase_manual_review_blocker/external_staked_sol_assertion.json
```

The report includes the blocker, refusal reasons if any, backup preview,
external inventory preview, and whether the trading block would clear.

## Operator Assertion

If state does not already carry explicit P2-020A fields, provide a local
assertion file:

```json
{
  "symbol": "SOL/USD",
  "staked_external_position": true,
  "external_inventory_classification": "external_staked_position",
  "tradable_by_bot": false,
  "manual_close_allowed": false,
  "bot_inventory": false
}
```

This file is local evidence only. It does not prove P/L and does not authorize
risk scaling.

## Apply

Apply requires both flags:

```bash
python3 scripts/coinbase_manual_review_blocker_remediation.py \
  --json \
  --state-root /path/to/repo \
  --assertion-json /tmp/coinbase_external_inventory_assertion.json \
  --apply \
  --operator-approved-external-inventory-normalization
```

Apply mutates only local state:

- `state/coinbase/open_positions.json`
- `state/coinbase/external_inventory.json`
- a timestamped backup under `state/coinbase/backups/`

The SOL record is removed from active bot `open_positions` and preserved under
external inventory with `no_pnl_inference=true`, `no_close_attempted=true`,
`blocks_new_entries=false`, and the P2-020A external/staked fields.

## Rollback

Open the timestamped backup named in the JSON output and restore the backed-up
`open_positions` object to `state/coinbase/open_positions.json`. If needed,
restore the backed-up `external_inventory` object to
`state/coinbase/external_inventory.json`.

## Verification

Run:

```bash
python3 scripts/coinbase_manual_review_blocker_remediation.py --json --state-root /path/to/repo --assertion-json /tmp/coinbase_external_inventory_assertion.json
python3 scripts/coinbase_stale_blocker_watchdog.py --json
python3 scripts/coinbase_operator_status.py --json
```

The expected outcome is that true unresolved bot-owned manual-review positions
still block entries, but explicitly external/staked/non-bot inventory no longer
counts as an active manual-review entry blocker.

## Relationship To P2-021C And P2-021C2

P2-021C defines the human-approved read-only broker evidence bridge. P2-021C2
makes stale blockers visible and urgent. P2-021C3 adds the local state
normalization command after evidence and operator approval.

This is not a risk increase, not a notional increase, and not symbol expansion.
It does not place trades, does not close or sell SOL, does not infer realized
P/L, and does not call broker APIs.
