# One-Cycle Coinbase Broker Evidence Adapter

P2-022C2 maps the first clean one-cycle Coinbase read-only capture into the
offline profit evidence resolver schema.

## Current Evidence

The human-approved read-only capture for `real-ethusd-029` succeeded after the
P2-022C1 probe compatibility fix. The entry and exit broker probes both showed:

- order status/details were readable;
- historical fills were readable;
- `filled_size`, `average_filled_price`, `filled_value`, `total_fees`, and
  `settled` were present;
- per-fill fees were present;
- stable fill identifiers were present;
- no order/cancel/close/modify action was attempted.

The previous blocker was an offline schema mismatch: the clean capture used
`cycles[].entry_broker_payload_redacted` and
`cycles[].exit_broker_payload_redacted`, while the adapter and resolver expected
already-normalized `evidence_cycles`.

## Offline Commands

Run the adapter on a clean redacted payload:

```bash
python3 scripts/coinbase_broker_evidence_adapter.py \
  --source-json tests/fixtures/coinbase_read_only_one_cycle_payload/real_ethusd_029_redacted_payload.json \
  --json
```

Run the resolver directly on the same payload:

```bash
python3 scripts/coinbase_profit_readout_evidence_resolver.py \
  --probe-json tests/fixtures/coinbase_read_only_one_cycle_payload/real_ethusd_029_redacted_payload.json \
  --json
```

Both commands are offline-only. They do not import broker clients, read `.env`,
write state/logs, or place/cancel/close/modify orders.

## Readout Semantics

For this one-cycle payload only, direct broker-backed evidence can move the
fixture readout to `measured_broker_backed_limited` when both entry and exit legs
have direct broker order IDs, fill IDs, fees, and filled value/proceeds evidence.

This does not approve scaling, risk increase, symbol expansion, or local journal
P/L aggregation.

Preserved state for real current/incomplete evidence:

```text
profit_readout_real_current=unsafe_to_aggregate
aggregation_allowed_real_current=false
scaling_allowed=false
risk_increase=not_approved
```
