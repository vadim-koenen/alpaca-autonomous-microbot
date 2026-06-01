# Human-Approved Read-Only Evidence Capture

P2-021C adds an offline bridge between the broker evidence source map and a
future human-approved Coinbase read-only capture. It does not call Coinbase,
does not read `.env`, and does not write runtime state or logs.

Current real-account truth is preserved:

```text
profit_readout_real_current=unsafe_to_aggregate
aggregation_allowed_real_current=false
scaling_allowed=false
risk_increase=not_approved
```

## Purpose

The bridge answers one operational question before any live read is approved:
which exact order IDs, product IDs, date windows, fields, redactions, and offline
commands are required to turn future Coinbase read-only payloads into the
P2-021B adapter input and then into the P2-021A resolver.

Run the offline checklist with a prepared request:

```bash
python3 scripts/coinbase_read_only_evidence_capture_checklist.py \
  --request-json tests/fixtures/coinbase_read_only_evidence_capture/complete_capture_request.json \
  --json
```

To mark the checklist as ready for a future human-approved read-only capture,
the operator must explicitly add:

```bash
--human-approved-read-only-capture
```

That flag does not perform a capture. It only records that a human has approved
the future read-only step described by the checklist.

## Required Capture Inputs

Each closed bot-owned cycle must include:

- `product_id`
- entry and exit `order_id`
- date window `start` and `end`

Each future captured fill/order payload must preserve direct broker facts:

- `order_id`
- trade or fill ID
- `side`
- `product_id`
- `size`
- `price`
- `timestamp`
- fee or commission
- filled value or proceeds

Local journal P/L is still insufficient and must not unlock aggregation.
Staked SOL remains external locked inventory and must not be included as
bot-tradable inventory.

## Future Commands

The checklist output includes future commands clearly marked:

```text
DO NOT RUN WITHOUT APPROVAL
```

Those commands are not executed by P2-021C. After human approval, the intended
future read-only method calls are:

```text
BrokerCoinbase.get_order_status(order_id=...)
BrokerCoinbase.get_historical_fills(product_id=..., order_id=..., start=..., end=...)
```

After redaction, the expected offline adapter command is:

```bash
python3 scripts/coinbase_broker_evidence_adapter.py \
  --source-json /tmp/coinbase_read_only_evidence_capture_payload.json \
  --json
```

The resolver can then be run offline on the adapted evidence payload path
specified by the checklist.

## Safety Rules

P2-021C does not allow:

- live broker calls
- `--live-read-only` execution
- `.env` or secret reads
- orders, cancels, closes, or modifications
- runtime, risk, config, background, state, or log mutation
- `logs/coinbase_fills.csv` writes
- `append_coinbase_fill_row` activation
- risk increase
- merge to `main`
