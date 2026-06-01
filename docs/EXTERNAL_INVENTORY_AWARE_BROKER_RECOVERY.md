# P2-021C4 External Inventory Aware Broker Recovery

P2-021C4 prevents Coinbase broker-position recovery from rehydrating known
external/staked SOL into active bot `open_positions`.

## Problem

After P2-021C3 normalized the user-staked SOL position into
`state/coinbase/external_inventory.json`, a restart could still see SOL in the
broker position snapshot and rebuild it into `state/coinbase/open_positions.json`
with `recovery_source=broker_position`. That recreated an active
manual-review-style blocker even though the position is external inventory:

- `staked_external_position=true`
- `external_inventory_classification=external_staked_position`
- `tradable_by_bot=false`
- `manual_close_allowed=false`
- `bot_inventory=false`
- `blocks_new_entries=false`

## C4 Behavior

When `position_manager.py` sees a broker SOL position that matches an
authoritative external inventory record, it:

- does not restore it from saved active state;
- does not recover it as `broker_recovered`;
- does not create a `journal_reassociated` active position;
- does not write active `open_positions`;
- records only observation metadata on the existing external inventory record:
  `last_seen_on_broker`, `last_seen_at`, `observed_qty`,
  `observed_notional`, `no_pnl_inference=true`, `no_close_attempted=true`,
  and `blocks_new_entries=false`.

This keeps active `open_positions` reserved for bot-tradable inventory.

## Entry Gate And Status Semantics

External/staked SOL is excluded from current bot-tradable inventory and current
entry blockers. Historical manual-review journal rows remain auditable, but
watchdog/operator status treat them as resolved by authoritative external
inventory when no active manual-review position exists.

The bot still must not claim realized P/L from external SOL.

Preserved readout:

```text
profit_readout=unsafe_to_aggregate
aggregation_allowed=false for real/incomplete evidence
scaling_allowed=false
risk_increase=not_approved
```

## Safety Boundary

P2-021C4 does not:

- call live broker APIs;
- run `--live-read-only`;
- read `.env` or secrets;
- place, cancel, close, sell, or modify orders;
- change risk, runtime, config, symbols, leverage, margin, futures, options, or
  commodities behavior;
- write `logs/coinbase_fills.csv`;
- activate `append_coinbase_fill_row`;
- use local journal P/L as broker truth;
- merge to `main`.

## Offline Verification

Run:

```bash
python3 -m py_compile position_manager.py utils.py scripts/coinbase_open_orphan_position_status.py scripts/coinbase_operator_status.py scripts/coinbase_stale_blocker_watchdog.py
python3 -m pytest tests/test_position_manager_reassociation.py tests/test_coinbase_stale_blocker_watchdog.py tests/test_coinbase_operator_status.py tests/test_coinbase_manual_review_blocker_remediation.py -q
```

Post-merge, after operator review only, restart verification should confirm:

- `state/coinbase/open_positions.json` remains empty or contains only
  bot-tradable positions;
- `state/coinbase/external_inventory.json` retains SOL/USD as external staked
  inventory;
- operator status reports no active SOL entry blocker;
- watchdog reports historical manual-review rows resolved by external inventory;
- `profit_readout` remains unsafe until direct broker fee/proceeds evidence is
  available.
