# EXTERNAL SIGNAL LAYER SAFETY GATE

**Purpose**: Preserve the long-term plan for syndicated crypto/news/trend context without implementing any of it yet.

**Status**: This capability is **not enabled** and must not be enabled until broker reconciliation and direct P/L truth are complete.

---

## Why It Is Not Allowed Yet

- Broker truth and P/L evidence gate are not yet at L4/L5 for the open SOL position.
- External signals could easily be misinterpreted as direct trading triggers.
- Adding any external data source before the core evidence requirements are met would violate the established safety order.

---

## Core Constraints (Non-Negotiable)

- External signals are **advisory-only**.
- They must never produce direct buy/sell triggers.
- They must never bypass or relax risk, sizing, cap, or allocation gates.
- They must never override strategy decisions.
- They must remain **disabled by default** (opt-in only after full validation).
- No automatic consumption of signals into live trading paths is permitted.

---

## Intended Future Sequence (When Enabled)

1. Source registry (list of allowed, vetted feeds only)
2. Read-only collector (no write side effects)
3. Context signal aggregator (produces weak signals only)
4. Optional weak watchlist / skip / observe input (after explicit validation and gate checks)
5. Never a direct trading decision

---

## Candidate Future Sources (For Reference Only)

- CoinGecko (market data)
- CoinDesk RSS / news
- Financial Modeling Prep crypto news endpoints
- LunarCrush (social/sentiment) — only after rigorous validation

All sources must be re-validated for current terms, rate limits, and data quality before any use.

---

## Enforcement

Any future patch that attempts to:
- Add network calls for external data
- Wire signals into scan/proposal/decision paths
- Relax risk gates based on external context

...must first demonstrate that the P/L evidence gate (L4 minimum for the assets being traded) has been passed, and must pass a full ChatGPT review against this document.

**End of safety gate.** This document is the authoritative reference for the external signal layer. It must be updated (and the gate re-enforced) before any implementation work begins.