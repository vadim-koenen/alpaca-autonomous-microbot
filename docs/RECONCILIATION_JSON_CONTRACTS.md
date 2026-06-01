# RECONCILIATION JSON CONTRACTS

**Purpose**: This document defines the stable top-level JSON contracts for all reconciliation and reporting scripts. The goal is to make future automation, dashboards, and regression tests reliable by guaranteeing predictable field names and semantics.

**Current main HEAD reference**: e48f0b7 (after P2-018F)

**Important note on review-only branches**:
- `scripts/coinbase_full_fill_payload_capture.py` (P2-017D, review branch f8dc271) is **not present on main**. Its contract is documented below for future reference only. Do not import or execute it until it is properly reviewed and merged.
- `tests/test_local_review_gate_reconciliation_safety.py` (P2-018E, review branch e53b426) is **not present on main**. It is review-only.

All contracts below apply only to scripts that are merged into main.

---

## 1. scripts/coinbase_live_broker_reconciliation_probe.py

**Primary output fields (both default and --live-read-only modes)**:
- verdict (string)
- profit_readout (string)
- live_read_only (boolean)
- broker_calls_made (boolean)
- broker_read_successful (boolean)
- sol_on_broker (true / false / null)
- eth_on_broker (true / false / null)
- open_positions_on_broker (list)
- open_orders (list)
- recent_fills_sample (list)
- blockers (list of strings)
- next_action (string)
- credential_status (string)
- broker_error_type (string or null)
- errors (list)
- generated_at (ISO string)

**Contract guarantees**:
- `sol_on_broker` and `eth_on_broker` are null when no successful broker read occurred (unknown state semantics).
- Default mode (no --live-read-only) always sets live_read_only=false, broker_calls_made=false, broker_read_successful=false.

---

## 2. scripts/coinbase_broker_truth_summary.py

**Primary output fields**:
- verdict
- profit_readout
- broker_truth_available (boolean)
- live_read_only
- broker_calls_made
- broker_read_successful
- sol_on_broker
- eth_on_broker
- open_orders_count
- recent_fills_sample_count
- local_open_positions_count
- local_open_position_symbols (list)
- heartbeat_equity
- heartbeat_buying_power
- heartbeat_open_positions
- local_journal_recent_sol_eth_rows_count
- local_journal_recent_zero_qty_rows_count
- blockers (list)
- reconciliation_status
- schema_missing_fields (list or null)
- recommended_next_action
- generated_at

**Contract guarantees**:
- If the input probe JSON is missing the three explicit booleans (live_read_only, broker_calls_made, broker_read_successful), `schema_missing_fields` will list them.
- `broker_truth_available` is false unless `broker_read_successful` is explicitly true in the probe.

---

## 3. scripts/coinbase_fill_position_lifecycle_reconciliation.py

**Primary output fields**:
- verdict
- profit_readout
- broker_truth_available
- reconciliation_status
- current_open_positions_count
- current_open_position_symbols (list)
- current_sol_qty
- current_sol_market_value
- current_sol_price
- likely_current_sol_entry_trade_id
- likely_current_sol_entry_size
- likely_current_sol_entry_price
- likely_current_sol_entry_gross_cost_estimate
- current_sol_gross_unrealized_pnl_estimate
- fees_available_for_current_sol_entry (boolean)
- filled_value_available_for_current_sol_entry (boolean)
- net_pnl_available (boolean)
- recent_sol_fills_count
- recent_eth_fills_count
- recent_fills_with_trade_id_count
- recent_fills_missing_fee_count
- recent_fills_missing_filled_value_count
- zero_qty_journal_rows_are_excluded (always true)
- blockers (list)
- recommended_next_action
- generated_at
- probe_source

**Contract guarantees**:
- `net_pnl_available` is only true when both fee and filled_value are present and non-null for the matched entry.
- `profit_readout` remains "unsafe_to_aggregate" even when a size match is found, because direct fee/filled_value evidence is still required.

---

## 4. scripts/coinbase_fill_payload_field_discovery.py

**Primary output fields**:
- verdict
- profit_readout
- discovery_status
- broker_truth_available
- source_mode ("offline_probe_json")
- fills_inspected_count
- products_seen (list)
- matched_trade_id
- matched_trade_found (boolean)
- matched_trade_product_id
- matched_trade_side
- matched_trade_size
- matched_trade_price
- matched_trade_fee_present (boolean)
- matched_trade_fee_non_null (boolean)
- matched_trade_filled_value_present (boolean)
- matched_trade_filled_value_non_null (boolean)
- matched_trade_order_id_present (boolean)
- field_presence_summary (object)
- candidate_fee_fields (list)
- candidate_value_fields (list)
- candidate_order_id_fields (list)
- missing_direct_fee_count
- missing_direct_filled_value_count
- net_pnl_available (boolean)
- blockers (list)
- recommended_next_action
- generated_at
- probe_source

**Contract guarantees**:
- `discovery_status` will be "matched_trade_found_but_fee_and_value_missing" when the trade exists in the sample but fee/filled_value are null or absent.
- Candidate fields include nested paths when deeper structures are present in the input.

---

## 5. scripts/coinbase_pl_evidence_gate.py

**Primary output fields**:
- verdict
- profit_readout
- broker_truth_available (boolean)
- sol_on_broker (boolean or null)
- current_sol_qty
- matched_trade_id
- entry_fee_available (boolean)
- entry_filled_value_available (boolean)
- exit_fee_available (boolean)
- exit_filled_value_available (boolean)
- zero_qty_rows_excluded (always true)
- net_pnl_available (boolean)
- aggregation_allowed (boolean)
- scaling_allowed (boolean)
- required_next_evidence (list)
- blockers (list)
- recommended_next_action
- generated_at
- probe_source

**Contract guarantees**:
- `aggregation_allowed` and `scaling_allowed` are false while the SOL position is open or direct entry+exit fee/filled_value facts are missing.
- `zero_qty_rows_excluded` is always true (policy enforcement).

---

## 6. scripts/coinbase_reconciliation_dashboard.py

**Primary output fields (text + JSON)**:
- verdict
- profit_readout
- current_bot_blocker_state (string)
- sol_status (object with held_on_broker and qty)
- matched_trade (object)
- fee_value_availability (object)
- p_l_evidence_gate (object with net_pnl_available, aggregation_allowed, scaling_allowed)
- next_safe_action (string)
- explicit_warning (string containing "DO NOT SCALE RISK. DO NOT CLOSE AUTOMATICALLY.")
- generated_at
- probe_source

**Contract guarantees**:
- The `explicit_warning` field must always be present and contain the standard safety language.

---

## Review-Only Scripts (Not on Main)

These scripts exist only on review branches and are **not** covered by the above contracts until properly reviewed and merged:

- `scripts/coinbase_full_fill_payload_capture.py` (P2-017D, review branch f8dc271)
- Associated test file from P2-018E (review branch e53b426)

Their contracts will be added here only after explicit ChatGPT approval and merge.

---

**End of contract registry.** Update this document when new reconciliation scripts are added to main or when field names are intentionally changed (with migration notes).