# EXTERNAL SIGNAL CONTEXT PLAN (Advisory Layer)

This document preserves the long-term plan for incorporating external syndicated crypto, news, and trend context into the bot.

**Critical Status**: This layer is **advisory-only** and must remain so until broker reconciliation, direct fill/proceeds/fees truth, and risk gates are solid.

## Purpose

Provide the bot with higher-quality, structured external context (beyond pure price/volume) to improve skip/observe decisions and eventually support weak watchlist signals — **without** bypassing risk controls or directly triggering trades.

## Target Sources (Initial Registry)

- CoinGecko trending / market data
- CoinDesk RSS / news
- Financial Modeling Prep crypto news
- LunarCrush social sentiment / social volume
- Other reputable, rate-limited sources as they prove useful

## Target Architecture (High-Level, Future)

1. **Source Registry** (`config/external_sources.yaml` or similar)
   - List of sources with rate limits, auth method (if any), and reliability tier.

2. **Read-Only Collector**
   - Periodic, cached fetching of raw signals.
   - Strict rate limiting and error handling.
   - No writes to production journal or state except a dedicated context cache.

3. **Context Signal Aggregator**
   - Normalizes signals into a common schema (symbol, signal_type, strength, source, timestamp, confidence).
   - Produces a lightweight context snapshot per symbol or market regime.

4. **Optional Weak Input Layer** (only after heavy validation)
   - Can feed into skip/observe logic or a low-confidence watchlist.
   - Must be explicitly gated behind feature flags.
   - Must never override risk gates, position limits, or daily loss stops.

## Strict Guardrails (Non-Negotiable)

- **Advisory only** until further notice:
  - No direct buy/sell triggers.
  - No sizing, cap, or risk changes.
  - No strategy override or bypass.
  - No relaxation of existing reconciliation or safety requirements.

- All external signals start with **zero weight** in decision making.
- Any integration must be preceded by:
  - Successful live broker truth runs (P2-015x series).
  - Proven direct fill/proceeds/fees reconciliation.
  - Explicit ChatGPT approval for the specific integration step.

## Current Recommended Sequence (2026)

1. Complete and validate live broker reconciliation probe runs (P2-015x).
2. Achieve reliable direct broker facts for positions, orders, and fills.
3. Build minimal read-only collector + aggregator (read-only, cached, rate-limited).
4. Run in shadow mode for weeks/months while comparing against actual bot behavior.
5. Only after strong evidence of value and no negative side-effects: propose gated, low-weight usage in skip/observe paths.

## Non-Goals (for the foreseeable future)

- Real-time trading signals from social/news.
- Automated position sizing based on sentiment.
- Any mechanism that could increase aggressiveness without proven edge + reconciliation.

## Next Concrete Steps (when ready)

- Define minimal signal schema.
- Implement a thin collector for 1–2 sources behind a feature flag.
- Add basic tests and safety assertions (rate limits, no secrets leakage, read-only).
- Produce shadow reports for review.

This document exists so that future work does not require rediscovering the original intent or re-litigating the safety boundaries every time external context is discussed.

---
*Created as part of P2-016A planning docs. Do not implement collectors yet.*