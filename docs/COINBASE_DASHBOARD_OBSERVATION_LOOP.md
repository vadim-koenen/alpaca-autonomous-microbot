# Coinbase Dashboard Observation Loop

P2-024C adds an offline observation loop and operator digest on top of the
P2-024B opportunity dashboard.

The observation loop repeats finite local dashboard snapshots without sleeping,
writing files, calling brokers, reading secrets, or touching runtime services.
The operator digest converts those snapshots into a concise readout:

- current-style verdict
- next required action
- final notional preview
- BTC/USD and ETH/USD only confirmation
- SOL/USD exclusion confirmation
- trend and fee-drag status
- preserved profit/risk gates

Example offline commands:

```bash
python3 scripts/coinbase_dashboard_observation_loop.py \
  --heartbeat tests/fixtures/opportunity_dashboard/heartbeat_current_50usd.json \
  --iterations 2 \
  --json

python3 scripts/coinbase_operator_digest.py \
  --heartbeat tests/fixtures/opportunity_dashboard/heartbeat_current_50usd.json \
  --iterations 2
```

Preserved gates:

```text
trade_permission=none
profit_readout=unsafe_to_aggregate
aggregation_allowed=false
scaling_allowed=false
risk_increase=not_approved
```

The digest is an operator advisory only. It never grants trade permission, never
restarts runtime, and never changes risk, sizing, symbols, or config.
