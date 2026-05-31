# P2-012B — Coinbase Multi-Asset Spot Expansion Plumbing (Scaffold)

This document describes the controlled plumbing added in P2-012B to prepare for intentional expansion of live spot crypto symbols on Coinbase, while preserving the strict "controlled-aggressive" posture (micro notional, tiny exposure, no leverage).

## Goals

- Wire real prediction telemetry into every live scan/proposal decision so we can measure candidate quality, skip reasons, regime behavior, and (later) outcome hit rates.
- Provide a conservative, read-only helper (`CoinbaseMarketUniverse.get_spot_crypto_candidates`) that can classify a large product universe and produce a ranked list of *potential* additional spot symbols.
- Make all new candidates explicitly **disabled for live trading** (`allow_live_trading=False`) by default.
- Give operators and future patches clear visibility (via scripts and tests) into what would be included vs. excluded and why.
- Never auto-enable any new symbol for orders, never increase notional/exposure, never touch TP/SL/hold time, never enable perps/futures/leverage/gold/silver/commodities.

## Key Safety Properties (P2-012B)

- Telemetry writes use `safe_log_*` wrappers — exceptions are swallowed; trading path is unaffected.
- The multi-asset helper **only** returns candidates that are:
  - `product_type == "spot_crypto"`
  - `product_enabled` and not `trading_disabled`
  - quote in supported set (USD/USDC/USDT etc.)
  - `leverage_allowed == False` and no max_leverage
  - not matching gold/silver/XAU/XAG or PERP/FUTURE patterns
- Every newly discovered candidate has `allow_live_trading=False` (and `is_currently_configured_live=False` unless it matches the current `live_symbols` in config).
- Current live set (BTC/USD, ETH/USD, SOL/USD from `config_coinbase_crypto.yaml`) remains the sole source of truth for what actually trades.
- No order placement, risk changes, or config mutation occurs.

## Usage

```bash
# Current configured + any cached product metadata
python3 scripts/coinbase_multi_asset_candidates.py

# With a saved product universe (from external List Products call or fixture)
python3 scripts/coinbase_multi_asset_candidates.py --products-file /tmp/coinbase_products.json --json

# Prediction telemetry (now populated from real scans)
python3 scripts/coinbase_prediction_status.py --json
```

The `get_spot_crypto_candidates()` method can also be called from Python for custom reporting or future enablement logic (under separate patch + review).

## What This Patch Does NOT Do

- Does not increase any caps or notionals.
- Does not change which symbols actually receive proposals that can turn into orders.
- Does not enable leveraged, perpetual, futures, margin, options, or commodity products.
- Does not write to the blocked fill logger.
- Does not modify ACTIVE_HANDOFF.md.
- Does not relax any existing risk or runtime safety checks.

## Next Steps (Future Patches, After Proof)

- Human review of candidate list + explicit addition to `live_symbols` (or a new `approved_expansion_symbols`).
- Per-symbol eligibility + broker-fact proof (fees, proceeds, stable IDs) for the new symbols.
- Gradual rollout under the same micro-cap / controlled exploration discipline.
- Only after all of the above would any new symbol be allowed to generate live orders.

---

P2-012B multi-asset spot plumbing + live telemetry integration complete.
No new live-order symbols enabled. All invariants preserved.
