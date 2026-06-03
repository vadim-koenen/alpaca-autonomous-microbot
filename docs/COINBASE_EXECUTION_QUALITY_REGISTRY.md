# Coinbase Execution Quality Registry

P2-025A adds an offline, fixture-backed execution-quality registry for the
controlled Coinbase spot basket:

- BTC/USD
- ETH/USD
- ADA/USD
- AVAX/USD
- DOGE/USD
- LINK/USD
- LTC/USD

SOL/USD remains external/staked inventory and is excluded from bot-tradable
inventory and ranking.

## Why This Exists

The first broker-backed `$1` ETH cycle was directionally gross positive but net
negative after fees. For a small account using `$5-$10` trades, symbol choice
must account for execution quality before any future order path can be trusted.

This registry scores local fixture evidence using:

- bid/ask spread
- max allowed spread
- target notional
- maker/taker fee assumptions
- entry and exit liquidity assumptions
- slippage buffer
- required break-even gross move
- expected gross move, when supplied

## Fee Drag Relationship

The required break-even move is:

```text
round_trip_fee_rate + spread_rate + slippage_buffer_rate
```

A symbol with acceptable spread can still fail if the assumed liquidity type is
taker/taker and the expected gross move is too small. This preserves the fee
drag guard instead of weakening it.

## Coinbase Preview PNL Is Not Enough

Coinbase order preview can be useful as an advisory source later, but preview
PNL is not final profitability evidence here because preview PNL excludes fees
and slippage. The registry marks preview values as advisory-only and never lets
them override the fee/spread/slippage model.

## Why Product Metadata, Book, And Fills Matter

Future read-only adapters should populate this registry from direct Coinbase
facts:

- product metadata for spot-only admission and product constraints
- product book / ticker for bid, ask, spread, and depth
- order preview for advisory cost context only
- fills for broker-backed fee and proceeds truth after execution

## Read-Only Boundary

P2-025A is offline-only. It does not import broker clients, call live APIs, read
`.env`, preview/create/cancel/close/modify orders, write logs/state, restart the
bot, or touch `launchctl`.

## Future Work

Likely next patches:

- P2-025B Coinbase product metadata fixture/adapter
- P2-025C mandatory pre-trade preview/cost gate
- P2-025D maker-first/post-only execution feasibility
- P2-025E broker-backed fill reconciliation improvement
