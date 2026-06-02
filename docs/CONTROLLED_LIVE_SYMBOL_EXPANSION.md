# Controlled Live Symbol Expansion

P2-024D expands the live Coinbase spot candidate basket because BTC/USD and
ETH/USD alone were producing too few opportunities after the trend, fee-drag,
and risk gates became stricter.

Approved live spot basket:

- BTC/USD
- ETH/USD
- ADA/USD
- AVAX/USD
- DOGE/USD
- LINK/USD
- LTC/USD

Explicit exclusions:

- SOL/USD
- derivatives
- perps
- prediction markets
- unsupported products
- invalid or stale quote products

This is a controlled opportunity-count expansion only. It does not increase
trade size, hard caps, open-position limits, daily trade count, or exposure.

Preserved caps:

```text
max_trade_notional_usd=10.00
absolute_hard_trade_cap_usd=10.00
max_total_crypto_exposure_usd=10.00
max_open_positions=1
max_trades_per_day=3
shared_caps=true
```

Every expanded symbol still has to pass:

- explicit live-basket membership
- SOL/external inventory exclusion
- fresh valid bid/ask quote
- conservative spread threshold
- local regime/strategy permission
- fee-drag expected-edge clearance
- max open position and daily trade limits
- risk manager checks

The dashboard, observation loop, and operator digest are read-only. They show
the expanded basket and per-symbol skip reasons, but still report
`trade_permission=none`.

Next success metric:

```text
first closed expanded-symbol $5-$10 cycle with direct broker-backed net P/L
```

Profit aggregation remains unsafe until direct broker-backed evidence exists.
