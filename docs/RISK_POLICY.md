# Risk Policy

The risk manager is mandatory and cannot be bypassed.

Every order must pass risk checks before the broker adapter is called. Strategy output is only a proposal.

## Broker-Recovered Positions

Broker-recovered positions count toward exposure by default.

External/untradeable exposure blocks new entries when it consumes the relevant cap.

`counts_toward_exposure=false` may only be used after explicit human approval.

## Duplicate Orders

The final order path blocks duplicate intent using:

```text
broker:strategy:asset_class:symbol:side:purpose
```

It checks local state, broker open orders when available, and recent journal intent. If order state cannot be checked, the bot fails closed and requires manual reconciliation.

## Fail Closed

Missing state, broker uncertainty, stale data, wide spreads, account-health failures, auth failures, and risk-cap breaches block trading.

## No Self-Increase

The bot must not self-modify live strategy scope, increase risk, add symbols, add leverage, enable options, enable margin, or enable short selling without human approval.
