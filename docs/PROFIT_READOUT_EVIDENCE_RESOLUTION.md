# PROFIT READOUT EVIDENCE RESOLUTION

P2-021A adds an offline-first resolver for the `profit_readout` blocker.

The resolver does not make broker calls, does not read `.env`, does not write
state or logs, does not touch `logs/coinbase_fills.csv`, and does not activate
`append_coinbase_fill_row`.

## Current State

```text
profit_readout=unsafe_to_aggregate
aggregation_allowed=false
scaling_allowed=false
risk_increase=not_approved
```

The current tiny SOL position is user-staked external locked inventory:

```text
staked_external_position=true
external_inventory_classification=external_staked_position
tradable_by_bot=false
manual_close_allowed=false
bot_inventory=false
```

That SOL must not be counted as bot inventory and must not be closed or
remediated by the bot.

## Evidence Sources Inspected

Repo inspection found these relevant surfaces:

- `broker_coinbase.py`
  - `get_historical_fills(product_id=..., order_id=...)`
  - Uses Coinbase Advanced Trade `get_fills(**params)`.
  - Preserves `fills` or `data` response rows.
  - Supports product-id and order-id filtering.
- `broker_coinbase.py`
  - `get_order_status(order_id=...)`
  - Normalizes order details including `filled_value` and `total_fees`.
- `coinbase_order_fills_reconciliation.py`
  - Pure helper that classifies order/fill fields as direct broker facts,
    locally derived, unavailable, or unsafe estimates.
- Existing fixtures under `tests/fixtures/coinbase/`
  - Show order-level `filled_value`, `total_fees`, `order_id`.
  - Show fill-level `trade_id` / `entry_id`, `order_id`, `fee`, `size`, `price`.
- Existing reconciliation fixtures under `tests/fixtures/coinbase_reconciliation/`
  - Show the old SOL blocker shape where fee and filled_value were missing.

Coinbase evidence hypothesis preserved for future human-approved live read-only
work:

1. Historical/list fills may expose fill-level `trade_id` or `entry_id`.
2. Order-id-filtered fills may connect fills to a specific bot order.
3. Advanced Trade fill transaction rows may include `order_id`, `product_id`,
   and `commission` / `fee`.
4. Order details may expose direct `filled_value` and `total_fees`.
5. Existing local captured payloads can be replayed through the resolver offline.

## Resolver Contract

Script:

```bash
python3 scripts/coinbase_profit_readout_evidence_resolver.py \
  --probe-json tests/fixtures/coinbase_profit_readout/complete_direct_entry_exit_evidence.json \
  --json
```

Default mode accepts fixture/probe JSON only.

Required output fields:

- `verdict`
- `profit_readout`
- `aggregation_allowed`
- `scaling_allowed`
- `evidence_level`
- `required_missing_fields`
- `entry_evidence_available`
- `exit_evidence_available`
- `direct_fee_available`
- `direct_proceeds_or_filled_value_available`
- `direct_order_id_available`
- `direct_trade_or_fill_id_available`
- `staked_external_position`
- `bot_inventory`
- `next_required_action`

## Promotion Rule

`profit_readout` may become `measured_broker_backed_limited` only for closed,
bot-owned cycles where every required direct broker fact is present for both
entry and exit legs:

- direct order id
- direct trade/fill id
- direct fee
- direct proceeds or filled_value
- correct entry BUY side
- correct exit SELL side

When all required facts are present:

```text
profit_readout=measured_broker_backed_limited
aggregation_allowed=true
scaling_allowed=false
evidence_level=L4_direct_entry_exit_broker_facts
```

`scaling_allowed` stays false because risk increase remains a separate human
approval gate.

## Fail-Closed Rules

The resolver must return `profit_readout=unsafe_to_aggregate` when:

- any required direct broker field is missing
- fees are missing or zero
- proceeds / filled_value are missing or zero
- order ids are missing
- trade/fill ids are missing
- only local journal P/L is present
- the inventory is staked external inventory
- the supplied evidence is not a closed bot-owned entry+exit cycle

Local journals, estimated P/L fields, dashboard text, and operator notes are not
broker truth.

## Future Human-Approved Read-Only Evidence Collection

Do not run this during offline review. This is the exact future shape if Vadim
explicitly approves a single live read-only evidence collection task later:

```bash
# Human approval required before any live read-only command.
# No orders, cancels, closes, modifications, state writes, or fill logger writes.

python3 scripts/coinbase_full_fill_payload_capture.py \
  --live-read-only \
  --trade-id <TRADE_OR_FILL_ID> \
  --product-id <PRODUCT-ID> \
  --json
```

The underlying wrapper paths to inspect are:

```text
BrokerCoinbase.get_historical_fills(product_id=..., order_id=...)
BrokerCoinbase.get_order_status(order_id=...)
```

Any captured output must be redacted and replayed through
`coinbase_profit_readout_evidence_resolver.py` offline before any readout
promotion is considered.

## Non-Goals

- No live broker calls in P2-021A.
- No `--live-read-only` in P2-021A verification.
- No `.env` or secrets.
- No orders/cancels/closes/modifications.
- No runtime, risk, config, background, state, or log mutation.
- No `logs/coinbase_fills.csv` writes.
- No `append_coinbase_fill_row` activation.
- No risk increase.

