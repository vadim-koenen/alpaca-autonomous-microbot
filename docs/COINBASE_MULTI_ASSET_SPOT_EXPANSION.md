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

## P2-012C: Opt-in Micro-Size Live Expansion (Config-Gated)

P2-012C adds the actual (but strictly opt-in) live trading path for additional Coinbase **spot crypto only** symbols at the existing micro size.

### Exact Config Fields Added (all inside `crypto:`)

```yaml
  multi_asset_spot:
    enabled: false                    # DEFAULT — safe, no behavior change
    max_symbols: 8
    allowed_quote_currencies: [USD, USDC]
    exclude_product_types: [perpetual_future, expiring_future, commodity_linked_derivative, unknown]
    max_spread_bps: 50
    allow_live_trading_symbols: []    # THE EXPLICIT ALLOWLIST — nothing else will ever trade
    max_new_symbols_per_day: 2
```

- **enabled: false** (default) → identical behavior to P2-012B and earlier. Only `live_symbols` (BTC/ETH/SOL) are used.
- **allow_live_trading_symbols** is the final hard gate. A symbol must be listed here **and** pass every filter in the resolver (spot_crypto, not disabled, good quote, no leverage, no gold/silver/perp/future/commodity, spread ok) before it is returned for live proposal generation.
- Micro notional, total exposure, TP/SL (1.5%/3%), hold time (90m), and all other risk fields are **unchanged** — new symbols inherit the existing caps.
- Prediction telemetry is **always on** for every symbol scanned (base + any expanded).

### How to Preview (Dry-Run) Before Enabling

```bash
# Shows exactly what would be live right now under current config + any cached products
python3 scripts/coinbase_multi_asset_candidates.py --show-expansion

# With full product metadata (recommended before enabling)
python3 scripts/coinbase_multi_asset_candidates.py --products-file /tmp/coinbase_products.json --show-expansion
```

The script prints the "LIVE EXPANSION DRY-RUN" section with effective symbols, newly selected, and exclusions with reasons.

### Runtime Behavior

- When disabled (default): `strategy_router` uses exactly the original `live_symbols`. One debug log notes the disabled state. No other changes.
- When enabled + allowlist populated: the resolver augments the live set for that scan cycle only (per the config). Clear INFO logs show the expansion. All new symbols go through the exact same proposal → risk → order path (and emit telemetry).
- Hard filters are re-applied on every resolution using the `CoinbaseMarketUniverse` classification (P2-012B + P2-012C extensions).
- Failures in resolution are non-fatal (falls back to base symbols).

### Safety Guarantees (Reinforced in P2-012C)

- Spot crypto **only**.
- No leverage, perps, futures, gold, silver, commodities, or derivatives ever receive live proposals.
- Explicit allowlist required — classification alone is never sufficient for live trading.
- No increase to any notional, exposure, TP/SL, or hold time.
- Fill logger remains fully blocked.
- `ACTIVE_HANDOFF.md` untouched.
- All new/expanded symbols produce prediction telemetry rows (candidate or skipped) exactly like BTC/ETH/SOL.
- Tests (including `test_coinbase_multi_asset_live_expansion.py`) prove default safety and correct opt-in behavior.

### To Actually Enable (Example)

Edit `config_coinbase_crypto.yaml`:

```yaml
  multi_asset_spot:
    enabled: true
    allow_live_trading_symbols:
      - ADA/USD
      - AVAX/USD
    # other fields as needed
```

Then run the dry-run script, review the output, start in dry_run mode if desired, then live.

Only after the allowlist change + review does any new symbol generate live orders at micro size.

---

P2-012C opt-in multi-asset spot live expansion complete.
Default behavior unchanged. Explicit allowlist + all hard filters required for expansion.
Prediction telemetry remains enabled. Fill logger blocked. All prior invariants preserved.
