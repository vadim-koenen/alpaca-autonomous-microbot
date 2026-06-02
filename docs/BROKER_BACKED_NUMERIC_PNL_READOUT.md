# Broker-Backed Numeric P/L Readout

P2-022D adds an offline numeric realized P/L readout for closed Coinbase cycles
only when direct broker-backed numeric values are available.

## What C2 Proved

P2-022C2 proved the one-cycle ETH read-only capture can be adapted into direct
broker evidence:

- entry and exit order details are present;
- entry and exit fill facts are present;
- direct order IDs and fill IDs are present;
- direct fees and filled value/proceeds evidence are present;
- the resolver can return `measured_broker_backed_limited` for that limited
  broker-backed cycle.

That evidence completeness is separate from numeric P/L extraction.

## What D Adds

`scripts/coinbase_broker_backed_pnl_readout.py` computes:

- entry filled value;
- entry fees;
- exit filled value/proceeds;
- exit fees;
- gross P/L;
- total fees;
- net P/L;
- net P/L direction.

It uses `Decimal`, not `float`, and reads local JSON only.

Example:

```bash
python3 scripts/coinbase_broker_backed_pnl_readout.py \
  --source-json tests/fixtures/coinbase_numeric_broker_pnl/one_cycle_numeric_payload.json \
  --json
```

## Redacted Markers

Redacted presence markers such as
`<REDACTED_DIRECT_BROKER_FILLED_VALUE_PRESENT>` prove that a field existed, but
they are not numeric values. Numeric P/L remains blocked until a numeric-safe
redacted payload retains filled value/proceeds and fee amounts.

The script does not infer P/L from local journals. Local journal P/L remains
advisory only.

## Safety

The numeric readout is offline-only. It does not import broker clients, read
`.env`, write logs/state, or place/cancel/close/modify orders.

Preserved state:

```text
profit_readout_real_current=unsafe_to_aggregate until numeric-safe broker values are accepted
scaling_allowed=false
risk_increase=not_approved
```
