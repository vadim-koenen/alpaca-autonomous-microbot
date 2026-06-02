# Read-Only Trend Advisory Layer

P2-024A adds a read-only trend/advisory registry for the Coinbase BTC/ETH
balance-relative pilot.

## Why This Exists

After the P2-023B restart, BTC/USD and ETH/USD both scanned as downtrend with
no allowed strategies, so the bot sat out. That was safe behavior. The bot did
not yet have a broad current-trend/news/sentiment layer to explain or normalize
context around that sit-out.

## Advisory Only

This layer cannot:

- place trades
- preview orders
- cancel, close, or modify orders
- change sizing
- override risk gates
- enable new symbols
- trade SOL/USD
- trigger derivatives, perps, prediction-market, margin, or leverage execution

The schema always emits:

```text
mode=read_only_advisory
trade_permission=none
risk_increase=not_approved
eligible_for_live_trade_trigger=false
```

## Sources

P2-024A defines source registry entries for:

- Coinbase local market context from existing local regime/candle/WebSocket
  derived observations
- CoinGecko trending coins/categories, fixture-backed initially
- CoinDesk RSS/news headlines, fixture-backed initially
- future sources disabled by default

Network fetching is not used by default. Tests require no API keys and do not
read `.env`.

## Signal Behavior

Local market context remains primary. If local context says downtrend and the
strategy list is empty, the advisory action is `avoid` or `watch`, not buy.

Positive external trend/news can only become `confirm_only`; it cannot create a
live trade permission and cannot override risk gates or fee-drag checks.

BTC/USD and ETH/USD are the only live advisory symbols. SOL/USD context may be
noted as excluded, but it is not emitted as a live advisory symbol.

## Future Path

Trend signals can become one input into entry scoring only after multiple
broker-backed BTC/ETH pilot cycles are net positive after fees, spread, and
slippage buffer. Until then, broker-backed net P/L remains the success metric.
