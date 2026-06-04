# P2-025P Live Exit-Policy Parity Report

P2-025P adds an offline predictive parity report for Coinbase live exit behavior. It does not change the existing replay harness or live exit code.

## What It Compares

The report compares three modes:

- `original_simulated_tp_sl_high_low`: the existing replay harness, unchanged, using intra-candle high/low TP/SL detection.
- `journal_exit_aligned_control`: the P2-025O reconciliation control that uses actual journal exit price/time. This is not predictive evidence.
- `predictive_live_exit_policy`: an offline approximation of live exit checks using journal entry facts, candle-close scan decisions, TP/SL thresholds, and max-hold timeout.

The predictive mode does not use journal exit price or journal exit timestamp for prediction. Timeout decisions use candle close at or after `entry_time + max_hold_minutes`, not high/low.

## Trust Gates

Predictive replay is trustworthy only if all gates pass:

- `direction_match >= 0.90`
- `exit_reason_match_rate >= 0.90`
- `timeout_exit_match_rate >= 0.95`
- `abs(signed gross residual) <= 0.10`
- `timeout residual <= 0.05`
- `exit timestamp median delta <= one scan/bar interval`
- `forward_looking_fields_used=false`
- `aligned_mode_used_for_prediction=false`

If any gate fails, the result remains diagnostic only. It does not approve maker/post-only work, exit tuning, scaling, or live changes.

## Usage

```bash
python3 scripts/coinbase_live_exit_policy_parity_report.py --json
python3 scripts/coinbase_live_exit_policy_parity_report.py
python3 scripts/coinbase_live_exit_policy_parity_report.py --top-n 20
```

Optional output is available, but the script does not write by default:

```bash
python3 scripts/coinbase_live_exit_policy_parity_report.py --json --output reports/replay_fidelity/p2_025p_parity.json
```

## Current Verdict

P2-025O proved that journal-exit alignment reconciles residuals by construction. P2-025P asks the harder question: can an offline predictive approximation reproduce live exit outcomes without using journal exits as an answer key?

Current covered-cycle result on local offline data:

- `cycles_seen=50`
- `cycles_analyzed=48`
- `cycles_skipped=2` (ADA/USD and ETH/USD OHLCV gaps)
- `predictive_replay_trustworthy=true` on the covered 48 cycles
- `forward_looking_fields_used=false`
- `aligned_mode_used_for_prediction=false`
- `journal_exit_aligned_control` remains control-only

Because coverage is still incomplete, the next step is to close the ADA/ETH offline OHLCV gaps and rerun parity to full coverage before maker/post-only feasibility is scoped. This patch still authorizes no live behavior.

Preserved invariants:

- `trade_permission=none`
- `scaling_allowed=false`
- `risk_increase=not_approved`
- no maker/post-only implementation
- no exit tuning
- no live config/risk/runtime change
