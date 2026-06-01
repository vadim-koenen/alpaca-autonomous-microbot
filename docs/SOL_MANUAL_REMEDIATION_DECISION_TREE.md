# SOL MANUAL REMEDIATION DECISION TREE

**Purpose**: Provide a safe, explicit decision flow for the unresolved tiny open SOL position (trade_id 1f10a7cb-3fe5-4cbb-b990-f74c39529fc9).

**Current known facts (as of second overnight run, main e48f0b7 / later)**:
- SOL is still held on broker
- qty ≈ 0.0122504 (very small notional, ~$1 range historically)
- Likely entry: trade_id 1f10a7cb-3fe5-4cbb-b990-f74c39529fc9 (SOL-USD BUY @ 81.63)
- Direct fee and filled_value evidence for this lot remain unavailable in samples seen so far
- net_pnl_available = false
- profit_readout = unsafe_to_aggregate
- Risk increase = not approved

---

## Human Decision Flow

1. **Verify current position in Coinbase UI**
   - Confirm the exact qty and whether it is still "live" in the account.
   - Note any manual actions already taken outside the bot (transfers, manual closes, etc.).

2. **Do not assume the bot can or should close it**
   - The bot has never had reliable close capability demonstrated for this lot.
   - Automatic close or state clearing is prohibited.

3. **Do not auto-clear local state**
   - Never delete or "drop" the position record in state/coinbase/ without confirmed external evidence + human sign-off.

4. **If the user manually resolves the position in the Coinbase UI**
   - Take screenshots or export the relevant trade history.
   - Record the resolution method and date outside automated systems.
   - Only after external confirmation should any local state reconciliation be considered.

5. **Required evidence before considering the blocker cleared**
   - Direct non-null fee + filled_value for the entry leg (from broker payload)
   - Direct non-null fee + filled_value for any exit leg(s)
   - Independent confirmation that the position is no longer visible on the broker
   - Explicit human approval (recorded in handoff or separate log)
   - Updated ACTIVE_HANDOFF.md reflecting the new evidence level

---

## Prohibited Actions

- Automatic close via any script or scheduled job
- Automatic state clearing or "re-associated" marking
- Treating zero-qty journal rows as real fills or P/L
- Using avg_entry_price=0 from broker position objects as cost basis
- Any risk/sizing increase while the position and evidence gaps remain
- Local journal-only P/L aggregation for this lot

---

## When Human Approval Is Required

Any of the following actions require explicit human approval and a recorded rationale:

- Manually closing the position in the exchange UI
- Transferring the asset out of the trading account
- Clearing or modifying the local open position record
- Changing the "broker close capability" status in any reporting

**End of decision tree.** This document is the authoritative reference for safe handling of the open SOL reconciliation item. Update it when new direct evidence becomes available.