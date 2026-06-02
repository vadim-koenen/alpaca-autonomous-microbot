# Fee-Aware $5 Coinbase Pilot

P2-023A replaces ineffective `$1` Coinbase micro-trades with a controlled
fee-aware `$5` pilot gate.

## Why $1 Trades Are Rejected

The first real broker-backed numeric ETH cycle, `real-ethusd-029`, was
directionally correct but net negative after Coinbase fees:

```text
entry filled_value=1.0000
entry fee=0.0060
exit filled_value=1.0025
exit fee=0.0120
gross_pnl=0.0025
total_fees=0.0180
net_pnl=-0.0155
net_pnl_direction=negative
```

The gross move was positive, but fees exceeded the realized edge. This means
`$1` execution is not meaningful live trading for this account.

## Controlled Pilot Envelope

The new pilot is deliberately narrow:

- `pilot_trade_notional_usd=5.00`
- `max_trade_notional_usd=5.00`
- `max_open_positions=1`
- `max_trades_per_day=3`
- BTC/USD and ETH/USD only
- SOL/USD remains excluded as external/staked inventory
- no multi-asset expansion during this pilot
- no margin, leverage, options, futures, perps, or commodities

This is not unrestricted scaling. It is a capped experiment to determine whether
slightly larger spot trades can clear measured fee drag.

## Fee-Drag Gate

The gate estimates the observed round-trip fee rate from broker-backed evidence:

```text
entry_fee / entry_filled_value + exit_fee / exit_filled_value
```

A candidate must have expected gross move above:

```text
observed_round_trip_fee_rate + spread_slippage_buffer
```

If the expected edge is too small, the entry is skipped with:

```text
fee_drag_expected_edge_too_small
```

## Offline Report

Run the fee-drag report against a numeric-safe evidence payload:

```bash
python3 scripts/coinbase_fee_drag_profitability_report.py \
  --source-json tests/fixtures/coinbase_fee_drag_profitability/real_style_1usd_eth_fee_drag_cycle.json \
  --json
```

Expected for the first measured `$1` ETH cycle:

```text
verdict=FEE_DRAG_CONFIRMED
recommendation=do_not_continue_1usd_micro_trades
scale_allowed=false
risk_increase=not_approved
```

## Scaling Rule

Scaling remains locked at the `$5` pilot cap. Larger sizing is not approved until
multiple broker-backed measured cycles are net positive after fees, spread, and
slippage buffer.
