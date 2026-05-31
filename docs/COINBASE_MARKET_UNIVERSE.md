# P2-012A — Coinbase Market Universe (Scaffold)

This document describes the read-only market universe classification scaffold added in P2-012A.

## Purpose

Provide a safe, offline-capable way to ingest Coinbase product metadata and classify every tradable product (spot crypto, perpetuals, expiring futures, commodity-linked derivatives) without enabling live trading for any new product class.

## Key Safety Properties

- Every newly discovered product defaults to `allow_live_trading = False`.
- GOLD-PERP, SILVER-PERP, XAU, XAG, etc. are explicitly classified as `commodity_linked_derivative` (or `perpetual_future`) but **never enabled** for this account in the current controlled exploration.
- Current live symbols (BTC/USD, ETH/USD, SOL/USD) continue to be the only ones allowed under existing policy.
- No order placement, risk, or strategy code was modified to trade new products.
- All classification and eligibility data is preserved in raw form for future audit.

## Product Type Taxonomy (P2-012A)

- `spot_crypto`
- `perpetual_future`
- `expiring_future`
- `commodity_linked_derivative`
- `unknown`

Gold/silver-like products are force-classified into `commodity_linked_derivative` (or perpetual variant) and have `allow_live_trading=False`.

## Usage (Offline / Test)

```python
from coinbase_market_universe import CoinbaseMarketUniverse

u = CoinbaseMarketUniverse()
u.ingest_products(list_of_raw_products)   # from fixture or saved JSON
print(u.summarize())
print(u.get_product("GOLD-PERP"))
```

## Status Script

```bash
python3 scripts/coinbase_market_universe_status.py
python3 scripts/coinbase_market_universe_status.py --file path/to/saved_universe.json --json
```

The script is deliberately useful even with zero data so it can be run safely in any environment.

## Relationship to Future Work

This scaffold is a necessary stepping stone toward universal Coinbase coverage. Actual enablement of new product classes (including any commodity-linked or leveraged products) will require:
- Separate eligibility proof per product
- Direct broker-fact proof for fees/proceeds on those products
- Explicit policy change and safety review

None of that is performed in P2-012A.

---

P2-012A market universe component complete. No trading behavior changed.
