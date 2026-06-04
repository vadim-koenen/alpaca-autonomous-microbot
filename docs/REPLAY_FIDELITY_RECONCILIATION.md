# REPLAY FIDELITY RECONCILIATION (P2-025M)

## Why this exists
P2-025L produced economics and fee scenario results (including "fee_drag_dominant", break-even ~0.74%, notional sensitivity, and per-scenario win rates ~52% under replay vs ~2% journal). A senior consultant review identified that the underlying replay is not yet trustworthy: direction_match only 0.50 and replay-with-journal-fees net (+0.249 on 48) does not reconcile to realized journal analyzed net (-1.090). The ~$1.34 gap across 48 cycles suggests the replay may be manufacturing most or all of the apparent gross edge (+1.278 replay gross vs journal analyzed gross near zero or negative).

P2-025M adds per-cycle fidelity reconciliation before any maker/post-only implementation, exit tuning, or scaling. Do not treat P2-025L fee scenarios as actionable until this report passes its conservative gates.

## What is measured
- Only cycles with OHLCV coverage are analyzed (skipped-cycle accounting preserved and detailed).
- Per analyzed cycle (using journal entry_price/notional exactly, replay exit derived from gross on the window bars + slippage model):
  - journal vs replay entry/exit prices and bases (exact journal fill for entry; bar high/low/close + adverse slip for replay exit)
  - journal gross, replay gross, gross residual (replay - journal)
  - journal fees, replay net using journal-recorded fees, net residual
  - sign match (gross), direction_match from replay run
  - residual as % of notional
- Aggregates: signed/absolute total residual, mean/median/p75/p90/max abs residual, median % of notional.
- Direction fidelity: overall match, mismatch count, timeout-specific match, list of mismatches.
- By-symbol, by-strategy, by-exit-reason breakdowns (analyzed/skipped, dir match, residuals).
- Timeout-specific (max-hold) fidelity, since these dominate.
- Skipped-cycle details: symbol, entry/exit ts, reason, whether fixable by re-fetch/import.
- Plain-English `replay_trustworthy: true/false` + failed gates + suspected drivers.

## Trust gates (conservative)
- direction_match >= 0.85
- median absolute residual <= 10% of notional (median of per-cycle abs(res)/notional)
- abs(signed total net residual using journal-recorded fees) <= $0.10
- If any gate cannot be evaluated (missing notionals, prices, etc.), replay_trustworthy=false and the gate is listed as unavailable.

## Current verdict (as of this run on real untracked data)
- cycles_seen: 50, analyzed: 48, skipped: 2 (ADA/USD full gap + 1 ETH/USD partial)
- journal_analyzed_gross: ~-0.061
- replay_gross: +1.278
- signed gross residual: +1.339 (matches consultant ~$1.34 gap)
- abs gross residual total: ~2.26
- med abs gross: ~0.026
- p90 abs: ~0.122
- dir_match: 0.50 (24 mismatches)
- timeout_dir_match: ~0.51
- replay_trustworthy: false
- failed gates: direction_match < 0.85, abs(signed net residual using journal fees) > 0.10
- suspected drivers: low direction match (bias in exit price or entry vs journal fills); timeout dominance amplifies close-vs-fill discrepancy.
- Senior consultant note (enforced): P2-025L fee scenarios are not actionable until fidelity passes.

## Skipped ADA/ETH gaps (current data)
- ADA/USD: 1 seen, 0 with coverage (full window gap). entry/exit ~2026-06-03 21:38 to 23:08. Fixable by re-fetch via public Exchange candles for that window + import_validate --write.
- ETH/USD: 15 seen, 14 with, 1 without (partial gap at one cycle's window start/end). The specific cycle entry/exit shown in script output.
- ALGO/BTC/SOL: 100% coverage in current local untracked data.
- These 2 skipped do not block the fidelity verdict on the 48 covered cycles. The report details them for acquisition follow-up.

## What must be true before P2-025N (maker/post-only feasibility)
- Sustained high coverage on the current (or larger) journal window set.
- replay_trustworthy = true under the gates above on real (untracked) data.
- direction_match high and residuals small enough that replay gross is credible vs journal gross (not manufactured by bar granularity/slippage assumptions).
- Explicit senior-consultant or human sign-off that the per-cycle reconciliation supports using the harness for fee-scenario "what if" experiments.
- Still no live, no paper probes, no config changes, review branch only.

## Invariants
- Pure offline. Reuses existing parse_journal_cycles, load_bars_from_fixture, run_journal_window_replay (zero-fee run for pure gross), and coverage helpers.
- No broker calls, no orders, no --live-read-only, no .env/secrets, no launchctl, no runtime mutation.
- Always emits trade_permission=none / risk_increase=not_approved / scaling_allowed=false.
- data/offline_ohlcv/ remains untracked.
- Review push only; no merge to main.
- Does not implement maker logic, does not modify exits, does not add probes.

This report exists to make the replay-vs-realized gap visible and quantifiable. Until it passes, P2-025L results remain diagnostic only.
