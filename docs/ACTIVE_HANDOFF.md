# ACTIVE HANDOFF — Alpaca/Coinbase Autonomous Trading Bot

## P2-022D review — numeric broker-backed one-cycle P/L readout

**Branch:** `review/p2-022d-numeric-broker-backed-cycle-readout`

P2-022D adds an offline numeric P/L readout layer for direct Coinbase
broker-backed evidence cycles.

Current good state:

- P2-022C2 is merged on `main` at `586b5fb`.
- The real ETH cycle `real-ethusd-029` resolves as L4 direct broker evidence:
  - `verdict=EVIDENCE_RESOLVED`
  - `profit_readout=measured_broker_backed_limited`
  - `cycles_evaluated=1`
  - `complete_direct_cycles=1`
  - entry/exit direct order IDs, fill IDs, fees, and filled value/proceeds are
    available as broker-backed evidence.
- Numeric realized P/L still requires numeric-safe local extraction of
  `filled_value`/proceeds and fee amounts.
- Redacted presence markers prove completeness but are not numeric values.

P2-022D updates:

- Adds `scripts/coinbase_broker_backed_pnl_readout.py`.
- Computes limited-cycle gross P/L, total fees, and net P/L with `Decimal` only
  when direct numeric broker values are present.
- Blocks numeric P/L when values are redacted presence markers.
- Keeps local journal P/L advisory only.

Preserved truth:

- `profit_readout_real_current=unsafe_to_aggregate` until numeric-safe broker
  values are accepted for real-current reporting.
- `scaling_allowed=false`
- risk increase not approved
- no live broker calls
- no `--live-read-only` execution during verification
- no `.env` or secrets
- no order/cancel/close/modify
- no `logs/coinbase_fills.csv` writes
- no `append_coinbase_fill_row` activation
- no risk/notional/symbol/config/strategy expansion

---

## P2-022C2 review — adapt one-cycle read-only payload

**Branch:** `review/p2-022c2-adapt-one-cycle-read-only-payload`

P2-022C2 adapts the clean one-cycle Coinbase read-only capture payload into the
offline broker evidence adapter and profit evidence resolver schemas.

Current good state:

- P2-022C1 is merged on `main` at `d39ef3e`.
- The one-cycle human-approved read-only capture for `real-ethusd-029` succeeded
  for both entry and exit broker reads after the probe compatibility fix.
- Entry and exit both showed direct broker-backed order/fill evidence presence:
  filled size, average filled price, filled value, total fees, settlement, per-fill
  fees, and stable fill identifiers.
- The remaining blocker is offline-only: the clean payload used
  `cycles[].entry_broker_payload_redacted` and
  `cycles[].exit_broker_payload_redacted`, while the adapter/resolver previously
  expected normalized `evidence_cycles`.
- No more live broker reads are needed until this adapter mapping is verified
  offline.

P2-022C2 updates:

- `scripts/coinbase_read_only_broker_fact_probe.py` keeps `--output json`
  stdout as pure JSON by sending the live-read-only warning banner to stderr.
- `scripts/coinbase_broker_evidence_adapter.py` recognizes
  `schema_version=p2-022c.one_cycle_read_only_payload.v1`.
- `scripts/coinbase_profit_readout_evidence_resolver.py` can evaluate that
  payload shape directly in offline mode.

Preserved truth:

- `profit_readout_real_current=unsafe_to_aggregate` until this branch is merged
  and offline resolver verification passes.
- Fixture-only one-cycle readout may become `measured_broker_backed_limited`.
- `aggregation_allowed_real_current=false`
- `scaling_allowed=false`
- risk increase not approved
- no live broker calls
- no `--live-read-only` execution during verification
- no `.env` or secrets
- no order/cancel/close/modify
- no `logs/coinbase_fills.csv` writes
- no `append_coinbase_fill_row` activation
- no risk/notional/symbol/config/strategy expansion

---

## P2-022C1 review — read-only probe compatibility fix

**Branch:** `review/p2-022c1-fix-read-only-probe-compatibility`

P2-022C1 fixes the Coinbase read-only broker fact probe compatibility issue found
during the first one-cycle human-approved capture attempt.

Current good state:

- P2-022B is merged on `main` at `2b89d82`.
- The paired evidence request builder is ready and can produce checklist-ready
  BTC/ETH paired order requests.
- The attempted one-cycle capture for `real-ethusd-029` failed before broker
  evidence was captured because:
  - the checklist emitted stale probe syntax using `--json`;
  - `scripts/coinbase_read_only_broker_fact_probe.py` passed unsupported
    `dry_run=True` to the current `BrokerCoinbase()` constructor.
- P2-022C1 updates planned checklist probe commands to use `--output json`.
- P2-022C1 updates the probe to construct `BrokerCoinbase()` only after explicit
  `--live-read-only` opt-in and to report structured read-only safety fields.

Next step after merge:

- Retry exactly one human-approved read-only Coinbase evidence capture cycle.
- Keep capture limited to listed BTC/ETH order IDs and date windows.
- Redact any captured broker payload before offline adapter/resolver use.

Preserved truth:

- `profit_readout_real_current=unsafe_to_aggregate`
- `aggregation_allowed_real_current=false`
- `scaling_allowed=false`
- risk increase not approved
- no live broker calls during implementation or tests
- no `--live-read-only` execution during verification
- no `.env` or secrets
- no order/cancel/close/modify
- no `logs/coinbase_fills.csv` writes
- no `append_coinbase_fill_row` activation
- no risk/notional/symbol/config/strategy expansion

---

## P2-022B review — paired Coinbase evidence request builder

**Branch:** `review/p2-022b-paired-evidence-request-builder`

P2-022B turns the successful one-off `/tmp` paired evidence request generation
into a deterministic offline repo script:

- `scripts/coinbase_paired_evidence_request_builder.py`
- `docs/PAIRED_COINBASE_EVIDENCE_REQUEST_BUILDER.md`
- `tests/test_coinbase_paired_evidence_request_builder.py`

Latest good state:

- `main` includes P2-021C5.
- Live execution is repaired.
- SOL/USD is external/staked, excluded from active recovery, and excluded from
  Coinbase candidate cycles.
- Manual paired discovery succeeded with real BTC/ETH rows:
  `uuid_btc_eth_rows=60` and `paired_cycles_count=8`.
- The generated request can pass the human-approved read-only capture checklist.

The next step after merge is a human-approved read-only Coinbase broker evidence
capture for the listed BTC/ETH entry and exit order IDs, followed by redaction,
offline adapter normalization, and offline profit evidence resolution.

Preserved truth:

- `profit_readout_real_current=unsafe_to_aggregate`
- `aggregation_allowed_real_current=false`
- `scaling_allowed=false`
- risk increase not approved
- no live broker calls
- no `--live-read-only` execution
- no `.env` or secrets
- no order/cancel/close/modify
- no state/log mutation outside explicit output path
- no `logs/coinbase_fills.csv` writes
- no `append_coinbase_fill_row` activation
- no risk/notional/symbol/config/strategy expansion

---

## P2-021C5 review — exclude external inventory from Coinbase candidates

**Branch:** `review/p2-021c5-exclude-external-inventory-candidates`

P2-021C5 removes authoritative external/staked inventory symbols from Coinbase
live entry candidate evaluation. After P2-021C4, `manual_review_position_open`
is resolved and broker recovery no longer rehydrates user-staked SOL/USD into
active `open_positions`, but SOL/USD could still consume scan/risk cycles and
produce safe-but-wasteful journal rows such as `already have open position in
SOL/USD`.

The new candidate filter excludes a symbol only when
`state/coinbase/external_inventory.json` proves all of:

- `external_inventory_classification=external_staked_position`
- `staked_external_position=true`
- `bot_inventory=false`
- `tradable_by_bot=false`
- `manual_close_allowed=false`
- `blocks_new_entries=false`

BTC/USD and ETH/USD remain eligible candidates. Missing or malformed external
inventory fails safely by excluding nothing. True active bot-owned unresolved
positions still flow through the existing blocker/risk logic.

Preserved truth:

- `profit_readout_real_current=unsafe_to_aggregate`
- `aggregation_allowed_real_current=false`
- `scaling_allowed=false`
- risk increase not approved
- no live broker calls
- no `--live-read-only`
- no `.env` or secrets
- no order/cancel/close/modify
- no auto-close or auto-sell SOL
- no risk/notional/symbol/config expansion
- no `logs/coinbase_fills.csv` writes
- no `append_coinbase_fill_row` activation

---

## P2-021C4 review — external-inventory-aware broker recovery

**Branch:** `review/p2-021c4-external-inventory-aware-broker-recovery`

P2-021C4 fixes the post-P2-021C3 restart path where broker-position recovery
could rehydrate the user-staked SOL/USD position back into active
`open_positions` with `recovery_source=broker_position`.

The authoritative classification remains:

- `staked_external_position=true`
- `external_inventory_classification=external_staked_position`
- `tradable_by_bot=false`
- `manual_close_allowed=false`
- `bot_inventory=false`
- `blocks_new_entries=false`

Recovery now treats matching broker SOL observations as external inventory only:
no active open-position restore, no broker-recovered active position, no
journal-reassociated active position, no SOL close/sell/remediation attempt, and
no P/L inference from SOL.

Watchdog/operator status now distinguish historical manual-review rows from a
current active SOL entry blocker when authoritative external inventory exists.

Preserved truth:

- `profit_readout_real_current=unsafe_to_aggregate`
- `aggregation_allowed_real_current=false`
- `scaling_allowed=false`
- risk increase not approved
- no live broker calls
- no `--live-read-only`
- no `.env` or secrets
- no order/cancel/close/modify
- no risk/runtime/config/background changes
- no `logs/coinbase_fills.csv` writes
- no `append_coinbase_fill_row` activation

Post-merge verification should restart or run the normal operator status checks
only under existing operator procedures and confirm `open_positions` remains
bot-inventory-only while SOL/USD stays in `external_inventory.json`.

---

## P2-021C3 review — manual-review blocker remediation

**Branch:** `review/p2-021c3-manual-review-blocker-remediation`

P2-021C3 adds an offline, local, operator-approved state-normalization path for
stale `manual_review_position_open` blockers caused by proven external/staked
non-bot-tradable SOL inventory.

Live problem: Coinbase can be running with buying power and still produce no
entries because `state/coinbase/open_positions.json` contains a stale SOL/USD
manual-review blocker with `broker_close_capability_unconfirmed`.

Safety semantics:

- Do not close SOL.
- Do not sell SOL.
- Do not treat SOL as bot inventory.
- Do not infer realized P/L from SOL.
- No risk increase, notional increase, symbol expansion, leverage, or margin.
- `profit_readout_real_current=unsafe_to_aggregate`
- `aggregation_allowed_real_current=false`
- `scaling_allowed=false`

The remediation script defaults to dry-run. Apply requires
`--apply --operator-approved-external-inventory-normalization`, creates a
timestamped backup, moves proven external/staked SOL out of active bot
`open_positions`, and preserves an audit record in local external inventory.

---

## P2-021C2 (stacked on P2-021C review branch) — anti-stale manual-review blocker watchdog

**Branch:** `review/p2-021c2-anti-stale-manual-review-blocker-watchdog` (stacked on review/p2-021c-read-only-evidence-capture-bridge at dc34054; P2-021C not yet merged to main)

P2-021C2 adds a read-only, offline anti-stale watchdog (`scripts/coinbase_stale_blocker_watchdog.py`) that detects when a `manual_review_position_open` entry blocker has aged beyond a configurable threshold (default 180 minutes).

It computes blocker age, counts, severity, and distinguishes:
- True unresolved bot-owned positions (escalates to STALE_BLOCKER_REQUIRES_OPERATOR_ACTION, still blocks trading).
- External/staked/non-bot locked inventory (reported as external; never auto-closed or treated as bot inventory).
- Stale state bugs (repeated blocks with no actual open manual-review position).

The watchdog is integrated into the operator status aggregator for visibility.

**Current live problem addressed:**
The bot was running with buying power but 0 trades all day due to repeated `ENTRY_BLOCKED reason=manual_review_position_open`, with no age tracking or escalation in the main status tools.

**Preserved truth (no relaxation of gates):**
- `profit_readout_real_current=unsafe_to_aggregate`
- `aggregation_allowed_real_current=false`
- `scaling_allowed=false`
- risk increase not approved
- staked SOL remains external locked inventory, not bot inventory
- No auto-close of any position
- No auto-clear of unresolved bot-owned positions
- No live broker calls in this patch or verification

This patch does not unblock trading. It only makes indefinite silent suspension impossible by forcing explicit stale-blocker state and operator action requirements. It connects directly to the P2-021C read-only evidence capture bridge for the safe, human-approved path forward.

---

## P2-021C review — human-approved read-only evidence capture bridge

**Branch:** `review/p2-021c-read-only-evidence-capture-bridge`

P2-021C adds an offline checklist bridge for a future human-approved Coinbase
read-only capture. It does not call live broker APIs, does not execute
`--live-read-only`, does not import broker clients, does not read `.env`, and
does not write runtime state/logs.

The bridge documents the exact future order IDs, product IDs, date windows,
direct broker fields, redaction requirements, adapter input path, adapter
command, and resolver command needed to feed real captured facts into P2-021B
and P2-021A after explicit human approval.

Preserved current truth:

- `profit_readout_real_current=unsafe_to_aggregate`
- `aggregation_allowed_real_current=false`
- `scaling_allowed=false`
- risk increase not approved
- staked SOL remains external locked inventory, not bot inventory

---

## P2-021A review — profit readout direct evidence resolver

**Branch:** `review/p2-021a-profit-readout-evidence-resolver`

P2-021A adds an offline-only profit readout evidence resolver:

- `scripts/coinbase_profit_readout_evidence_resolver.py`
- direct broker evidence fixtures under `tests/fixtures/coinbase_profit_readout/`
- `tests/test_coinbase_profit_readout_evidence_resolver.py`
- `docs/PROFIT_READOUT_EVIDENCE_RESOLUTION.md`

The resolver keeps `profit_readout=unsafe_to_aggregate` unless closed bot-owned
entry+exit cycles contain direct order ids, fill/trade ids, direct fees, and
direct proceeds/filled_value for both legs.

Complete direct broker evidence can produce:

- `profit_readout=measured_broker_backed_limited`
- `aggregation_allowed=true` for the supplied closed cycles only
- `scaling_allowed=false` because risk increase remains not approved

Preserved blockers and safety:

- staked SOL remains external locked inventory, not bot inventory
- local journal P/L never unlocks aggregation
- incomplete direct evidence stays `unsafe_to_aggregate`
- no live broker calls
- no `--live-read-only`
- no `.env` or secrets
- no order/cancel/close/modify
- no runtime/risk/config/background changes
- no state/log mutation
- no `logs/coinbase_fills.csv` writes
- no `append_coinbase_fill_row` activation
- risk increase not approved

---

## P2-020A review — staked SOL external inventory semantics

**Branch:** `review/p2-020a-staked-sol-external-inventory`

New project fact from Vadim: the current SOL position shown in Coinbase is staked by the user. The bot cannot trade it or close it.

P2-020A classifies this SOL as external staked inventory / externally locked inventory rather than bot-tradable inventory.

Preserved safety state:
- SOL should be excluded from bot-tradable inventory.
- No close/remediation recommendation should be made for this SOL while it is staked.
- `profit_readout=unsafe_to_aggregate`
- `aggregation_allowed=false`
- `scaling_allowed=false`
- risk increase still not approved until P/L evidence and safe tradable-inventory logic are clean

No live broker calls, no `--live-read-only`, no `.env` reads, no order/cancel/close/modify, no runtime/risk/config/background/state/log mutations.

---

## P2-019H complete — second overnight handoff pack (GREEN docs-only)

**Branch:** `review/p2-019h-second-overnight-handoff-pack`

**Functional patch commit:** (final merge of this run)

P2-019H added `docs/SECOND_OVERNIGHT_STATUS_HANDOFF.md` and closed the second overnight autonomy run.

Records all GREEN patches executed (P2-019A–G), the two review-only branches (P2-017D and P2-018E), final state, and exact transcript locations + copy commands.

Pure GREEN docs closure.

---

## P2-019H complete — second overnight handoff pack (GREEN docs-only)

**Branch:** `review/p2-019h-second-overnight-handoff-pack`

**Functional patch commit:** (closing commit of this run)

P2-019H added `docs/SECOND_OVERNIGHT_STATUS_HANDOFF.md` and performed the final ACTIVE_HANDOFF.md update.

Records:
- 8 GREEN patches executed and self-merged (P2-019A through P2-019H)
- 2 review-only branches left untouched (P2-017D and P2-018E)
- Final state: profit_readout=unsafe_to_aggregate, risk increase not approved
- Exact transcript locations and pbcopy commands

Pure GREEN docs closure of the second overnight autonomy run.

---

## P2-019G complete — external signal layer safety runbook (GREEN docs-only)

**Branch:** `review/p2-019g-external-signal-layer-safety-runbook`

**Functional patch commit:** `e7a9bec`

P2-019G added `docs/EXTERNAL_SIGNAL_LAYER_SAFETY_GATE.md`.

Documents that external syndicated crypto/news/trend context remains disabled until broker truth and P/L evidence gate are complete. Explicit constraints, future sequence, and enforcement rules defined.

Pure GREEN docs-only.

---

## P2-019F complete — redaction and sensitive-field policy for broker payloads (GREEN)

**Branch:** `review/p2-019f-broker-payload-redaction-policy`

**Functional patch commit:** `8b2380a`

P2-019F added:
- `docs/BROKER_PAYLOAD_REDACTION_POLICY.md`
- `scripts/redact_broker_payload.py` + tests

Defines mandatory redaction rules for sensitive broker fields (account_id, secrets, long identifiers, etc.) and provides a simple offline helper.

Pure GREEN.

---

## P2-019E complete — manual SOL remediation decision tree runbook (GREEN docs-only)

**Branch:** `review/p2-019e-manual-sol-remediation-decision-tree`

**Functional patch commit:** `bb1846b`

P2-019E added `docs/SOL_MANUAL_REMEDIATION_DECISION_TREE.md`.

Documents the safe human decision flow for the unresolved SOL position, explicit prohibitions, and required evidence (direct entry + exit facts + human approval) before the blocker can be cleared.

Pure GREEN docs-only.

---

## P2-019D complete — operator daily digest generator, offline only (GREEN)

**Branch:** `review/p2-019d-offline-operator-daily-digest`

**Functional patch commit:** `0e20afc`

P2-019D added a lightweight offline daily digest:

- `scripts/operator_daily_digest.py`
- `tests/test_operator_daily_digest.py`

Produces text + JSON with current gate status and explicit safety warnings.

Pure GREEN (read-only).

---

## P2-019C complete — offline golden reconciliation regression runner (GREEN)

**Branch:** `review/p2-019c-offline-golden-reconciliation-regression-runner`

**Functional patch commit:** `4691023`

P2-019C added a single offline regression harness:

- `scripts/run_offline_reconciliation_regression.py`
- `tests/test_run_offline_reconciliation_regression.py`

Runs key checks (evidence gate, dashboard, zero-qty fixtures, malformed payloads) and reports the required summary fields with current gate status.

Pure GREEN (offline only).

---

## P2-019B complete — reconciliation JSON contract registry (GREEN)

**Branch:** `review/p2-019b-reconciliation-json-contracts`

**Functional patch commit:** `0864be5`

P2-019B added:
- `docs/RECONCILIATION_JSON_CONTRACTS.md` — stable top-level field contracts for all main reconciliation scripts
- `tests/test_reconciliation_json_contracts.py` — lightweight offline validation

The document explicitly marks P2-017D and P2-018E scripts as review-only only (not on main).

Pure GREEN (docs + offline tests).

---

## P2-019A complete — unmerged review branch audit pack (GREEN docs-only)

**Branch:** `review/p2-019a-unmerged-review-branch-audit-pack`

**Functional patch commit:** `50734e5`

P2-019A added `docs/UNMERGED_REVIEW_BRANCH_AUDIT.md`.

This document tracks YELLOW review branches that must not be merged without explicit ChatGPT review:

- review/p2-017d-coinbase-full-fill-payload-capture (f8dc271) — first live read-only capture for matched SOL trade; original transcript did not include exact required live JSON fields.
- review/p2-018e-local-review-gate-reconciliation-safety (e53b426) — review gate expansion with noisy static scanning.

The document includes:
- Why each branch is unmerged
- Exact pre-merge verification requirements
- Explicit “do not merge overnight” rule
- Expected ChatGPT review questions
- Re-assertion that profit_readout remains unsafe_to_aggregate and risk increase is not approved

This is pure GREEN docs-only work.

Verification passed: git diff --check clean, required phrases present, clean fast-forward merge to main.

---

## P2-018F complete — overnight final handoff and status pack (GREEN docs-only)

**Branch:** `review/p2-018f-overnight-handoff-pack`

**Functional patch commit:** `53db020`

P2-018F added:
- `docs/OVERNIGHT_STATUS_HANDOFF.md` (full summary of the overnight run)
- Master transcript at `/tmp/overnight_master_verification_transcript.txt`

Records all GREEN patches executed and self-merged, P2-018E left as review-only, P2-017D untouched per instructions, and final state.

Pure GREEN docs closure of the overnight autonomy run.

---

## P2-018D complete — operator reconciliation dashboard, offline only (GREEN)

**Branch:** `review/p2-018d-offline-reconciliation-dashboard`

**Functional patch commit:** `de2f9de`

P2-018D added a strictly offline one-page reconciliation dashboard:

- `scripts/coinbase_reconciliation_dashboard.py`
- `tests/test_coinbase_reconciliation_dashboard.py`

Produces clear operator output including:
- Current blocker state
- SOL status
- Fee/value availability
- Explicit "DO NOT SCALE RISK. DO NOT CLOSE AUTOMATICALLY." warning
- Next safe action

Pure GREEN (read-only, no broker/.env/writes).

---

## P2-018C complete — offline reconciliation fixture pack (GREEN)

**Branch:** `review/p2-018c-reconciliation-fixtures-and-regression-tests`

**Functional patch commit:** `8f7c680`

P2-018C added a set of offline synthetic fixtures for long-term regression safety:

- tests/fixtures/coinbase_reconciliation/
  - sol_open_missing_fee_value.json
  - sol_entry_exit_direct_facts_complete.json
  - sol_zero_qty_noise_rows.csv
  - broker_truth_unavailable.json
  - malformed_fill_payloads.json

- tests/test_coinbase_reconciliation_fixtures.py (5 tests)

These fixtures protect critical invariants:
- Zero-qty rows must never be treated as real fills
- Missing fee/filled_value keeps the evidence gate blocked
- Malformed payloads must not crash consumers
- Direct entry+exit facts are the threshold for aggregation eligibility (in test scenarios)

This is pure GREEN (fixtures + tests only).

---

## P2-018B complete — offline P/L evidence gate checker (GREEN)

**Branch:** `review/p2-018b-offline-pl-evidence-gate-checker`

**Functional patch commit:** `50b26fa`

P2-018B added a strictly offline, read-only evidence gate checker:

- `scripts/coinbase_pl_evidence_gate.py`
- `tests/test_coinbase_pl_evidence_gate.py` (7 tests)

The checker consumes a probe JSON and reports:
- `verdict`, `profit_readout`, `net_pnl_available`, `aggregation_allowed`, `scaling_allowed`
- Entry/exit fee + filled_value availability
- `zero_qty_rows_excluded` (always true per policy)
- Clear blockers and required_next_evidence

Current snapshot (as of this patch) correctly produces:
- BLOCKED + unsafe_to_aggregate
- sol_on_broker=true blocker
- aggregation_allowed=false, scaling_allowed=false

This is pure GREEN (offline only, no broker/.env/writes/runtime changes).

Verification passed: git diff --check clean, all tests green, smoke matches expected state, clean fast-forward merge.

---

## P2-018A complete — BROKER_TRUTH_AND_PL_EVIDENCE_GATE runbook (GREEN docs-only)

**Branch:** `review/p2-018a-broker-truth-evidence-gate-runbook`

**Functional patch commit:** `0253cae`

P2-018A added the authoritative evidence ladder document:

- `docs/BROKER_TRUTH_AND_PL_EVIDENCE_GATE.md`
- Defines L0–L5 evidence levels required before `profit_readout` can leave `unsafe_to_aggregate`
- Explicitly documents current state (SOL held, fee/filled_value missing, net_pnl_available=false)
- Prohibits treating zero-qty rows as fills, using avg_entry_price=0, risk scaling while blockers exist
- Requires explicit human approval for any manual remediation/close of the open SOL position
- Gate enforcement language for all future patches

This is pure docs-only (GREEN). No runtime, config, risk, order, or background behavior changed.

Verification passed: git diff --check clean, required strings present, clean fast-forward merge to main.

---

## P2-017C complete — read-only Coinbase full fill payload/proceeds field discovery for matched SOL lot

**Branch:** `review/p2-017c-coinbase-fill-payload-field-discovery`

**Functional patch commit (approved review 08bc67c, fast-forward merged to main):** `08bc67c`

P2-017C (YELLOW review branch, approved after verification and merged ff-only to main) adds a dedicated read-only discovery tool that inspects the recent_fills_sample (and any nested structures) from a prior hardened broker probe to determine exactly which direct fee, filled_value/proceeds, order linkage, and timing fields are present (or explicitly null) for the currently open matched SOL lot.

New artifacts:
- `scripts/coinbase_fill_payload_field_discovery.py`
- `tests/test_coinbase_fill_payload_field_discovery.py`

The script:
- Operates in default offline mode against an existing probe JSON only.
- Focuses on the known matched BUY trade_id = 1f10a7cb-3fe5-4cbb-b990-f74c39529fc9.
- Reports presence vs non-null status for fee and filled_value.
- Scans for candidate nested fee/value/order fields.
- Keeps `profit_readout=unsafe_to_aggregate` and `net_pnl_available=false` while direct non-null values are absent.

**Current verified readout (as of P2-017C):**
- profit_readout: unsafe_to_aggregate
- discovery_status: matched_trade_found_but_fee_and_value_missing
- broker_truth_available: true
- source_mode: offline_probe_json
- fills_inspected_count: 20
- products_seen: ['ETH/USD', 'SOL/USD']
- matched_trade_id: 1f10a7cb-3fe5-4cbb-b990-f74c39529fc9
- matched_trade_found: true
- matched_trade_product_id: SOL-USD
- matched_trade_side: BUY
- matched_trade_size: 0.0122504
- matched_trade_price: 81.63
- matched_trade_fee_present: true
- matched_trade_fee_non_null: false
- matched_trade_filled_value_present: true
- matched_trade_filled_value_non_null: false
- matched_trade_order_id_present: false
- candidate_fee_fields: ['fee']
- candidate_value_fields: ['filled_value']
- candidate_order_id_fields: []
- missing_direct_fee_count: 20
- missing_direct_filled_value_count: 20
- net_pnl_available: false
- risk increase: not approved
- next action: controlled deeper read-only fill payload capture for the matched trade_id (not scaling or closing the SOL position)

**Safety (re-asserted):**
- Default mode: zero broker calls, zero .env reads, zero file mutations.
- No append_coinbase_fill_row, no logs/coinbase_fills.csv writes.
- No strategy/risk/sizing/config/runtime/LaunchAgent changes.
- Optional --live-read-only mode (if ever implemented) is strictly opt-in and never used in verification.

All verification commands passed using the pre-existing hardened probe JSON only. No --live-read-only during this patch. Merged to main after explicit approval.

---

## P2-017B complete — read-only Coinbase fill/position lifecycle reconciliation report

## P2-017B complete — read-only Coinbase fill/position lifecycle reconciliation report

**Branch:** `review/p2-017b-coinbase-fill-position-lifecycle-reconciliation`

**Functional patch commit (approved review e11ac84, fast-forward merged to main):** `e11ac84`

P2-017B (YELLOW review branch, approved after verification and merged ff-only to main) adds a focused read-only lifecycle report that consumes a hardened live broker probe JSON and answers whether recent fills in the broker sample can explain the currently held SOL position reported by the exchange.

New artifacts:
- `scripts/coinbase_fill_position_lifecycle_reconciliation.py`
- `tests/test_coinbase_fill_position_lifecycle_reconciliation.py`

The report:
- Parses open_positions_on_broker and recent_fills_sample from the probe.
- Normalizes SOL-USD ↔ SOL/USD product IDs.
- Detects exact/near-exact size match between current broker SOL long and a recent BUY fill.
- Emits only clearly labeled **provisional estimates** (gross_cost = size × price for the matched BUY; gross_unrealized_pnl = current_market_value − gross_cost).
- Explicitly reports `fees_available=false`, `filled_value_available=false`, `net_pnl_available=false` when those fields are null/missing in the sample.
- Keeps `profit_readout=unsafe_to_aggregate` and `verdict=BLOCKED` (SOL still held on broker).
- Excludes zero-qty journal rows by design (they are never treated as real fills).

**Current verified readout (from hardened live probe /tmp/coinbase_live_probe_hardened_current.json as of P2-017B):**
- verdict: BLOCKED
- profit_readout: unsafe_to_aggregate
- broker_truth_available: true
- SOL held on broker: true
- current_sol_qty: 0.0122504
- current_sol_market_value: 1.0134755
- current_sol_price: 82.715
- likely_current_sol_entry_trade_id: 1f10a7cb-3fe5-4cbb-b990-f74c39529fc9
- likely_current_sol_entry_size: 0.0122504
- likely_current_sol_entry_price: 81.63
- likely_current_sol_entry_gross_cost_estimate: 1.000000152
- current_sol_gross_unrealized_pnl_estimate: 0.013475348000000054
- fees_available_for_current_sol_entry: false
- filled_value_available_for_current_sol_entry: false
- net_pnl_available: false
- recent_sol_fills_count: 10
- recent_eth_fills_count: 10
- recent_fills_missing_fee_count: 20
- recent_fills_missing_filled_value_count: 20
- reconciliation_status: current_sol_likely_matched_to_recent_buy_but_pnl_unsafe
- risk increase: not approved
- next action: direct per-fill fee + filled_value/proceeds reconciliation (not scaling or closing the SOL position)

**Safety (re-asserted):**
- Zero broker calls, zero .env reads, zero file mutations in the new script and tests.
- No append_coinbase_fill_row, no logs/coinbase_fills.csv writes.
- No strategy/risk/sizing/config/runtime/LaunchAgent changes.

All verification commands passed using the pre-existing hardened probe JSON only. No --live-read-only during this patch. Merged to main after explicit approval.

---

## P2-017A complete — Coinbase live broker-truth probe schema hardening + read-only reconciliation summary

## P2-017A complete — Coinbase live broker-truth probe schema hardening + read-only reconciliation summary

**Branch:** `review/p2-017a-coinbase-broker-truth-schema-and-summary`

**Functional patch commit (approved review 805ddfe, fast-forward merged to main):** `805ddfe`

P2-017A (YELLOW review branch, approved after verification and merged ff-only to main) hardens the live broker reconciliation probe JSON contract so every output path (default and --live-read-only) explicitly includes:
- live_read_only, broker_calls_made, broker_read_successful (booleans)
- broker_error_type, credential_status
- sol_on_broker / eth_on_broker (true/false/null with unknown-state semantics)
- open_orders, recent_fills_sample, open_positions_on_broker
- Full required top-level keys for downstream consumers.

Added new pure read-only summarizer:
- `scripts/coinbase_broker_truth_summary.py`
- Consumes prior probe JSON + local state/closed_positions + runtime/heartbeat + journal (safe columns only)
- Never calls broker, never reads .env, never mutates files
- Gracefully handles old probe JSONs missing the new booleans (reports schema_missing_fields)
- Produces reconciliation_status, broker_truth_available, recommended_next_action, zero-qty journal counts, etc.

**Current verified readout (from live probe + local state as of P2-017A):**
- build momentum: positive
- trading/profit readout: unsafe_to_aggregate
- SOL held on broker: true (per live read-only probe; conflicts with local dropped/re-associated/unconfirmed evidence)
- open orders: 0
- recent fills sample: 20
- risk increase: not approved
- next action: reconciliation (not strategy/risk scaling or sizing changes)
- broker close capability for the open SOL position remains unconfirmed
- local_open_positions_count: 1
- local_open_position_symbols includes SOL/USD
- local_journal_recent_zero_qty_rows_count: 51

Tests added:
- tests/test_coinbase_live_broker_reconciliation_probe_schema.py
- tests/test_coinbase_broker_truth_summary.py

All verification commands (py_compile, pytest subsets, git diff --check, default probe --json, summary using pre-existing /tmp probe JSON only) passed on review branch. No --live-read-only run in this patch. No new broker calls. Merged to main after explicit approval; no self-merge.

**Safety invariants (re-asserted):**
- No orders, cancels, closes, modifications
- No writes to logs/coinbase_fills.csv or append_coinbase_fill_row
- No mutation of state/coinbase/*.json or runtime
- No LaunchAgent / background / runtime config changes
- No secrets printed or committed
- Default probe path: zero broker calls
- Summary: zero network, zero .env, zero writes

**Next after P2-017A:** Continue reconciliation proof work toward direct sell proceeds + per-fill fees + stable trade_id availability before any fill logger activation or risk scaling. SOL broker-held blocker remains the gating item. Profit readout stays unsafe_to_aggregate until direct broker facts for exits are proven.

---

## P2-016A complete — Grok execution protocol and external signal context plan

## P2-016A complete — Grok execution protocol and external signal context plan

Functional patch commit: `061fabc`

P2-016A added durable project docs to reduce copy/paste overhead and preserve future roadmap discipline:

* `docs/GROK_EXECUTION_PROTOCOL.md`

  * defines Controlled Autonomy workflow for Grok
  * standardizes branch, test, commit, merge, handoff, and transcript expectations
  * allows self-merge for low-risk docs/tests/read-only diagnostic work after verification
  * preserves hard blocks around orders, risk, sizing, runtime, LaunchAgents, and strategy changes

* `docs/EXTERNAL_SIGNAL_CONTEXT_PLAN.md`

  * preserves future syndicated crypto/news/trend context layer
  * target sources include CoinGecko, CoinDesk RSS/news, Financial Modeling Prep crypto news, LunarCrush, and similar reputable feeds
  * layer remains advisory-only until broker reconciliation and direct P/L truth are solid
  * no direct buy/sell triggers, sizing/risk/cap changes, or strategy overrides
  * intended sequence: source registry → read-only collector → context signal aggregator → weak watchlist/skip/observe input after validation

Safety / scope:

* docs-only functional patch
* no runtime/config/order/risk/strategy changes
* no broker API calls
* no file/log/journal/state mutation outside docs
* no fill logger writes
* no leverage, margin, futures, perps, options, commodities, GOLD/SILVER/XAU/XAG enabled

Profit / momentum readout:

* build momentum: strong positive
* process velocity: improved via Controlled Autonomy docs
* trading/profit readout: unsafe-to-aggregate until successful broker truth and direct fill/proceeds/fees reconciliation are proven

## P2-015B complete — Coinbase live probe adapter compatibility and unknown-state semantics

Functional patch commit: `c9d8f05`

P2-015B fixed the Coinbase live broker reconciliation probe after P2-015A exposed a broker adapter compatibility issue:

* removed incorrect `dry_run=True` constructor usage for `BrokerCoinbase`
* classified broker adapter errors separately from actual broker truth
* preserved explicit `--live-read-only` gating
* preserved default zero-broker-call behavior
* corrected unknown-state semantics:

  * if no successful broker read occurs, `sol_on_broker` is `null`, not `false`
  * if no successful broker read occurs, `eth_on_broker` is `null`, not `false`
  * broker holdings are not reported as proven false unless direct broker data was successfully fetched
* added/updated tests covering adapter error and unknown-state behavior

Current default result:

* `verdict`: `BLOCKED`
* `profit_readout`: `unsafe_to_aggregate`
* `live_read_only`: `false`
* `broker_calls_made`: `false`
* `sol_on_broker`: `null`
* `eth_on_broker`: `null`

Safety / scope:

* no runtime/config/order/risk/strategy files changed
* no default broker/API calls
* no order placement/cancel/close/modify calls
* no file mutation calls in production script
* no journal/state/runtime/log writes
* no `logs/coinbase_fills.csv` writes
* no `append_coinbase_fill_row` production call
* no `.replace()` call in production script per conservative safety gate
* no leverage, margin, futures, perps, options, commodities, GOLD/SILVER/XAU/XAG enabled

Profit / momentum readout:

* build momentum: strong positive
* trading/profit readout: unsafe-to-aggregate
* broker truth still requires a successful `--live-read-only` run with valid read-only Coinbase credentials

## P2-015A complete — read-only Coinbase live broker reconciliation probe

Functional patch commit: `2f2ab7a`

P2-015A added an explicit opt-in Coinbase live broker reconciliation probe:

* new script: `scripts/coinbase_live_broker_reconciliation_probe.py`
* new tests: `tests/test_coinbase_live_broker_reconciliation_probe.py`
* default mode performs ZERO broker/API calls
* live broker reads require explicit `--live-read-only`
* `--json` emits valid machine-readable output in both default and live-read-only paths
* default JSON includes `live_read_only=false` and `broker_calls_made=false`
* probe is designed to compare direct broker account/position/order/fill truth against local SOL/USD orphan/reconciliation evidence

Current default result:

* `verdict`: `BLOCKED`
* `profit_readout`: `unsafe_to_aggregate`
* `live_read_only`: `false`
* `broker_calls_made`: `false`
* next action: re-run with `--live-read-only` after confirming read-only Coinbase API credentials

Safety / scope:

* no runtime/config/order/risk/strategy files changed
* no default broker/API calls
* no order placement/cancel/close/modify calls
* no file mutation calls in production script
* no journal/state/runtime/log writes
* no `logs/coinbase_fills.csv` writes
* no `append_coinbase_fill_row` production call
* no `.replace()` call in production script per conservative safety gate
* no leverage, margin, futures, perps, options, commodities, GOLD/SILVER/XAU/XAG enabled

Profit / momentum readout:

* build momentum: strong positive
* trading/profit readout: unsafe-to-aggregate
* no risk/cap/aggressiveness increase is justified until direct broker close/fill/proceeds/fees truth is proven

## P2-014E complete — read-only Coinbase operator status aggregator

Functional patch commit: `662dc1d`

P2-014E added a single read-only Coinbase operator status aggregator:

- new script: `scripts/coinbase_operator_status.py`
- new tests: `tests/test_coinbase_operator_status.py`
- aggregates local fill/proceeds/P&L reconciliation status
- aggregates open/orphan position status
- aggregates prediction/price-data coverage status where available
- emits text and machine-readable `--json`
- provides top-level `verdict`, `profit_readout`, blockers, and next recommended action

Current local operator result:
- `verdict`: `BLOCKED`
- `profit_readout`: `unsafe_to_aggregate`
- `sol_blocker_detected`: `true`
- blocker count: `8`
- next action: urgently investigate and resolve SOL/USD broker-close status before aggregating P/L or increasing risk

Safety / scope:
- no runtime/config/order/risk/strategy files changed
- no broker API calls added
- no `.env` reads added
- no network calls added
- no file mutation calls in production script
- no fill logger writes enabled
- no `logs/coinbase_fills.csv` writes
- no `append_coinbase_fill_row` production call
- no leverage, margin, futures, perps, options, commodities, GOLD/SILVER/XAU/XAG enabled

Profit / momentum readout:
- build momentum: strong positive
- trading/profit readout: unsafe-to-aggregate
- no risk/cap/aggressiveness increase is justified

## P2-014D complete — read-only open/orphan Coinbase position status report

Functional patch commit: `39a3408`

P2-014D added a read-only operator report for Coinbase open/orphan position status:
- current/open position evidence
- dropped/re-associated/orphan evidence
- broker close capability status
- manual-review requirements
- profit/readout blockers
- machine-readable `--json` output

Current report result:
- SOL/USD unresolved/re-associated broker-close blocker detected from local journal evidence
- broker close capability remains unconfirmed unless direct later evidence proves otherwise
- realized P/L remains unsafe-to-aggregate while open/orphan status is unresolved
- report is intentionally conservative and advisory-only

Safety / scope:
- no runtime/config/order/risk/strategy files changed
- no broker API calls added
- no `.env` reads added
- no fill logger writes enabled
- no `logs/coinbase_fills.csv` changes
- no `append_coinbase_fill_row` production call
- no leverage, margin, futures, perps, options, commodities, GOLD/SILVER/XAU/XAG enabled

Profit / momentum readout:
- build momentum: strong positive
- trading/profit readout: unsafe-to-aggregate
- no risk/cap/aggressiveness increase is justified

## P2-014C complete — local review-gate automation for Grok/Codex patches

Functional patch commit: `1e66b94`

P2-014C added reusable local review-gate scaffolding to reduce copy/paste, false positives, and human verification errors during Grok/Codex buildout.

Changed files:
- `scripts/local_review_gate.py`
- `tests/test_local_review_gate.py`
- `docs/GROK_CODEX_REVIEW_GATE.md`

Purpose:
- verify review branches with one command
- check expected changed files
- block protected runtime/config/order/risk/log files
- require explicit permission for `docs/ACTIVE_HANDOFF.md` changes
- avoid false positives where `append_coinbase_fill_row` appears only in protective tests
- block production fill logger writes/references unless explicitly approved
- produce compact final reports for ChatGPT merge review

Safety / scope:
- no live trading behavior changed
- no strategy/order/risk/symbol/cap/config/runtime behavior changed
- no broker API calls added
- no `.env` reads added
- no fill logger writes enabled
- `logs/coinbase_fills.csv` remains protected
- no leverage, margin, futures, perps, options, commodities, GOLD/SILVER/XAU/XAG enabled

Profit / momentum readout:
- build momentum: strong positive
- trading/profit readout: still unsafe-to-aggregate
- no risk/cap/aggressiveness increase is justified


## P2-014B complete — read-only fill/proceeds/P&L reconciliation readout

Functional patch commit: `1eb2007`

P2-014B improved `scripts/coinbase_fill_proceeds_reconciliation_report.py` and its tests so the local reconciliation report now clearly separates:
- direct broker facts available from local rows
- locally derived values
- unsafe/missing values
- matched-pair summaries
- open/unresolved position evidence
- SOL/USD broker-close blocker evidence

Verified:
- `tests/test_coinbase_fill_proceeds_reconciliation_report.py`: 16 passed
- `tests/test_coinbase_fill_logging_contract_check.py`: 10 passed
- `tests/test_coinbase_entry_exit_capture.py`: 5 passed
- report smoke passed
- patch remained read-only/local CSV inspection only

Current report result:
- direct order/client-order coverage exists
- direct sell proceeds are not available locally
- direct fees are not available locally in enough form for immutable P/L aggregation
- no paired cycle has both actual buy cost and direct sell proceeds locally available
- realized P/L remains unavailable / unsafe-to-aggregate
- SOL/USD open/re-associated blocker remains active
- broker close capability remains unconfirmed

Safety / scope:
- no runtime/config/order/risk/strategy files changed
- no fill logger writes enabled
- no `append_coinbase_fill_row` production call
- no `.env`, `logs/coinbase_fills.csv`, LaunchAgent, state, runtime, or broker API behavior changed
- no leverage, margin, futures, perps, options, commodities, GOLD/SILVER/XAU/XAG enabled

Profit / momentum readout:
- build momentum: positive
- trading/profit readout: unsafe-to-aggregate
- no risk/cap/aggressiveness increase is justified


## P2-014A — ACTIVE_HANDOFF live status preservation + P2-014 preflight (docs-only)

Functional patch commit (latest complete): `e90e678` (P2-013C: read-only local price data coverage diagnostics + targeted regressions)

P2-014A (this patch): docs-only update to preserve latest live Coinbase operational/reconciliation blocker status in ACTIVE_HANDOFF.md. No runtime strategy, config, risk, order, .env, LaunchAgent, or logging behavior changes of any kind. This patch exists solely to improve operational/profit truth by documenting grim reality accurately.

**Preserved live status (as of latest local auto-sync; treat strictly as operational/reconciliation blocker, NOT strategy success):**
- Coinbase equity around $45.73
- SOL/USD open/re-associated (bot-origin position)
- broker close capability unconfirmed
- close failures logged (position may have been dropped from tracking after 3 failed close attempts)
- latest functional patch remains e90e678
- no risk/aggressiveness increase justified

P2-013C diagnostic results (retained for continuity):
- outcome evaluator remains read-only
- price data status remains read-only
- local run still reports `Evaluable telemetry rows: 0`
- hit rates remain non-actionable until dense local price coverage exists
- strategy tuning remains premature

Safety / scope (unchanged):
- no strategy/order/risk/symbol/cap/config/runtime changes
- no leverage, margin, futures, perps, options, commodities, GOLD/SILVER/XAU/XAG order placement enabled
- fill logger remains blocked
- `append_coinbase_fill_row` is not called by production code
- no `.env`, `logs/`, or `coinbase_fills.csv` changes
- profit/readout remains required in every status update and handoff

Profit / momentum readout:
- last verified realized P&L remains `-$0.0358` unless newer journal/status output proves otherwise
- current outcome scoring is still not actionable because evaluable telemetry rows remain `0`
- **current profit readout is unsafe-to-aggregate until direct fill/proceeds/fees reconciliation is proven** (see P2-014 preflight below)
- no risk/cap/aggressiveness increase is justified

<!-- This file is the shared context layer between Claude (advisor) and ChatGPT/Copilot (executor). -->
<!-- Update this file after every session. Both AIs read from here. Do not let it go stale. -->

**Last updated:** 2026-05-31 18:57 UTC — P2-014C complete; added local review-gate automation for Grok/Codex patches to reduce copy/paste, false positives, and human verification error. Latest functional patch commit 1e66b94. No strategy/order/risk/symbol/cap/config/runtime behavior changed. Profit readout remains unsafe-to-aggregate until direct fill/proceeds/fees and open-position status are proven.
**Updated by:** Grok (per P2-014A ritual)
**Repo:** https://github.com/vadim-koenen/alpaca-autonomous-microbot.git  
**Branch:** review/p2-014a-coinbase-live-status-and-reconciliation-preflight

## P2-014 Preflight — Profit Readout Safety (reconciliation blocker)

**Current profit readout (realized P&L, outcome scoring, hit rates) is unsafe-to-aggregate** until direct fill/proceeds/fees reconciliation is proven from broker data for entry and exit legs.

This is especially critical given the open SOL/USD position (broker close capability unconfirmed after logged close failures; position possibly dropped from tracking).

Existing reconciliation modules/scripts/tests already exist and should be reused for the next step:
- `coinbase_order_fills_reconciliation.py` (P2-011F) — pure `reconcile_order_with_fills()` returning `ReconciliationResult` with `direct_broker_fact` / `locally_derived` / `unavailable` classifications for proceeds, fees, filled_value, logger_ready gate, raw payloads preserved, blocking_reasons.
- `coinbase_entry_exit_capture.py` (P2-011G) — inert `capture_leg` / `capture_entry` / `capture_exit` wrappers over the above (never called from live paths in current code).
- `scripts/coinbase_fill_proceeds_reconciliation_report.py` + `tests/test_coinbase_fill_proceeds_reconciliation_report.py`
- `tests/test_coinbase_fill_logging_contract_check.py`
- `tests/test_coinbase_entry_exit_capture.py`

**Next patch should focus on read-only reconciliation reporting**: exercise the above modules against the current journal (and any available local broker history/fixtures for the open SOL position and recent exits) to determine whether stable per-fill trade_ids, actual sell proceeds on exits, and per-fill fees are recoverable. Produce advisory report only. No network calls in tests, no writes, no append_coinbase_fill_row, no live behavior changes, no config/risk/strategy modifications.

Until that proof exists, all P&L, expectancy, and "profit" numbers must be treated as provisional/unsafe-to-aggregate. The SOL position with unconfirmed broker close is an explicit reconciliation blocker.

No risk/aggressiveness increase or strategy changes are justified while this state persists.

---

## 1. Project Identity

Two bots, one repo, running on a Mac under launchd.

| Bot | Exchange | Status | Config file |
|---|---|---|---|
| **Coinbase bot** | Coinbase Advanced | ✅ PRIMARY — active optimization | `config_coinbase_crypto.yaml` |
| **Alpaca bot** | Alpaca | ⏸ SECONDARY — on hold | `config.yaml` |

**Coinbase bot** is the active focus. Running $1 controlled exploration across BTC/USD, ETH/USD, SOL/USD. All current patches (P2-001x through P2-002) are Coinbase-only.

**Alpaca bot** is running but on hold — constant stale quote skips during off-hours, zero trades placed, not current priority. Will revisit when equity market hours align or when Coinbase work reaches a stable plateau.

Note: repo name (`alpaca-autonomous-microbot`) reflects the project's origin. Both bots live here.

---

## 2. Hard Rules (both AIs must respect these always)

```
DO NOT:
  - restart bots
  - run launchctl
  - run live mode manually
  - place / cancel / modify orders
  - edit .env
  - read or print secrets or API keys
  - touch broker_*.py, order_manager.py, risk_manager.py, main.py
  - touch launchd/, state/, runtime files
  - change config_coinbase_crypto.yaml or config.yaml risk caps
  - raise notional, exposure caps, max open positions, or daily loss cap
  - connect prediction/ML outputs to live trading decisions
  - approve paper-to-live model promotion

ALWAYS:
  - Advisory/read-only patches are Class 1 (safest)
  - Live behavior changes are Class 2+ (require explicit approval)
  - New report/script files are always Class 1
  - Tests must accompany new scripts
  - Every new file must have ADVISORY ONLY comment block at top
```

---

## 3. Current Live State

| Item | Value |
|---|---|
| Coinbase equity | $45.73 |
| Coinbase status | RUNNING_BY_LAUNCHD |
| Alpaca equity | $10.00 |
| Alpaca status | RUNNING_BY_LAUNCHD (outside market hours) |
| Kill switch | INACTIVE (trading allowed) |
| Open positions | 1 (SOL/USD — bot_opened, broker_close_capability_unconfirmed) |
| Last Coinbase trade | 2026-05-31T16:30:23 UTC (SOL/USD entry, filled) |
| Last Coinbase exit | 2026-05-25T11:19:39 UTC (ETH/USD, max-hold) |
| Current regime | downtrend (AVAX/USD scan; bot correctly sitting out) |

---

## 4. Coinbase Controlled Exploration Config (do not change)

```yaml
controlled_exploration:
  enabled: true
  approved_symbols: [BTC/USD, ETH/USD, SOL/USD]
  max_single_trade_notional_usd: 1.00
  max_total_exploration_exposure_usd: 6.00
  max_round_trips_per_day: 12
  max_entries_per_symbol_per_day: 4
  per_symbol_cooldown_minutes: 30
  daily_stop_loss_usd: 3.00
  max_consecutive_losses: 3
  max_open_positions: 2

fee_model:
  maker_fee_pct: 0.006   # 0.60%
  taker_fee_pct: 0.012   # 1.20%
  # Round-trip taker break-even: 2.40% gross move required
```

---

## 5. Completed Milestones

| ID | Name | Status |
|---|---|---|
| P1-001 | Shadow learner schema/scaffold | DONE |
| P1-002 | Shadow learner log/state ingestion | DONE |
| P1-003/004 | Outcome labeling scaffold | DONE |
| P1-004B/F | Price history + retrospective/prospective samples | DONE / advisory |
| P1-006 | News/trend context scaffold | DONE |
| P1-006C | Prospective diagnostics — no deployable edge found | DONE |
| P1-006D | Scoring reconciliation | DONE / committed |
| P2-001 | Controlled Coinbase exploration | DONE / live |
| P2-001B | State-aware LRU rotation (BTC→ETH→SOL proven) | DONE / committed `adbebf4` |
| P2-001C | Coinbase exploration fee/performance report | DONE / committed `0a6c82c` |
| P2-001D | Controlled exploration status accuracy fix | DONE / committed `e10a722` |
| P2-001E | Coinbase exit quality report | DONE / committed `535298c` |
| P2-001F | Coinbase maker order audit | DONE / committed `f835e74` |
| P2-001G | Patch completion automation | DONE / committed `5fcca5c` |
| P2-001H | Coinbase live-only performance re-baseline | DONE / committed `9ac606a` |
| P2-001I | Handoff automation daemon | DONE / committed `0028733` |
| P2-002 | Review and commit advisory prediction features | DONE / committed `012ab07` |
| P2-003 | Intra-hold price path logger | DONE / committed `bd89891` |
| P2-004 | Dynamic equity-based Coinbase sizing groundwork | DONE / committed `4903014` |
| P2-005 | Coinbase Price-Path MFE/MAE Analyzer | DONE / committed `7ddf6d7` |
| P2-006 | Coinbase Sizing / Execution / Profitability Reconciliation Report | DONE / committed `49135bc` |
| P2-007 | Coinbase Fill / Proceeds Reconciliation Report | DONE / committed `1b6ce77` |
| P2-008 | Coinbase Immutable Fill Logging Contract Spec | DONE / committed `fbe3867` |
| P2-009 | Open-Source Bot Plumbing Survey | DONE / committed `1b49c11` |
| P2-010 | Coinbase Fill Logging Implementation Discovery | DONE / committed `0bc4d87` |
| P2-010B | Stabilize Coinbase Fill Logging Discovery Report | DONE / committed `d1de493` |
| P2-010C | Remove Volatile Skipped Paths From Discovery Report | DONE / committed `3a7a953` |
| P2-011A | Coinbase Fill Logger Scaffold | DONE / committed `818ded7` |
| P2-011B | Coinbase Fill Response Discovery | DONE / committed `90f68fa` |
| P2-011C | Coinbase Raw Payload Fixture Proof | DONE / committed `081c04b` |
| P2-011D-alt | Coinbase Fills Payload Discovery | DONE / committed `0b2a629` |
| P2-011E | Coinbase Historical Fills Wrapper Proof | DONE / committed `af1eb87` |

---

## 6. Git State (as of last update)

```
Latest functional patch commit: `d67c37c`
Commit hashes for handoff updates should be verified with `git log`; this file intentionally avoids storing a self-referential handoff commit hash.
Clean: no dirty tracked files (except handoff update)

Recent commits:
  90f68fa P2-011B: Coinbase Fill Response Discovery
  818ded7 P2-011A: Coinbase Fill Logger Scaffold
  3a7a953 P2-010C: Remove Volatile Skipped Paths From Discovery Report
  d1de493 P2-010B: Stabilize Coinbase Fill Logging Discovery Report
  0bc4d87 P2-010: Coinbase Fill Logging Implementation Discovery
  1b49c11 P2-009: Open-Source Bot Plumbing Survey
  fbe3867 P2-008: Coinbase Immutable Fill Logging Contract Spec
  1b6ce77 P2-007: Coinbase Fill / Proceeds Reconciliation Report
  49135bc P2-006: Coinbase Sizing / Execution / Profitability Reconciliation Report
```

P2-002 advisory prediction features are committed (`012ab07`); do not connect to live decisions without explicit approval.

---

## 7. Current Performance Diagnosis

From confirmed live trade data (6 completed cycles):

| Cycle | Gross | Fee | Net |
|---|---|---|---|
| BTC/USD #1 | -$0.0074 | -$0.0120 | **-$0.0193** |
| ETH/USD #1 | -$0.0046 | -$0.0120 | **-$0.0166** |
| SOL/USD #1 | +$0.0150 | -$0.0121 | **+$0.0029** ✓ |
| BTC/USD #2 | +$0.0039 | -$0.0120 | **-$0.0081** |
| ETH/USD #2 | -$0.0050 | -$0.0120 | **-$0.0169** |
| SOL/USD #2 | -$0.0082 | -$0.0120 | **-$0.0202** |

- **All 26 journal exits are max-hold exits** — SL/TP thresholds have never triggered
- Fee per round trip ≈ $0.012 at $1 notional
- Break-even requires 2.4% gross move in 90 min; actual avg is ~0.1–0.5%
- 1 of 6 net positive. Current expectancy is negative.
- Root cause: fee drag + forced time exits, not execution failure

---

## 8. Active Patch Queue

### IN PROGRESS
**P2-011H completed the narrow opt-in dry-run Coinbase capture seam proof in the actual entry/exit flow. Key finding: `position_manager.py` now has a disabled-by-default `dry_run_capture=False` seam that can call the inert capture/reconciliation helpers only when explicitly enabled, storing results in memory via `_dry_run_captures` and performing no writes. Dedicated tests prove default constructor compatibility, default-disabled behavior, opt-in entry/exit capture behavior, no `append_coinbase_fill_row` calls, no logger writes, and logger readiness remaining blocked when broker facts are missing. Logger hook remains blocked. Next safe patch: P2-011I — controlled dry-run broker-data capture/probe proof to exercise the seam with real or captured broker payloads, still no writes. Do not tune TP/SL, hold time, notional size, symbols, predictions, risk caps, config, runtime, or live strategy until actual fills/proceeds/fees are captured and reconciled.**

### QUEUED (blocked — data + explicit approval required)
- **SL/TP/hold-time tuning** — Class 2; use P2-001E exit-quality and P2-005 MFE/MAE reports only after ≥20 price-path samples, ~2+ weeks of P2-003 data, and explicit human approval

### DO NOT START YET
- Any TP/SL/hold-time config changes
- Notional increase
- P2-003 entry quality gate
- Connecting P2-002 features to live decisions
- Alpaca equity work (after-hours stale quotes are expected, not a bug)

---

## 9. How to Update This File

**After Claude session:** Claude updates sections 3, 6, 7, 8 based on what was reviewed.  
**After Copilot execution:** Update section 8 (mark patch done, add new queued item).  
**After each git push:** Update section 6 with new HEAD commit.  

Keep this file committed and pushed. Both AIs reference it at session start.

---

## 10. Session Start Checklist

For any AI beginning a session on this project:

```bash
cd /Users/vadimkoenen/Documents/Claude/Projects/Investing/alpaca-autonomous-microbot

# 1. Confirm repo state
git status --short
git log --oneline -5

# 2. Confirm bots running
bash scripts/status.sh

# 3. Confirm exploration state
CONFIG_FILE=config_coinbase_crypto.yaml python3 scripts/controlled_exploration_status.py

# 4. Read this file
cat docs/ACTIVE_HANDOFF.md
```

Do not recommend or execute anything until all four commands have been run and reviewed.

---

## 11. Automated Status Log
<!-- Appended automatically by Claude scheduled tasks. Do not edit manually. -->
<!-- Format: YYYY-MM-DD HH:MM | equity=$X | positions=X | regime=X | errors=X | head=commit -->

- 2026-05-29 20:30 | equity=$40.94 | positions=0 | regime=dead_chop | errors=0 | head=adbebf4
- 2026-05-30 02:53 | equity=$40.94 | positions=0 | regime=dead_chop | errors=0 | head=8bbaae0 | P2-001D committed+pushed, auto-sync installed, P2-001E now active
- 2026-05-30 03:35 UTC | head=535298c | P2-001E committed+pushed; Class 2 SL/TP/hold tuning awaiting explicit approval
- 2026-05-30 03:53 UTC | head=f835e74 | P2-001F committed+pushed; 6/6 entries likely passive-priced; actual maker/taker fee flags still unproven
- 2026-05-30 03:56 UTC | head=f835e74 | P2-001F committed+pushed; 6/6 entries likely passive-priced; actual maker/taker fee flags still unproven
- 2026-05-30 04:05 UTC | head=5fcca5c | P2-001G complete; Automates ACTIVE_HANDOFF updates, handoff commits, pushes, and raw GitHub verification
- 2026-05-30 04:12 UTC | head=9ac606a | P2-001H complete; Re-baselines Coinbase exploration using live-only BTC/ETH/SOL data excluding dry_run, ALGO, probe, and recovered noise
- 2026-05-30 04:23 UTC | head=0028733 | P2-001I complete; Adds polling daemon to automate ACTIVE_HANDOFF updates
- 2026-05-30 12:41 | equity=$40.94 | positions=0 | regime=dead_chop | errors=0 | head=b4da00f
- 2026-05-30 12:41 UTC | head=012ab07 | P2-002 complete; Shadow learner features reviewed for future-data leakage and committed
- 2026-05-30 12:52 UTC | head=bd89891 | P2-003 complete; Adds read-only Coinbase price path logger to collect intra-hold snapshots for true MFE/MAE analysis before Class 2 tuning
- 2026-05-30 14:28 UTC | head=4903014 | P2-004 complete; Adds Coinbase-only dynamic equity sizing framework while preserving hard $1 trade cap, exposure cap, stop-loss cap, and existing risk gates
- 2026-05-30 14:44 UTC | head=7ddf6d7 | P2-005 complete; Adds advisory-only Coinbase price-path MFE/MAE analyzer, tests, and runbook to evaluate intra-hold excursions before any Class 2 tuning.
- 2026-05-30 18:26 UTC | head=49135bc | P2-006 complete; Adds advisory-only Coinbase sizing/execution reconciliation report, tests, and runbook. The report explains fixed-cap controlled exploration, legacy $0.50 vs $1.00 sizing, missing sell-fill data, fee drag, max-hold exits, and why P/L must remain unavailable when sell proceeds are not present.
- 2026-05-30 19:15 UTC | head=1b6ce77 | P2-007 complete; Adds advisory-only Coinbase fill/proceeds reconciliation report, tests, and runbook. Confirms 37 exit/sell rows, zero direct sell proceeds, zero fee rows, zero reconstructable gross/net P/L pairs; realized P/L must remain n/a until immutable fill/proceeds/fee logging is fixed.
- 2026-05-30 19:35 UTC | head=fbe3867 | P2-008 complete; Adds Coinbase immutable fill logging contract spec, read-only contract checker, and tests. Confirms `logs/coinbase_fills.csv` is missing and realized P/L must remain n/a until actual fill/proceeds/fee logging is implemented safely.
- 2026-05-30 19:45 UTC | head=1b49c11 | P2-009 complete; Adds open-source bot plumbing survey, read-only reference checker, and tests. Integrates Freqtrade, Hummingbot, Jesse, OctoBot, and CCXT as architecture references only. No external code copied, no installs, no live behavior changes, no strategy tuning. Next patch should be P2-010 read-only Coinbase fill logging implementation discovery.
- 2026-05-30 19:50 UTC | head=0bc4d87 | P2-010 complete; Adds read-only Coinbase fill logging implementation discovery, generated report, scanner, and tests. Identifies broker/status/journal seams for future append-only fill logging. No live behavior changes, no external API calls, no config/risk/state/runtime/launchd changes, and no strategy tuning.
- 2026-05-30 19:55 UTC | head=d1de493 | P2-010B complete; Stabilizes Coinbase fill logging discovery report generation and tests deterministic regeneration. No live behavior changes, no external API calls, no config/risk/state/runtime/launchd changes, and no strategy tuning.
- 2026-05-30 20:00 UTC | head=3a7a953 | P2-010C complete; Removes volatile `.git/` skipped-path preview entries from the Coinbase fill logging discovery report and confirms deterministic regeneration. No live behavior changes, no external API calls, no config/risk/state/runtime/launchd changes, and no strategy tuning.
- 2026-05-30 23:06 UTC | head=818ded7 | P2-011A complete; Adds tested append-only Coinbase fill/proceeds/fee logger scaffold, deterministic CSV schema, append/header safety tests, raw payload serialization tests, and implementation plan. No broker/journal hook, no live behavior changes, no external API calls, no config/risk/state/runtime/launchd changes, and no strategy tuning.
- 2026-05-30 23:26 UTC | head=90f68fa | P2-011B complete; Adds read-only Coinbase fill response discovery script, generated report, and tests. Confirms logger hook remains blocked because direct sell proceeds and actual exit-leg fees are not yet proven from current broker response handling. No broker/journal hook, no live behavior changes, no external API calls, no config/risk/state/runtime/launchd changes, and no strategy tuning.
- 2026-05-31 03:34 UTC | head=081c04b | P2-011C complete; Added raw Coinbase order/status + fills fixture proof and committed required fixtures. Tests passed. Logger hook remains blocked because direct sell proceeds and current exit-leg stable fill-level idempotency are still not proven from the current broker response path. No live behavior/config/risk/runtime/strategy changes.
- 2026-05-31 03:38 UTC | head=0b2a629 | P2-011D-alt complete; Added Coinbase fills payload discovery with fixtures/tests. Finding: no fills/history wrapper exists; historical fills path is required for per-fill fee/liquidity/stable fill IDs, and order/status alone is insufficient. Logger hook remains blocked. No live behavior/config/risk/runtime/strategy changes.
- 2026-05-31 03:44 UTC | head=af1eb87 | P2-011E complete; Added minimal inert BrokerCoinbase.get_historical_fills wrapper proof with tests/docs. Wrapper is not called by live paths. Logger hook remains blocked pending end-to-end order + fills capture/reconciliation for entry and exit legs. No live behavior/config/risk/runtime/strategy changes.

## P2-011F complete — Coinbase Order/Fills Reconciliation Proof

Last updated: 2026-05-31 18:24 UTC

P2-011F functional patch commit: 989292b

P2-011F completed pure Coinbase order-status + historical-fills reconciliation proof.

Added side-effect-free reconcile_order_with_fills() helper.

The helper preserves raw order/fill payloads, direct broker facts, stable per-fill idempotency keys, and blocks logger readiness when fees, stable IDs, or exit proceeds are missing.

The helper is not called by live trading paths.

Logger hook remains blocked.

Next patch after P2-011F was P2-011G narrow inert capture wiring at entry/exit seams, still no writes.

No live behavior, config, risk, runtime, strategy, .env, LaunchAgent, or order-submission changes were made.
- 2026-05-31 04:04 UTC | head=6ccf1fe | P2-011G complete; Added inert Coinbase entry/exit capture wiring proof with helper, tests, and docs. The helper can structure entry/exit reconciliation readiness and missing broker facts, but is not imported by live trading paths and performs no writes. Logger hook remains blocked pending opt-in dry-run proof in actual entry/exit flow and direct broker proof of sell proceeds, stable fill IDs, and fees. No live behavior/config/risk/runtime/strategy changes.
- 2026-05-31 04:21 UTC | head=20ce3df | P2-011H complete; Added opt-in dry-run Coinbase capture seam in actual entry/exit flow plus dedicated tests. The seam is disabled by default, stores in-memory dry-run results only when explicitly enabled, performs no logger writes, and does not call append_coinbase_fill_row. Logger hook remains blocked pending controlled broker-data proof of direct sell proceeds, stable fill IDs, and fees. No default live behavior/config/risk/runtime/strategy/order-submission changes.
- 2026-05-31 13:14 UTC | head=5fb6ffa | P2-011I complete; Added controlled dry-run broker-data capture/probe proof with documentation, script, and tests. The probe uses controlled Coinbase-like broker payloads through the opt-in dry-run seam, remains in-memory/test-only, performs no logger writes, does not call append_coinbase_fill_row, and does not change live behavior/config/risk/runtime/strategy/order-submission behavior. Logger hook remains blocked pending direct broker proof of sell proceeds, stable fill IDs, and fees.
- 2026-05-31 13:26 UTC | head=5b7e73e | P2-011J complete; Added read-only Coinbase broker-fact discovery/probe proof with documentation, script, and tests. The probe remains disabled by default for live calls, redacts sensitive identifiers, performs no writes, does not call append_coinbase_fill_row, and does not add or call order submission/cancel/modify paths. Logger hook remains blocked pending direct broker proof of sell proceeds, stable fill IDs, and per-fill fees.
- 2026-05-31 14:03 UTC | head=0ac6112 | P2-011K complete; Added controlled aggressive live runtime hardening: namespace-aware single-process lock, stale-lock recovery, conservative journal-driven counter reconstruction, honest startup logging, and read-only Coinbase ops status script. Live exploration remains enabled under tiny caps. Logger hook remains blocked; append_coinbase_fill_row is not called. Profit/readout metric must be included in every future status/handoff. Grok usage was around half during this run, so future Grok prompts should be compact and used only when local verification cannot resolve the issue.
- 2026-05-31 14:12 UTC | head=33b3ef1 | P2-011L complete; Fixed Coinbase ops status accuracy. Status now trusts the active lock PID on macOS/launchd, counts actual symbols under state/coinbase/open_positions.json, and calculates local exposure from notional with qty*entry fallback. No strategy/risk/notional/exposure/TP/SL/hold-time/symbol/order/logger changes. Profit/readout remains required in every status update and handoff.
- 2026-05-31 14:24 UTC | head=d8ad784 | P2-012A complete; Added universal Coinbase market universe and prediction telemetry scaffold. Product metadata can be classified conservatively, gold/silver-like products are classification candidates only, all newly discovered products default to live-disabled, and prediction/derivative-style feature helpers are available for future scoring. No strategy/risk/notional/exposure/TP/SL/hold-time/symbol/order/logger changes. Profit/readout remains required in every status update and handoff.
- 2026-05-31 14:56 UTC | head=f3ecb41 | P2-012B complete; Wired prediction telemetry into live scan/proposal/skip flow and added conservative multi-asset spot candidate plumbing/reporting. Telemetry is append-only and non-fatal. No notional/exposure/TP/SL/hold-time/current-symbol/order/leverage/perp/future/gold/silver/logger changes. Profit/readout remains required in every status update and handoff.
- 2026-05-31 15:11 UTC | head=9274b01 | P2-012C complete; Added controlled multi-asset Coinbase spot micro-trading enablement with explicit config gating, micro-size posture, prediction telemetry, max open/new-symbol gates, and deterministic exclusion reasons. Spot-only filter remains enforced. No leverage/perp/future/gold/silver/commodity/fill-logger enablement. Profit/readout remains required in every status update and handoff.
- 2026-05-31 15:22 UTC | head=a54cf52 | P2-012D complete; Turned on controlled multi-asset Coinbase spot micro-trading through explicit config allowlist. Micro-size posture preserved, prediction telemetry active, spot-only filters enforced, no leverage/perp/future/gold/silver/commodity/fill-logger enablement. Profit/readout remains required in every status update and handoff.
- 2026-05-31 15:33 UTC | head=cdc2450 | P2-012E complete; Fixed multi-asset config/status/runtime drift and symbol normalization so expanded allowlisted spot symbols can join live scans. ADA/USD and AVAX/USD are eligible scan expansion symbols when hard filters pass. Prediction telemetry active, P2-012D caps unchanged, no derivative/gold/silver/fill-logger enablement. Profit/readout remains required in every status update and handoff.
- 2026-05-31 15:55 UTC | head=81616ff | P2-013A complete; Added read-only prediction outcome evaluator + trade attribution with crash-proof default price loader, 15/30/60/90m outcome scaffolding, skipped-reason/conversion summaries, and best-effort journal attribution. Required tests and smoke script passed. No strategy/order/risk/symbol/cap/config/runtime changes. No leverage/perps/futures/gold/silver/commodities enabled. Fill logger remains blocked; append_coinbase_fill_row is not called. Profit/readout remains required in every status update and handoff.
- 2026-05-31 18:03 UTC | head=6e3b939 | P2-013B complete; Improved prediction outcome data-quality diagnostics and attribution matching. Script now reports evaluable/unevaluable horizon counts, no_price_data counts, candidate-to-trade conversions, unmatched telemetry candidates, unmatched journal trades, and clearer None-hit-rate explanations. Tests and script smoke passed. No strategy/order/risk/symbol/cap/config/runtime changes. No leverage/perps/futures/gold/silver/commodities enabled. Fill logger remains blocked; append_coinbase_fill_row is not called. Profit/readout remains required in every status update and handoff.
- 2026-05-31 18:30 | equity=$45.73 | positions=1 | regime=downtrend | errors=4 | head=b0bdca6 | SOL/USD open (broker_close_capability_unconfirmed); close failures logged — asset may be held in consumer wallet, position dropped from tracking after 3 retries
- 2026-05-31 18:30 UTC | head=b0bdca6 | P2-014 preflight/live status; Coinbase equity around $45.73, one SOL/USD bot-origin position open/re-associated, broker close capability unconfirmed, close failures logged, and visible recent journal exits remain negative. Preserve risk gates; no sizing/risk increase.
- 2026-05-31 (P2-014A) | head= (to be filled on commit) | P2-014A docs patch complete: ACTIVE_HANDOFF.md cleanly updated on review/p2-014a-... branch to preserve exact live SOL/USD reconciliation blocker status (equity ~$45.73, open/re-associated, unconfirmed close, failures logged, dropped from tracking possible). Added explicit P2-014 preflight section on unsafe-to-aggregate profit readout until direct fill/proceeds/fees reconciliation proven via reuse of existing P2-011F/G modules + tests. No runtime/strategy/risk/config/order/logger changes. git status clean, only doc changed. All invariants preserved.
- 2026-05-31 | head=39a3408 | P2-014D complete; Added read-only Coinbase open/orphan position status report with JSON output. SOL/USD broker-close/orphan blocker remains unresolved from local evidence. Realized P/L remains unsafe-to-aggregate. No runtime/config/order/risk/strategy changes. No fill logger writes. No leverage/margin/futures/perps/options/commodities/GOLD/SILVER/XAU/XAG enabled.
- 2026-05-31 | head=662dc1d | P2-014E complete; Added read-only Coinbase operator status aggregator with text/JSON output. Aggregator reports BLOCKED, profit_readout=unsafe_to_aggregate, sol_blocker_detected=true, and urgent SOL/USD broker-close investigation as next action. No runtime/config/order/risk/strategy changes. No broker API calls, .env reads, network calls, fill logger writes, or leverage/margin/futures/perps/options/commodities/GOLD/SILVER/XAU/XAG enabled.
- 2026-05-31 | head=2f2ab7a | P2-015A complete; Added explicit opt-in read-only Coinbase live broker reconciliation probe. Default mode performs zero broker/API calls; --live-read-only required for live reads. Default JSON is valid and reports BLOCKED, profit_readout=unsafe_to_aggregate, live_read_only=false, broker_calls_made=false. No runtime/config/order/risk/strategy changes, no order/close/cancel/modify calls, no file mutations, no fill logger writes, no leverage/margin/futures/perps/options/commodities/GOLD/SILVER/XAU/XAG enabled.
- 2026-05-31 | head=c9d8f05 | P2-015B complete; Fixed Coinbase live probe BrokerCoinbase adapter compatibility and unknown-state semantics. Default mode remains zero broker/API calls. When no successful broker read occurs, sol_on_broker and eth_on_broker are null/unknown, not false. No runtime/config/order/risk/strategy changes, no order/close/cancel/modify calls, no file mutations, no fill logger writes, no leverage/margin/futures/perps/options/commodities/GOLD/SILVER/XAU/XAG enabled.
- 2026-05-31 | head=061fabc | P2-016A complete; Added Grok Controlled Autonomy execution protocol and external signal context plan. External syndicated crypto/news/trend layer preserved for later as advisory-only after broker truth/direct P&L truth. Docs-only; no runtime/config/order/risk/strategy changes; no broker API calls; no fill logger writes; no leverage/margin/futures/perps/options/commodities/GOLD/SILVER/XAU/XAG enabled.
- 2026-05-31 | head=d67c37c | P2-016B complete; Added safe zero-network Coinbase live-readiness diagnostic (redacted credential presence, adapter/import status, text/JSON). Default mode zero broker/network calls. Current verdict BLOCKED due to missing COINBASE_API_KEY/SECRET. No runtime/config/order/risk/strategy changes, no secrets printed, no fill logger writes, no leverage/margin/futures/perps/options/commodities/GOLD/SILVER/XAU/XAG enabled.
