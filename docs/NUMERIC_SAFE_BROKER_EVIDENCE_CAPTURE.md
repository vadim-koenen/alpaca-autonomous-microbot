# Numeric-Safe Broker Evidence Capture

P2-022E adds an offline redaction/build step for Coinbase read-only evidence
payloads. P2-022D already computes numeric broker-backed P/L when direct numeric
values are available. It correctly blocked the real captured payload because the
needed financial values had been replaced with presence markers such as
`<REDACTED_DIRECT_BROKER_FILLED_VALUE_PRESENT>` and
`<REDACTED_DIRECT_BROKER_TOTAL_FEES_PRESENT>`.

Presence markers are useful for evidence completeness. They are not numeric
broker values, so they cannot support gross P/L, total fees, or net P/L.

## Numeric Fields Preserved

When `--preserve-numeric-pnl-fields` is used, the broker payload redactor keeps
the direct numeric fields needed for limited-cycle P/L:

- `filled_value`
- `total_fees`
- `filled_size`
- `average_filled_price`
- `price`
- `size`
- `fee`
- `commission`
- `commission_detail_total`
- `size_in_quote`
- `proceeds`

These values are financial facts from the broker read surface. They are required
for offline numeric P/L extraction and are not account identifiers.

## Fields Still Redacted

Identifier and secret-like fields remain redacted, including:

- `order_id`
- `client_order_id`
- `trade_id`
- `fill_id`
- `entry_id`
- `account_id`
- `portfolio_id` / `retail_portfolio_id`
- `user_id`
- any key containing secret-like fragments such as `secret`, `token`, `key`,
  `signature`, `auth`, `authorization`, or `bearer`

The goal is to keep numeric broker facts while removing identifiers and
credential-like material.

## Offline Build Command

Given already-captured local raw entry and exit JSON files, build a numeric-safe
one-cycle payload without any broker calls:

```bash
python3 scripts/coinbase_one_cycle_numeric_safe_payload_builder.py \
  --entry-raw /tmp/coinbase_read_only_evidence_capture_real-ethusd-029_entry_raw.json \
  --exit-raw /tmp/coinbase_read_only_evidence_capture_real-ethusd-029_exit_raw.json \
  --output /tmp/coinbase_read_only_evidence_capture_real-ethusd-029_numeric_safe.json \
  --cycle-id real-ethusd-029 \
  --product-id ETH-USD \
  --entry-order-id '<ENTRY_ORDER_ID>' \
  --exit-order-id '<EXIT_ORDER_ID>' \
  --preserve-numeric-pnl-fields \
  --json
```

The order IDs passed to the builder are used only to preserve evidence shape.
They are redacted in the output payload.

## Offline Numeric Readout

Run the broker-backed numeric P/L readout against the numeric-safe payload:

```bash
python3 scripts/coinbase_broker_backed_pnl_readout.py \
  --source-json /tmp/coinbase_read_only_evidence_capture_real-ethusd-029_numeric_safe.json \
  --json
```

Expected safe result when direct numeric entry and exit evidence is present:

```text
verdict=MEASURED_BROKER_BACKED_LIMITED
profit_readout=measured_broker_backed_limited
gross_pnl=<broker numeric gross>
total_fees=<broker numeric fees>
net_pnl=<broker numeric net>
scaling_allowed=false
risk_increase=not_approved
```

If numeric values are missing or replaced by redacted presence markers, the
readout remains blocked with `profit_readout=unsafe_to_aggregate`.

## Safety

P2-022E is offline-only. It does not import broker clients, read `.env`, place
orders, cancel/close/modify orders, write `logs/coinbase_fills.csv`, activate
`append_coinbase_fill_row`, or change risk, notional, symbols, strategy,
runtime, or configuration.

Scaling remains locked:

```text
scaling_allowed=false
risk_increase=not_approved
```
