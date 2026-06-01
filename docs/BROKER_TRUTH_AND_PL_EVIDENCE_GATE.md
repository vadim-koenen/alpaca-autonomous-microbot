# BROKER TRUTH AND P/L EVIDENCE GATE

**Purpose**: This document defines the minimum evidence ladder required before `profit_readout` can move beyond `unsafe_to_aggregate` for the Coinbase controlled exploration bot.

**Last updated**: Overnight autonomy run (P2-018A)  
**Current main HEAD reference**: 4410fe6 (P2-017C complete)  
**Status as of this document**: profit_readout remains `unsafe_to_aggregate`.

---

## Current Live State (as of P2-017C / start of overnight run)

- `broker_truth_available`: true
- `SOL held on broker`: true (qty = 0.0122504, market_value ≈ 1.0134755, current_price ≈ 82.715)
- Matched trade: `trade_id=1f10a7cb-3fe5-4cbb-b990-f74c39529fc9` (SOL-USD BUY, size=0.0122504, price=81.63)
- `fee` / `filled_value`: still missing or explicitly null in available samples
- `net_pnl_available`: false
- `profit_readout`: `unsafe_to_aggregate`
- Risk increase: **not approved**
- Zero-qty journal rows: must never be treated as real fills

---

## Evidence Levels (Ladder)

| Level | Description | P/L Status | Scaling / Aggregation Allowed? |
|-------|-------------|------------|--------------------------------|
| **L0** | Local journal only (no broker confirmation) | Unsafe | No |
| **L1** | Broker position read (qty, market_value, side) | Useful for monitoring only | No |
| **L2** | Broker fill sample with trade_id + size + price | Gross estimates only (provisional) | No |
| **L3** | **Direct non-null fee + filled_value for entry leg** | Entry cost truth established | Still **No** (exit leg required) |
| **L4** | **Direct non-null fee + filled_value for exit leg** | Realized P/L truth for closed trades | **Yes** for aggregation of completed cycles only |
| **L5** | Repeated validated closed trade lifecycles (entry + exit) with direct facts | Eligible for statistical aggregation | Yes, with conservative caps |

**Current achieved level**: Between L2 and L3 (matched trade exists in sample, but `fee` and `filled_value` remain unavailable).

---

## Allowed Readouts

- `gross_unrealized_estimate` (provisional, using matched BUY cost)
- `gross_cost_estimate`
- Direct per-fill `fee` and `filled_value` (proceeds) **only when explicitly non-null from broker payload**

## Prohibited

- Treating zero-qty journal rows as fills or P/L contributors
- Using `avg_entry_price=0` from broker position objects as cost basis
- Using local journal rows alone as "direct broker truth"
- Any risk/sizing/cap increase while a blocker exists
- Automatic closing or state clearing of the open SOL position

---

## Manual Remediation Policy

The open SOL position (trade_id `1f10a7cb-...`) remains an unresolved reconciliation item.

- No automatic close
- No automatic state clearing or "dropped" marking
- Any close, remediation, or manual wallet reconciliation **requires explicit human approval** outside automated systems
- Any such action must be logged with rationale and evidence level at the time of the decision

---

## Gate Enforcement

Any future patch or script that attempts to:

- Move `profit_readout` beyond `unsafe_to_aggregate`
- Allow risk/sizing increases
- Produce "realized P/L" numbers
- Enable aggregation or outcome scoring on live trades

...must first pass through this evidence gate and demonstrate L4 (or higher) facts for the specific trades being measured.

Until then, all profit-related reporting must explicitly state `unsafe_to_aggregate`.

---

**End of gate document.** This is the authoritative reference for "how much broker truth is enough?" for this bot.