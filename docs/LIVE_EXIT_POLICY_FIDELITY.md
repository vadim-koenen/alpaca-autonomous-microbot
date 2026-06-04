# LIVE EXIT-POLICY FIDELITY / JOURNAL-EXIT-ALIGNED REPLAY MODE (P2-025O)

## Why P2-025O exists
P2-025N (price-basis reconciliation) on main at 8316f4b proved the replay divergence (direction_match=0.50, signed gross residual +1.33933688) is exit-basis driven, not entry-basis driven:
- entry residual contribution: ~0 (by harness design: replay always uses journal fill_price for entry)
- exit residual contribution: +1.33933688
- timeout-only residual: +1.26723778 (47/48 cycles)
- dominant driver: timeout_exit_basis_issue / exit_price_bias
- replay entry basis: "journal exact fill price" for all 48
- replay exit basis: "bar high + adverse slippage (take_profit)" 25 + "bar low + adverse slippage (stop_loss)" 23
- journal prices mostly inside nearest OHLCV h/l (entry 44/48, exit 43/48)
- Problem: the simulated replay manufactures TP/SL exits inside windows where the live journal recorded max-hold/timeout exits at the actual fill price.

P2-025O adds an offline journal-exit-aligned replay mode to test whether forcing the replay exit basis to follow the journal's recorded exit timestamp + reason + price (for the dominant timeout case) reconciles residuals to ~0 and direction_match to 1.0. This is strictly instrumentation/diagnostic. No strategy changes, no live changes, no exit logic mutation.

## P2-025N finding recap (exit-driven residual)
See docs/REPLAY_PRICE_BASIS_RECONCILIATION.md for full. Key: replay_trustworthy=false under P2-025M gates. The +1.34 gross edge is almost entirely from replay exit simulation differing from journal's live exit fills on timeout cycles. Entry was already "journal exact".

## Definition of simulated replay mode (unchanged)
- Uses the existing run_journal_window_replay + _simulate_one_trade on the journal [entry_time, exit_time] window bars.
- Entry: journal exact fill_price + notional (zero fee for gross purity).
- Exit: intra-bar high/low detection for TP (bar.h >= tp_level → high + adverse slip) or SL (bar.l <= sl_level → low + adverse), SL precedence on tie; fallback to close + adverse on max_hold or end_of_data.
- Produces "simulated" gross, exit_reason (often take_profit/stop_loss even inside journal-timeout windows), direction_match (net sign vs journal recorded).
- This is the "current TP/SL high-low based exit simulation".

## Definition of journal-exit-aligned mode (new, post-compute only)
- For each covered cycle, after running the (unmodified) simulated replay to obtain the "simulated" numbers:
  - If journal "exit_price" > 0 for the cycle, use it exactly as the aligned exit price (and rec_exit as reason).
  - Compute aligned_gross = (notional / journal_entry_price) * journal_exit_price - notional (zero-fee equivalent).
  - aligned_net_with_journal_fees = aligned_gross - journal_fees_recorded
  - direction_match aligned = sign match of that net vs journal recorded net.
- This mode never calls the simulator for exit; it post-adjusts P/L to journal's recorded exit fill.
- "journal-exit-aligned replay exit price" is either the journal exact or the fallback value (see below).
- Per-cycle also records: used_journal_exact_exit_price (bool), aligned_fallback_note (None or "candle_close_fallback"), journal_exit_within_candle_hl, residual_improved ("improved"/"worsened"/"unchanged").

## When journal exact exit price is used
- Whenever the parsed journal cycle has exit_price > 0 (present for the 48 analyzed cycles in current data).
- Especially for the 47 timeout/max-hold cycles: live bot exited by timeout policy at a broker fill price; we now use that price as replay's exit basis for the "aligned" comparison.
- Result: for those cycles, aligned_gross_residual == 0 (within decimal noise), direction often flips to match.

## When candle fallback is used
- If journal exit_price missing or <=0 for a cycle, locate nearest bar at journal exit_time (by symbol), use its .c (close).
- Mark explicitly: aligned_used_journal_exit_price=false, aligned_fallback_note="candle_close_fallback", aligned_replay_exit_price = that close.
- In current 48, zero cycles needed fallback (all had journal exit_price); fallback path is for robustness on future/partial journals.
- Note: fallback does not apply adverse slippage; it is an inferred close for diagnostic only. Clearly flagged.

## Before/after trust gates (same as P2-025M)
Gates (all must pass for replay_trustworthy=true; conservative):
- direction_match >= 0.85
- abs(signed total net residual using journal-recorded fees) <= $0.10
- median absolute residual <= 10% of notional (where calculable per-cycle; if not calculable for a mode, med_pct=None and gate is conservative on other criteria)
If any gate fails or un-evaluable in a way that violates, trustworthy=false + list failed_gates.

Results (real untracked data, 50/48/2):
- Simulated (current): direction_match=0.5, signed_gross_res=+1.33933688 (net res same), med_abs~0.026, p90~0.122, replay_trustworthy=false, failed=['direction_match < 0.85 (got 0.5)', 'abs(signed total net residual using journal fees) > 0.10 (got 1.33933688)']
- Aligned (journal-exit): direction_match=1.0, signed_gross_res=0E-8, med_abs=0E-8, p90=0E-8, replay_trustworthy=true, failed=[]
- direction_match_delta: +0.5
- residual_reduction_abs: 1.33933688, pct: 1.0
- timeout (47): sim res +1.26723778 / dir~0.5106 ; ali res 0 / dir 1.0
- by-symbol: e.g. ALGO sim_dir=0.0→1.0 res 0.40→0 ; ETH 0.071→1.0 res+1.107→0 ; BTC 1.0→1.0 res-0.337→0
- by-exit-reason: all timeout/max-hold categories show large sim positive res that goes to 0 when aligned; the 1 non-timeout (stop-loss) already closer.
- exit_policy_alignment_fixes_residual: true
- remaining_blockers: see below.

## Whether alignment resolves the residual
Yes for the covered cycles: when replay exit basis is forced to journal's actual live exit (price + ts + reason), the gross residual collapses to ~0, direction_match goes to 1.0 (48/48), and the mode passes all trust gates (replay_trustworthy=true under aligned). This confirms P2-025N diagnosis: the divergence was purely exit-policy / exit-basis (simulated intra-bar TP/SL vs live timeout policy fills), not entry or path or fees.

However, this does not mean "replay is now trustworthy for all uses":
- The alignment is a diagnostic lens only; the harness itself still simulates TP/SL.
- The live policy itself is heavy on timeout (47/48); the economics (fee drag on long holds) remain.
- 2 cycles still skipped (ADA/ETH gaps); full 50 would need re-run after gap close.
- Direction/residual under the actual (non-zero) fee model, varying notional, and any future maker/post-only fill assumptions would still need validation.

## What still blocks maker/post-only feasibility
- replay_trustworthy under the *simulated* (current harness) mode remains false. We only proved that *if* we had used the journal exit prices, the numbers would have matched.
- To use the harness for "what if maker fees" or "post-only exit policy experiments", the simulated mode itself must pass the gates on real data (after gap closure).
- Next: close the 2 gaps (ADA full ~2026-06-03 21:38-23:08, ETH partial ~2026-06-04 00:21-01:51) via offline/manual public fetch + scripts/coinbase_ohlcv_import_validate.py --write (no network executed here). Re-run price-basis + this fidelity on 50/50. Only then, if simulated trustworthy=true, consider a fresh review branch for gated maker/post-only feasibility study.
- Still no live, no paper, no config/risk/sizing/strategy/exit/LaunchAgent changes. Review branch only. data/offline_ohlcv/ + 4 unrelated remain untracked.

## Invariants preserved
- Pure offline. Reuses parse_journal_cycles, run_journal_window_replay (zero-fee simulated only; never mutated), _load_bars..., coverage helpers, _find_nearest_bar / _price_within / _is_timeout from prior P2 scripts. Aligned is pure math post-process on journal fields + bars for fallback.
- No broker, no orders, no --live-read-only, no .env/secrets, no launchctl, no network, no runtime mutation.
- --json / human / --top-n / --output (no default write) / --journal / --ohlcv-fixture / --max-cycles.
- Always trade_permission="none", risk_increase="not_approved", scaling_allowed=false.
- Skipped details + suggested gap-close cmds for ADA/ETH (same as 025N).
- Tests: deterministic fixtures, no-net/auth/live, no mutation proof, skipped accounting, gates, fallback, improvement, schema.
- Do not commit data/offline_ohlcv/ or the 4 unrelated untracked files.

## Baseline commands
```
python3 scripts/coinbase_replay_price_basis_reconciliation.py --json
python3 scripts/coinbase_live_exit_policy_fidelity.py --json
python3 scripts/coinbase_live_exit_policy_fidelity.py --top-n 10
```

## Related
- P2-025N: docs/REPLAY_PRICE_BASIS_RECONCILIATION.md + script
- P2-025M: docs/REPLAY_FIDELITY_RECONCILIATION.md + script
- P2-025L: docs/REPLAY_ECONOMICS_REPORT.md + script
- ACTIVE_HANDOFF.md (updated with this patch)

All evidence gates before any live or maker work. Stop after reporting. Do not merge.
