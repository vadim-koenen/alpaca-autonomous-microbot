# Coinbase Opportunity Dashboard

P2-024B adds an offline operator dashboard for the Coinbase bot. It explains
whether the current local evidence says to sit out, keep watching, or observe a
candidate. It does not authorize live trading.

The dashboard composes:

- the local Coinbase heartbeat
- the balance-relative pilot sizing preview
- the read-only trend advisory registry
- the latest fee-drag evidence report

Preserved safety posture:

- `trade_permission=none`
- `profit_readout=unsafe_to_aggregate`
- `aggregation_allowed=false`
- `scaling_allowed=false`
- `risk_increase=not_approved`
- BTC/USD and ETH/USD only
- SOL/USD remains excluded

Example offline commands:

```bash
python3 scripts/coinbase_opportunity_dashboard.py --json
python3 scripts/coinbase_opportunity_dashboard.py \
  --heartbeat tests/fixtures/opportunity_dashboard/heartbeat_current_50usd.json \
  --json
```

The trend layer remains advisory-only. Positive trend/news context can support
watching a symbol, but it never creates live trade permission and never bypasses
strategy, fee-drag, sizing, or risk gates.
