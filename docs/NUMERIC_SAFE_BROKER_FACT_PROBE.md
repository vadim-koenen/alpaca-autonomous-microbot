# Numeric-Safe Broker Fact Probe

P2-022F adds an explicit numeric-safe output mode to the Coinbase read-only
broker fact probe.

## Why P2-022E Still Blocked

P2-022E added numeric-safe redaction and one-cycle payload building. That proved
the offline builder can preserve direct broker numeric fields and that the
P2-022D readout can compute limited broker-backed P/L when those numbers are
present.

The live one-cycle capture still blocked because the probe emitted field
presence booleans and redacted presence markers, not the actual numeric broker
values. Booleans such as `has_filled_value=true` and `has_total_fees=true` prove
that a broker fact exists, but they are not numeric P/L evidence.

## Numeric-Safe Mode

Use `--include-numeric-pnl-fields` or the alias `--numeric-safe` to include
direct broker numeric fields in the probe JSON output.

Order fields preserved when present:

- `filled_value`
- `total_fees`
- `filled_size`
- `average_filled_price`
- `settled`
- `status` / `normalized_status`
- `side`
- `product_id`

Fill fields preserved when present:

- `price`
- `size`
- `fee`
- `commission`
- `commission_detail_total`
- `size_in_quote`
- `product_id`
- `side`

Identifier and secret-like fields remain redacted, including order IDs,
client-order IDs, trade/fill IDs, account IDs, portfolio IDs, user IDs, and any
auth/key/secret/token/signature-like fields.

Numeric values are copied as strings where possible. The probe does not perform
float math or infer missing values.

## One-Cycle Capture Shape

After human approval only, the future read-only retry should capture the same ETH
cycle with numeric-safe output:

```bash
python3 scripts/coinbase_read_only_broker_fact_probe.py \
  --live-read-only \
  --output json \
  --include-numeric-pnl-fields \
  --symbol ETH-USD \
  --order-id '<ENTRY_ORDER_ID>' \
  > /tmp/coinbase_read_only_evidence_capture_real-ethusd-029_entry_numeric_safe.json

python3 scripts/coinbase_read_only_broker_fact_probe.py \
  --live-read-only \
  --output json \
  --include-numeric-pnl-fields \
  --symbol ETH-USD \
  --order-id '<EXIT_ORDER_ID>' \
  > /tmp/coinbase_read_only_evidence_capture_real-ethusd-029_exit_numeric_safe.json
```

Do not run those commands without explicit human approval. They are read-only
broker calls, not implementation or test commands.

Then build the one-cycle payload offline:

```bash
python3 scripts/coinbase_one_cycle_numeric_safe_payload_builder.py \
  --entry-raw /tmp/coinbase_read_only_evidence_capture_real-ethusd-029_entry_numeric_safe.json \
  --exit-raw /tmp/coinbase_read_only_evidence_capture_real-ethusd-029_exit_numeric_safe.json \
  --output /tmp/coinbase_read_only_evidence_capture_real-ethusd-029_numeric_safe.json \
  --cycle-id real-ethusd-029 \
  --product-id ETH-USD \
  --entry-order-id '<ENTRY_ORDER_ID>' \
  --exit-order-id '<EXIT_ORDER_ID>' \
  --preserve-numeric-pnl-fields \
  --json
```

Run the broker-backed numeric readout offline:

```bash
python3 scripts/coinbase_broker_backed_pnl_readout.py \
  --source-json /tmp/coinbase_read_only_evidence_capture_real-ethusd-029_numeric_safe.json \
  --json
```

## Safety

P2-022F does not change risk, notional, symbols, strategy, runtime, background
jobs, or configuration. It does not write `logs/coinbase_fills.csv` or activate
`append_coinbase_fill_row`.

Preserved state:

```text
profit_readout_real_current=unsafe_to_aggregate until numeric broker facts are captured and accepted
scaling_allowed=false
risk_increase=not_approved
```
