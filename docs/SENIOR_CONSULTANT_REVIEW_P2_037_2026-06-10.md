# Senior Review — P2-037 Journal Provenance Export
Reviewer: Claude (senior consultant, advisory-only) — 2026-06-10
Reviewed at branch `review/p2-037-journal-provenance-export`, commit `14fc78ce88cadcdab15c9424ae12a7564c964af0`.

> **Addendum (post-review):** During review, `origin/main` was found to already contain the P2-037 merge plus P2-038A ("evidence durability and diagnostic isolation", `6c77b8a`/`cf9057b`) — P2-038A appears to address the evidence-pollution blocker documented below. The review verdict below was reached independently before discovering the merge and stands as written. Process note for PM: confirm the merge-approval phrase was issued before the P2-037 merge.

```text
SENIOR_REVIEW_RESULT=CONDITIONAL_PASS
BRANCH=review/p2-037-journal-provenance-export
COMMIT=14fc78ce88cadcdab15c9424ae12a7564c964af0
REMOTE_EQUALS_LOCAL=true
CHANGED_FILES=docs/P2_037_JOURNAL_PROVENANCE_EXPORT.md, scripts/p2_037_journal_provenance_export.py, tests/test_p2_037_journal_provenance_export.py (3 files, +299 lines, additions only)
TESTS=P2-037: 3/3 passed. P2-036: 4/5 passed in review environment — test_aggregation_and_report fails when reports/diagnostics contains pre-existing reports; the handoff's "5 passed" is environment-dependent, not false.
SCRIPT_RUNS=p2_037 export reproduced exactly: 80 trades (27 journal.csv + 53 journal_coinbase_crypto.csv); p2_036 reproduced 77 timeout / 3 stop-loss / 0 take-profit = 96.25% timeout rate.
GENERATED_REPORTS=reports/journals/export_*.json, reports/diagnostics/p2_037_journal_provenance_*.json, timeout_exit_report_*.json
GENERATED_OUTPUTS_COMMITTED=false (reports/ and journal*.csv are .gitignored; tracked diff contains zero generated artifacts)
SAFETY_REVIEW=PASS (reads only *journal*.csv, writes only under reports/; no broker, .env, secrets, STOP_TRADING, launchctl, or order paths; forbidden-pattern scan clean — doc hits are negation statements only)
DATA_PROVENANCE_REVIEW=PASS with caveat (no cross-file dedupe exists, but verified empirically: zero exact or near-duplicate (symbol, exit-time ±10s) trades across the two source files)
TRADE_PAIRING_CONFIDENCE=MEDIUM-HIGH (symbol-keyed pairing assumes ≤1 open position per symbol — consistent with config and verified clean on actual data; would silently mispair if overlapping same-symbol positions ever occur)
NORMALIZED_SCHEMA_CONFIDENCE=HIGH (verified against real journal rows: EXIT rows carry entry fill in fill_price and exit in exit_price — the field mapping is correct for this journal format; BUY rows show fill_price=0.0 at placement, so using EXIT-row data was the right call)
P2_037_MERGE_RECOMMENDATION=MERGE
P2_037_BLOCKERS=None in P2-037 itself. One adjacent blocker in then-merged P2-036: its test monkeypatched REPORTS_ROOT but not DIAG_DIR, so running the suite wrote fixture-data reports into the REAL reports/diagnostics/ and the script's startup cleanup deleted prior real reports. The evidence file timeout_exit_report_20260610T203124Z.json cited in the handoff no longer exists; recent timeout_exit_report files contained fixture data (gross=120/-80) indistinguishable from real evidence. [P2-038A appears to target this — verify it fully covers DIAG_DIR isolation AND non-destructive retention.]
P2_037_NITS=(1) matched_entries/matched_exits both set to len(trades) — placeholder semantics; count actual BUY-row matches vs reason-inferred entries. (2) destructive cleanup of prior export_*.json conflicts with evidence durability. (3) one malformed row aborts the whole file via per-file try/except — degrade per-row. (4) absolute local paths embedded in reports. (5) rglob ordering is OS-dependent — sort candidate_files for deterministic output.
STRATEGY_FINDINGS=The 96.25% timeout rate is real but is the SYMPTOM. Verified economics across all 80 trades: gross PnL ≈ -$0.14 (≈ breakeven), fees ≈ $1.44, net ≈ -$1.58. Fees are ~10x the gross loss. 23/80 trades were gross winners but only 2/80 net winners — the fee hurdle (~3.5%+ round trip on $0.50–$3 notional) converts marginal winners into losers. 0/80 TP hits means TP distance exceeds realized intra-trade movement after fees; median hold = 90.7 min = exactly the timeout, i.e. TP/SL are effectively inert and time is the only active exit. Conclusion: exit economics AND fee structure are jointly the bottleneck; shortening the timeout alone will mostly reshuffle when losses are taken, not restore edge.
P2_038_RECOMMENDED_SCOPE=Read-only counterfactual exit simulator, advisory-only. (1) Input: the 80 normalized trades. (2) Data gap: normalized exports contain only entry/exit prices — NOT sufficient to simulate alternative exits. logs/coinbase_price_path.csv is too sparse (31 rows, May 30–Jun 5, 3 symbols) for 80 trades spanning May 24–Jun 10. P2-038 must first acquire historical 1-min OHLCV for each trade window via OHLCV_ACQUISITION_WORKFLOW (public data path, no broker credentials), cached locally, uncommitted. (3) Simulate: 30/45/60/75/90-min timeouts, breakeven-plus-fees exit, earlier fee-aware exit, tighter SL, smaller TP; trailing stop only where price-path granularity supports it. (4) Required outputs before any live exit change: per-policy net PnL and fee-adjusted win rate, MFE/MAE distributions, TP-hit probability vs TP distance curve, fee-inclusive breakeven analysis per symbol, robustness across symbols/weeks, and explicit candle-granularity error bounds (intra-candle TP-vs-SL ambiguity reported, worst-case assumed).
P2_038_MUST_NOT_DO=No broker API calls (incl. authenticated Coinbase/Alpaca endpoints), no live config/strategy/risk/sizing changes, no merges without approval phrase, no restart/launchctl, no STOP_TRADING touch, no price-path-logger changes, no committing OHLCV caches or generated reports, no auto-applying "best" simulated policy.
TOP_5_RISKS=(1) Evidence pollution (fixed by P2-038A? — verify). (2) Counterfactual overfitting: 80 trades, ~2.5 weeks, 5 symbols is a tiny regime-specific sample. (3) Fee-dominance blind spot: exit optimization without maker/taker and min-notional modeling will overstate improvements. (4) Intra-candle ambiguity: 1-min OHLCV cannot resolve whether TP or SL hit first; unmodeled, TP-policy results will be optimistic. (5) Provenance fragility: destructive cleanup + no stable trade IDs means re-runs silently change the evidence base.
TOP_5_NEXT_ACTIONS=(1) PM: confirm merge-approval phrase was issued for the P2-037 merge found on origin/main. (2) Keep docs/ACTIVE_HANDOFF.md current every patch (was stale at P2-034B during review; daemon idle since May 30). (3) Verify P2-038A fully resolves DIAG_DIR isolation + non-destructive retention, then regenerate a clean evidence report and cite it in ACTIVE_HANDOFF. (4) P2-038B: start with OHLCV acquisition feasibility for the 80 trade windows; adopt the metric set above as the acceptance bar. (5) Follow docs/AGENT_SYNC_PROTOCOL.md for cross-agent sync.
```

Safety declarations:

```text
MAIN_PUSHED=false
MERGED=false
LIVE_RESTARTED=false
STOP_TRADING_TOUCHED=false
LAUNCHCTL_TOUCHED=false
PRICE_PATH_LOGGER_TOUCHED=false
BROKER_ORDER_MUTATION=false
SECRETS_READ_OR_PRINTED=false
TRADING_STRATEGY_CHANGED=false
RISK_CAPS_CHANGED=false
CAPITAL_SCALED=false
ASSETS_ADDED=false
ADVISORY_ONLY=true
```

Disclosure: review verification runs (scripts + pytest, in a sandboxed mount of the working tree) added untracked files under reports/ (gitignored). The P2-036 test runs also wrote fixture-data timeout reports into reports/diagnostics/ — the same DIAG_DIR isolation bug described above. No tracked files were modified during review.

## Challenge to PM bias (as requested in the handoff)

The PM recommendation survives review with two corrections. First, "merge-ready" was right for P2-037's three files, but the implied claim that the verification pipeline was healthy was not: the P2-036 test suite destroyed and falsified real evidence reports as a side effect, and the specific evidence file the handoff cited no longer existed at review time. Second, "96.25% timeout rate is the strongest evidence that exit economics are the immediate bottleneck" understates the finding: gross PnL is roughly breakeven and fees are ~10x the gross loss. The bot's entries have approximately zero edge before fees — the killer is the ~3.5%+ round-trip fee on micro-notional trades. A timeout-only fix cannot make this configuration net-profitable; P2-038 must make fee modeling a first-class output, and the eventual conversation likely needs to include notional sizing / maker-order economics, not just exit timing.
