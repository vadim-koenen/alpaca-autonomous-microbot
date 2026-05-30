# P2-011A — Coinbase Fill Logger Scaffold

## Purpose

Create the smallest safe append-only logging scaffold for immutable Coinbase fill/proceeds/fee facts.

This patch intentionally does not hook into live execution. It creates a tested utility that can later be called from the narrowest safe execution seam after review.

## Why this matters

The current Coinbase journal can show exits, but prior reconciliation work proved direct sell proceeds and fee rows are missing. Until actual filled size, average filled price, gross quote value, fee amount, fee currency, and net quote value are captured, realized gross/net P/L must remain unavailable.

Profit optimization remains blocked until realized P/L can be reconstructed from reliable facts.

## Files added

- coinbase_fill_logger.py
- tests/test_coinbase_fill_logger.py
- docs/COINBASE_FILL_LOGGER_IMPLEMENTATION_PLAN.md

## Target output

Default future output path: logs/coinbase_fills.csv

## Schema

The scaffold writes this deterministic header:

- schema_version
- captured_at_utc
- source
- broker
- account_mode
- product_id
- side
- order_id
- client_order_id
- status
- created_time
- completion_time
- filled_size
- average_filled_price
- gross_quote_value
- fee_amount
- fee_currency
- net_quote_value
- liquidity_indicator
- raw_order_response_json
- raw_fill_response_json
- reconstruction_status
- notes

## Safety boundaries

P2-011A does not change:

- order submission
- sizing
- TP/SL
- hold time
- symbols
- prediction logic
- risk caps
- config
- .env
- launchd/runtime behavior
- journal behavior
- broker behavior

## Next step after P2-011A

P2-011B should inspect the current code and select one narrow hook point. Candidate seams from P2-010/P2-010C discovery include:

- broker_coinbase.py:get_order_status
- broker_coinbase.py:place_limit_order
- broker_coinbase.py:place_market_order
- journal.py:log_exit

The preferred hook is the seam where confirmed fill/proceeds/fee data is already available, not a seam that would require guessing or reconstructing fees.

## Validation required before hook

Before P2-011B touches execution flow, confirm:

1. Which Coinbase response contains actual fill/proceeds/fee facts.
2. Whether average_filled_price, filled_size, and fees are direct broker facts or local estimates.
3. Whether sell proceeds can be captured directly.
4. Whether partial fills need one row per order or one row per fill.
5. Whether repeated status polling could duplicate rows.

If any of those are unclear, keep P2-011B as docs/discovery only.
