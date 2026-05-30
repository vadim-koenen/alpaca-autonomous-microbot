# Coinbase Immutable Fill Logging Spec

## Purpose

P2-008 defines the required contract for immutable Coinbase fill/proceeds/fee logging before any live implementation is attempted.

P2-007 proved the current local Coinbase journal has exit rows but does not contain direct sell proceeds or fee rows. That means realized gross/net P/L cannot be reconstructed safely and must remain `n/a`.

This spec exists to prevent strategy tuning based on incomplete data.

## Safety classification

Class 1: advisory/specification/read-only.

This patch must not:

- call Coinbase APIs
- read `.env`
- place, cancel, or modify orders
- restart bots
- run `launchctl`
- edit `config_coinbase_crypto.yaml` or `config.yaml`
- change risk caps
- touch `state/`, `runtime/`, or `launchd/`
- touch `broker_*.py`, `order_manager.py`, `risk_manager.py`, `main.py`, or `strategy_crypto.py`
- connect predictions to live trading

## Required future fill log

Future implementation should append one immutable row per Coinbase order fill.

Recommended file path:

- `logs/coinbase_fills.csv`

The file should be append-only. Existing rows should not be rewritten during normal bot operation.

## Required columns

Minimum required columns:

- `schema_version`
- `logged_at`
- `source`
- `environment`
- `strategy`
- `cycle_id`
- `position_id`
- `client_order_id`
- `exchange_order_id`
- `product_id`
- `symbol`
- `side`
- `order_type`
- `order_status`
- `fill_status`
- `filled_size`
- `average_filled_price`
- `gross_quote_value`
- `fee_amount`
- `fee_currency`
- `net_quote_value`
- `created_at`
- `filled_at`
- `raw_event_type`
- `notes`

## Column meanings

- `gross_quote_value`: gross quote-currency value of the fill before fees.
- `fee_amount`: actual fee charged for the fill.
- `net_quote_value`: quote value after fee treatment. For buys/sells this must be defined consistently in the future implementation.
- `cycle_id`: stable strategy lifecycle ID tying buy and sell fills together.
- `position_id`: stable local position identifier, if available.
- `client_order_id`: local/client-generated order identifier, if available.
- `exchange_order_id`: Coinbase-side order identifier.
- `side`: expected values are `buy` or `sell`.
- `fill_status`: expected values should distinguish filled, partial, canceled, rejected, and unknown.

## Why this matters

Profit optimization requires accurate realized P/L. Accurate realized P/L requires actual buy cost, sell proceeds, and fees.

Without this log, the system can observe exits but cannot safely answer whether the bot made or lost money on a closed cycle.

## Implementation guardrails for a later patch

A future implementation may need to touch live execution-path code. That future patch must be reviewed separately and must not be treated as Class 1 unless it is strictly non-invasive.

Before implementation, identify exactly where Coinbase order responses and fill details are available.

Implementation should prefer an append-only helper with narrow responsibility:

- accept normalized fill data
- validate required fields
- append to `logs/coinbase_fills.csv`
- never place orders
- never change config
- never mutate runtime state except the intended CSV append

## Profit roadmap dependency

Do not tune notional, TP/SL, hold time, symbol selection, or prediction-to-live behavior until fill/proceeds/fee logging is reliable enough to reconstruct realized P/L.
