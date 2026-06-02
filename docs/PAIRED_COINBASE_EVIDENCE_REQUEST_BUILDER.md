# Paired Coinbase Evidence Request Builder

P2-022B codifies the previously one-off `/tmp` paired Coinbase request
generation into a deterministic repo script:

```bash
python3 scripts/coinbase_paired_evidence_request_builder.py \
  --journal journal_coinbase_crypto.csv \
  --secondary-journal journal.csv \
  --output /tmp/p2_022b_real_paired_request.json \
  --json
```

## Why This Exists

P2-022A manual discovery proved the local journals contain real paired BTC/ETH
entry and exit Coinbase order UUIDs:

- `uuid_btc_eth_rows=60`
- `paired_cycles_count=8`
- the read-only capture checklist returned
  `READY_FOR_HUMAN_APPROVED_READ_ONLY_CAPTURE`

That successful request was generated with an ad-hoc shell/Python command. This
script makes the same request-building step reviewable, repeatable, and tested.

## What It Does

The builder reads local journal CSV rows only. It:

- accepts `--journal`, optional `--secondary-journal`, `--output`,
  `--max-cycles`, `--lookback-days`, and `--json`;
- detects UUID-like Coinbase order IDs only from `order_id`;
- includes BTC/USD and ETH/USD only for profit aggregation;
- excludes SOL/USD from profit aggregation because SOL is external/staked
  inventory;
- pairs BUY entry UUIDs with EXIT/SELL UUIDs FIFO per symbol;
- writes checklist-compatible `cycles[]` with `product_id`, entry/exit
  `order_ids`, `date_window`, and `source_rows`;
- emits a safety block preserving read-only and no-risk-increase semantics.

The output is deterministic for the same input journals. The lookback window is
anchored to the latest timestamp in the provided journal rows, not wall-clock
time.

## Checklist Meaning

After building a request, run:

```bash
python3 scripts/coinbase_read_only_evidence_capture_checklist.py \
  --request-json /tmp/p2_022b_real_paired_request.json \
  --human-approved-read-only-capture \
  --json
```

`READY_FOR_HUMAN_APPROVED_READ_ONLY_CAPTURE` means the offline request is
structurally complete for a future human-approved read-only broker evidence
capture. It does not mean broker facts have been captured yet, and it does not
authorize running live broker reads without explicit human approval.

## What It Does Not Do

The builder does not:

- call Coinbase or any broker API;
- execute `--live-read-only`;
- read `.env` or secrets;
- place, cancel, close, modify, or submit orders;
- write state, runtime, logs, or `logs/coinbase_fills.csv`;
- activate `append_coinbase_fill_row`;
- increase risk, notional, symbols, strategy scope, or scaling;
- infer realized P/L from local journal rows.

## Profit Readout

`profit_readout_real_current` remains `unsafe_to_aggregate` until the future
human-approved read-only capture obtains direct broker fee/proceeds/fill facts
and the offline adapter/resolver prove broker-backed measured evidence.
