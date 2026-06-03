# Read-Only Market Context Registry

P2-025B adds an offline, fixture-backed market/trend context registry for the
controlled Coinbase spot basket:

- BTC/USD
- ETH/USD
- ADA/USD
- AVAX/USD
- DOGE/USD
- LINK/USD
- LTC/USD

SOL/USD remains external/staked/non-bot inventory and is excluded from
bot-tradable context.

## Purpose

The registry models market and trend inputs without giving them trading
authority. It prepares a clear source map for future live-read-only evidence,
product metadata, order-book depth, and external trend research while preserving
all existing strategy, risk, sizing, and execution gates.

## Source Types

The registry includes source records for:

- `coinbase_market_data`
- `coinbase_product_metadata`
- `coinbase_level2_order_book_future`
- `coinbase_order_preview_future`
- `coingecko_trending`
- `coingecko_markets`
- `crypto_news_sentiment_future`
- `all_asset_opportunity_registry_future`

Each source reports category, status, network/auth needs, trading authority,
allowed use, forbidden use, freshness/update cadence, and symbol coverage or
mapping notes.

## Authority Boundary

Every source and symbol context has:

```text
trading_authority=none
trade_permission=none
```

External market, trend, news, and sentiment context cannot emit or authorize:

- buy
- sell
- trade
- order
- size increase
- risk override
- strategy override
- execution override

Advisory labels are limited to:

- `confirm_only`
- `watch`
- `avoid`
- `trend_attention`
- `insufficient_data`

## Coinbase Context

Coinbase market data and product metadata may become execution-quality inputs,
but they still cannot place orders or override risk. Coinbase order preview
remains future/disabled here. Preview PNL is not final profitability evidence
because fees and slippage require separate modeling.

## External Context

CoinGecko and future news/sentiment sources are advisory-only. They can help an
operator notice trends, but they cannot trigger trades, change sizing, change
risk, override strategy gates, or bypass execution-quality checks.

## Current Integration

P2-025B remains standalone. Dashboard/operator digest integration should wait
until the next patches prove product metadata, preview/cost, and maker-first
gates can stay read-only or explicitly risk-gated.

## Next Likely Patches

- P2-025C Coinbase product metadata fixture/adapter
- P2-025D mandatory pre-trade preview/cost gate
- P2-025E maker-first/post-only feasibility
- P2-025F WebSocket level2 design/offline simulator
- P2-026 all-asset opportunity registry read-only
