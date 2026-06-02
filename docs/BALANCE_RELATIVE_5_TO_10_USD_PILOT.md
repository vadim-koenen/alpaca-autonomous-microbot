# Balance-Relative $5-$10 Coinbase Pilot

P2-023B replaces fixed-only `$5` Coinbase pilot sizing with a capped
percentage-of-balance pilot.

## Why Fixed $5 Was Temporary

P2-023A proved `$1` trades were not economically useful. The first measured
real ETH cycle was directionally right but net negative after fees:

```text
gross_pnl=0.0025
total_fees=0.0180
net_pnl=-0.0155
```

The fixed `$5` pilot was a safer next step than `$1`, but a long-running bot
should not stay fixed forever. If account value grows, trade size can rise
gradually. If account value shrinks, trade size should not blindly stay high.

## Sizing Rule

The pilot now uses:

```text
effective_balance = min(valid_positive_buying_power, valid_positive_equity)
target_trade_notional = effective_balance * 0.10
final_trade_notional = capped balance-relative notional
```

Guardrails:

- minimum fee-aware trade notional: `$5.00`
- maximum trade notional: `$10.00`
- absolute hard trade cap: `$10.00`
- maximum open positions: `1`
- maximum trades per day: `3`
- eligible symbols: BTC/USD and ETH/USD only
- excluded symbols: SOL/USD

At the observed account snapshot around `equity=50.3762` and
`buying_power=49.4345`, 10% resolves to about `$5`. At a `$100` balance, 10%
resolves to `$10`. Above `$100`, the `$10` hard cap still holds until a human
explicitly changes the config.

## Fee-Drag Gate Remains Active

The entry candidate still must clear:

```text
observed_round_trip_fee_rate + spread/slippage buffer
```

Using the broker-backed ETH cycle:

```text
observed_round_trip_fee_rate=0.017970
minimum_required_gross_move_rate=0.018970
```

If expected gross move is too small, the bot skips with:

```text
fee_drag_expected_edge_too_small
```

## Success Metric

Broker-backed net P/L remains the success metric. Larger scaling is not
approved until multiple measured broker-backed cycles are net positive after
fees, spread, and slippage buffer.

Preserved truth:

```text
profit_readout_real_current=unsafe_to_aggregate unless direct broker facts prove otherwise
scaling_allowed=false beyond the $10 capped pilot
risk_increase=not_approved
```
