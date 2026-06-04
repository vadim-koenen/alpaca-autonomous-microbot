# P2-025R Maker/Post-Only Feasibility Model

## Why This Exists

P2-025Q closed the ADA/ETH offline OHLCV gaps and reran predictive live-exit-policy parity at full coverage:

- `cycles_seen=50`
- `cycles_analyzed=50`
- `cycles_skipped=0`
- `coverage_rate=1.0`
- `predictive_replay_trustworthy=true`
- `failed_predictive_gates=[]`
- `forward_looking_fields_used=false`
- `aligned_mode_used_for_prediction=false`

That made maker/post-only feasibility safe to study as offline modeling only. It did not authorize implementation, probes, restart, exit tuning, or scaling.

## What The Report Measures

`scripts/coinbase_maker_post_only_feasibility_report.py` uses the `predictive_live_exit_policy` mode as the replay basis, then separates:

- predictive gross P/L
- fees
- net P/L
- per-symbol results
- per-strategy results
- per-exit-reason results
- non-fill and adverse-selection haircuts
- notional sensitivity at `$0.50`, `$1`, `$5`, and `$10`

Fee scenarios:

- `journal_recorded_fees`
- `taker/taker`
- `maker/maker`
- `maker_entry_taker_exit`
- `taker_entry_maker_exit`
- `zero_fee_theoretical`

Haircuts are intentionally conservative:

- adverse selection reduces favorable gross only; losses remain intact
- non-fill removes winning net contribution only; losses remain intact

## Feasibility Gates

Maker/post-only cannot advance unless all gates pass:

- `predictive_replay_trustworthy=true`
- full coverage with `cycles_skipped=0`
- `maker/maker` net positive
- `maker/maker` net positive after 30% adverse-selection plus 30% non-fill haircut
- `maker/maker` net win rate at least `0.45`
- signed gross residual remains inside predictive parity tolerance
- `forward_looking_fields_used=false`
- `aligned_mode_used_for_prediction=false`
- at least 50 analyzed cycles

Passing these gates still would not authorize live implementation. It would only justify a later implementation design review.

## Current Verdict

Current offline result:

- `predictive_gross_pnl_sum=-0.26885977`
- `journal_recorded_on_analyzed_cycles.net_pnl_sum=-1.37856949`
- `taker/taker.net_pnl_sum=-2.57821663`
- `maker/maker.net_pnl_sum=-1.03864539`
- `maker_entry_taker_exit.net_pnl_sum=-1.80735557`
- `taker_entry_maker_exit.net_pnl_sum=-1.80950645`
- `zero_fee_theoretical.net_pnl_sum=-0.26885977`
- 30% adverse-selection plus 30% non-fill `maker/maker.net_pnl_sum=-1.07039283`
- 50% adverse-selection plus 50% non-fill `maker/maker.net_pnl_sum=-1.08942061`
- `maker/maker.win_rate=0.02`
- `fee_break_even_threshold=null`
- `fee_fix_verdict=fees_alone_cannot_fix_negative_predictive_gross`
- `maker_feasible_offline=false`

Failed feasibility gates:

- `maker/maker` net must be positive
- `maker/maker` net after 30% non-fill/adverse-selection haircut must be positive
- `maker/maker` net win rate must be at least `0.45`

The important finding is that the predictive gross edge is negative even before fees. Maker fees cannot fix a strategy whose predictive gross is already below zero.

## What This Does Not Prove

This report does not prove that maker/post-only would work in live markets. It also does not prove fill probability, queue position, adverse selection, spread capture, or live order behavior.

It is not a paper-trading plan and not a live-trading plan.

## Preserved Invariants

- `implementation_authorized=false`
- `paper_probe_authorized=false`
- `live_probe_authorized=false`
- `scaling_authorized=false`
- `trade_permission=none`
- `scaling_allowed=false`
- `risk_increase=not_approved`
- no live broker calls
- no `--live-read-only`
- no orders/cancels/closes/modifications
- no `.env` or credential reads
- no launchctl or restart
- no live config/risk/runtime changes
- no maker/post-only implementation
- no live exit logic changes
- no strategy threshold tuning

## Next Required Action

Do not implement maker/post-only. Fees alone are not sufficient under the current predictive replay basis.

The next high-ROI work should stay offline and explain why predictive gross is negative before fees, without changing live strategy thresholds or exit behavior.
