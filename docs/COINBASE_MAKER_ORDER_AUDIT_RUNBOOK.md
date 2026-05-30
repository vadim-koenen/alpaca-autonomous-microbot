# ADVISORY ONLY — read-only analysis, no live trading calls.

# Coinbase Maker Order Audit Runbook — P2-001F

## Overview

The Coinbase Maker Order Audit (`scripts/coinbase_maker_order_audit.py`) is a read-only diagnostic tool that determines whether the bot's entries for the `coinbase_exploration` strategy are likely maker-priced (passive) or taker-priced (aggressive) entries.

This is critical for understanding fee drag. Maker fills at Coinbase (at the $1 notional tier) are approximately 0.6%, while taker fills are approximately 1.2%. A round-trip taker entry and exit requires a ~2.4% gross move just to break even, whereas a maker entry and exit only requires ~1.2%. This audit uses pricing as an advisory proxy to estimate which tier a fill likely landed in.

---

## Quick Start

```bash
# 1. Run the audit
python3 scripts/coinbase_maker_order_audit.py

# 2. Run unit tests
python3 -m pytest tests/test_coinbase_maker_order_audit.py -v

# 3. Validate syntax
python3 -m py_compile scripts/coinbase_maker_order_audit.py
```

---

## What It Analyzes

### 1. Order Type Distribution
- Counts how many entries are `limit` vs `market` vs `unknown`.
- Confirms whether `passive_limit_entries=true` is actually being applied.

### 2. Pricing Classification
- **likely_maker**: Fills where `fill_price <= mid`. These orders were placed passively at or below the midpoint and likely waited for the market to come to them.
- **likely_taker**: Fills where `fill_price >= ask` (or close to it). These orders were likely aggressive or the market moved against the limit order before it was filled, resulting in a taker-priced execution.
- **unknown**: Entries where bid/ask quote data is missing from the journal.

### 3. Fee Tier and Break-Even Estimation
- Estimates the percentage of trades likely landing in the 0.6% maker tier vs the 1.2% taker tier based on the pricing proxy.
- Projects the round-trip break-even gross move required for each classification.

### 4. Per-Symbol Breakdown
- Breaks down likely passive-priced performance by symbol (BTC/USD, ETH/USD, SOL/USD).
- Helps identify if certain symbols are more prone to aggressive pricing (slippage).

---

## Limitations

- **No Definitive Fee Data**: Journal contains BUY PLACED rows and quote context, but does not contain definitive Coinbase maker/taker liquidity flags for each fill. Classification is an advisory proxy, not proof of actual fee tier.
- **Fill Price Proxy**: The audit assumes the `price` field in `PLACED` rows (which is the limit price) is the final fill price. In highly volatile markets, the actual fill could differ slightly if not using `post-only`.
- **Quote Latency**: The classification depends on the `bid` and `ask` logged at the time of order placement.
- **Exit Fees**: This audit focus on entries. Exits (which are often time-based) may have different pricing profiles.
- **Post-Only**: The bot logic may intend to use `post-only`, but the journal does not explicitly confirm if Coinbase accepted the order as `post-only` unless that flag is inspected in the API response.

---

## Troubleshooting

### "No entries found"
- Ensure `journal_coinbase_crypto.csv` contains rows with `strategy=coinbase_exploration` and `mode=live`.
- Check if any trades have been placed recently.

### "High percentage of likely_taker"
- This suggests that either:
  - `passive_limit_entries` is not working as expected.
  - The market is moving too fast for the limit orders to remain passive.
  - The spread is extremely tight, causing midpoint orders to be filled aggressively.

---

**Last Updated:** 2026-05-30 (P2-001F implementation)
**Status:** ACTIVE — Advisory analysis.
