# BROKER EVIDENCE SOURCE MAP

P2-021B maps offline Coinbase-like payloads into the P2-021A profit evidence
resolver schema. It does not make broker calls and does not change production
runtime behavior.

Current preserved state:

```text
profit_readout=unsafe_to_aggregate
aggregation_allowed=false
scaling_allowed=false
risk_increase=not_approved
```

P2-020A remains authoritative for the current staked SOL:

```text
staked_external_position=true
external_inventory_classification=external_staked_position
tradable_by_bot=false
manual_close_allowed=false
bot_inventory=false
```

## Existing Repo Evidence Surfaces

### List fills / historical fills

Repo wrapper:

```text
BrokerCoinbase.get_historical_fills(product_id=..., order_id=...)
```

Implementation surface:

- `broker_coinbase.py`
- calls Coinbase Advanced Trade `get_fills(**params)`
- supports `product_id`
- supports `order_id`
- normalizes response rows from `fills` or `data`

Fields expected from fill-like rows:

- `trade_id`, `fill_id`, or `entry_id`
- `order_id`
- `product_id`
- `side`
- `price`
- `size`
- `fee` or `commission`
- `filled_value`, `proceeds`, or quote-value equivalent when present

Evidence value:

- Strong source for per-fill idempotency and per-fill fee.
- Strong source for connecting a fill to a specific order when `order_id` is present.
- Insufficient alone if fee or value/proceeds are absent.

### Order details / status

Repo wrapper:

```text
BrokerCoinbase.get_order_status(order_id=...)
```

Implementation surface:

- `broker_coinbase.py`
- calls Coinbase Advanced Trade `get_order(order_id=...)`
- normalizes `filled_value`
- normalizes `total_fees`
- normalizes `filled_size`
- normalizes `average_filled_price`

Fields expected from order-like payloads:

- `order_id`
- `client_order_id`
- `product_id`
- `side`
- `status`
- `filled_value` or `proceeds`
- `total_fees` or `commission`

Evidence value:

- Strong source for order-level proceeds/value and total fees.
- Must be paired with fill rows that provide stable fill IDs before resolver promotion.

### Transaction-like fill records

Coinbase-like transaction/fill records may use names that differ from current
fixtures. The P2-021B adapter normalizes:

- `commission` -> `fee`
- `proceeds` -> `filled_value`
- `fill_id` / `entry_id` -> `trade_id` equivalent for resolver purposes

Evidence value:

- Useful when transaction rows include direct commission/proceeds and stable IDs.
- Still must include order linkage or order details to unlock measured readout.

### Existing probe JSON

Existing probes commonly expose:

- `recent_fills_sample`
- `open_positions_on_broker`
- `sol_on_broker`
- `broker_read_successful`

Evidence value:

- Safe offline input.
- Can unlock only if the sample includes direct order IDs, stable fill IDs,
  fees, and proceeds/filled_value for both entry and exit legs.
- Old SOL probes with null fee/filled_value remain unsafe.

### Local journals

Local journals can provide context, candidate order IDs, and operator history.

Evidence value:

- Insufficient for broker P/L truth.
- Any local `pnl`, `profit`, `realized_pnl`, or estimate remains
  `unsafe_to_aggregate` until corroborated by direct broker fields.

## Offline Adapter

Script:

```bash
python3 scripts/coinbase_broker_evidence_adapter.py \
  --source-json tests/fixtures/coinbase_broker_evidence/complete_commission_payload.json \
  --json
```

The adapter emits:

- `adapted_evidence` in the P2-021A resolver schema
- `resolver_report` from `coinbase_profit_readout_evidence_resolver.py`
- `source_map` explaining which source families supplied fields
- `safety` confirmations

Promotion remains delegated to P2-021A. P2-021B only normalizes source payloads.

## Future Human-Approved Read-Only Capture Checklist

Do not run this checklist without explicit human approval for a single
read-only task.

1. Identify a closed bot-owned cycle and collect candidate order IDs from local
   journal/context.
2. For each candidate entry and exit order, run a read-only order-detail capture
   using the existing wrapper path:

   ```text
   BrokerCoinbase.get_order_status(order_id=...)
   ```

3. For each order, capture filtered fills using:

   ```text
   BrokerCoinbase.get_historical_fills(product_id=..., order_id=...)
   ```

4. Redact raw payloads according to `docs/BROKER_PAYLOAD_REDACTION_POLICY.md`.
5. Save sanitized payloads outside production logs/state.
6. Replay the sanitized payload through:

   ```bash
   python3 scripts/coinbase_broker_evidence_adapter.py --source-json <sanitized_payload.json> --json
   ```

7. Confirm the nested resolver report:

   ```text
   profit_readout=measured_broker_backed_limited
   aggregation_allowed=true
   scaling_allowed=false
   evidence_level=L4_direct_entry_exit_broker_facts
   ```

8. If any direct field is missing, keep:

   ```text
   profit_readout=unsafe_to_aggregate
   aggregation_allowed=false
   scaling_allowed=false
   ```

## Hard Prohibitions

- No live broker calls in P2-021B.
- No `--live-read-only`.
- No `.env` or secrets reads.
- No orders/cancels/closes/modifications.
- No runtime/risk/config/background changes.
- No state/log mutation.
- No `logs/coinbase_fills.csv` writes.
- No `append_coinbase_fill_row` activation.
- No local journal P/L as broker truth.
- No staked SOL as bot inventory.
- No risk increase.

