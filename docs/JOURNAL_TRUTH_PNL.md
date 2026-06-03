# Journal-Truth P/L Readout

P2-025C adds an offline journal-truth P/L report for Coinbase live exits. The
purpose is direct operator loss control: the local Coinbase journal already
contains broker-recorded fills, fees, exits, and net P/L fields, so the bot
should not treat the current P/L state as unknowable while waiting for a stricter
direct-capture proof.

## Two Readouts

`journal_recorded_broker_backed` means the report was computed from the local
Coinbase journal. This is adequate for operator caution, shutdown decisions, and
sequencing the next offline backtest work. It is not a scaling unlock.

`numeric_safe_direct_capture` remains the stricter evidence gate for any future
aggregation or scaling decision. It requires direct broker fee/proceeds facts in
the newer resolver path. P2-025C does not weaken that gate and does not claim
that the journal is sufficient for increased risk.

The important policy change is semantic: `unsafe_to_aggregate` must not be read
as "no evidence." It means the strict aggregation gate is not satisfied. The
journal can still contain enough broker-recorded loss evidence to justify
defensive action.

## Senior-Consultant Sanity Anchor

The consultant review found the current journal appears to contain approximately:

- 47 live closed cycles from May 25 through June 2
- 1 winning cycle and 46 losing cycles
- cumulative net P/L around -$1.03
- 46 of 47 exits caused by max hold time around 90 minutes

The script is the authority for exact values. If the live journal changes, the
report should print the current script-derived values rather than forcing these
anchor numbers.

## Probe Shutoff

The legacy Coinbase probe path used a 0.50 USD ticket. Against observed Coinbase
fees, that path is structurally uneconomic because the round-trip fee hurdle is
too large for a micro ticket. P2-025C sets `coinbase_probe_enabled: false` as a
defensive reduction in activity pending a backtest/replay harness.

The probe notional value is left unchanged for audit clarity. No trade cap,
notional cap, max-open limit, daily-trade limit, eligible symbol list, SOL
exclusion, stop-loss, take-profit, hold-time, strategy threshold, runtime
process, or LaunchAgent state is changed.

## Output Contract

`scripts/coinbase_journal_truth_pnl_report.py` reads a CSV journal by header name
and skips blank, malformed, warning, non-live, and non-exit rows. The report
emits:

- total closed cycles
- wins, losses, breakeven cycles, and win rate
- gross P/L sum, fees sum, and net P/L sum
- date range
- per-strategy breakdown
- per-symbol breakdown
- normalized exit-reason breakdown
- `readout_class=journal_recorded_broker_backed`
- `numeric_safe_direct_capture_available=false`
- `trade_permission=none`
- `risk_increase=not_approved`
- `aggregation_allowed=false`
- `scaling_allowed=false`

The report is offline and observational. It does not grant trading authority,
does not increase risk, and does not modify state.
