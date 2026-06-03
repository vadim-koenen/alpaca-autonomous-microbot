# OFFLINE_BACKTEST_REPLAY_HARNESS (P2-025D)

## Why this exists
After P2-025C (probe shutoff) and journal-truth analysis showing ~2% win rate, 48 closed cycles, dominant "max hold time 90min exceeded" exits, and net negative P/L, we need an offline way to evaluate strategy and exit logic changes before any live modification.

This harness is the first step toward evidence-based exit overhaul (P2-025E).

## Hard properties (enforced)
- **Offline / fixture only**. Loads OHLCV from local JSON/JSONL/CSV under tests/fixtures/offline_backtest/.
- **No live broker APIs**, no orders, no --live-read-only, no .env/secrets, no launchctl, no runtime mutation.
- Always emits:
  - `trade_permission: "none"`
  - `risk_increase: "not_approved"`
  - `scaling_allowed: false`
- No changes to live config, caps (max_open=1, max_trades=3, notional 5/10), symbols, or SOL exclusion.
- Does not authorize or simulate live trading.

## What it models (baseline)
- Deterministic replay over a sequence of bars (close-to-close with adverse slippage buffer).
- Entry at close of signal bar (or first bar for demo).
- Exits: take_profit, stop_loss, max_hold_time_exceeded, end_of_data.
- Fees on entry notional and exit notional (configurable rates).
- Slippage/spread buffer applied adversely on fills.
- Hold time in wall minutes (or bars).
- Output per closed trade: symbol, strategy, times, prices, exit_reason, gross_pnl, fees, net_pnl, hold_minutes, notional.
- Aggregates + breakdown by exit_reason.

Documented limitation: first version is a replay scaffold, not a full limit-order-book / partial-fill / maker/taker simulation. It is sufficient to compare policies (e.g. "max-hold only" vs "TP+SL+trailing+fee-aware").

## Relation to journal-truth
The live journal_truth_pnl_report.py shows real closed-cycle economics (gross, fees, net, exit reasons) from actual fills.
This backtest lets us generate synthetic but controlled closed cycles against known price paths to test "what if we changed the exit rules?"

## How it supports P2-025E
Future patches can:
- Add new entry/exit policies as pluggable functions.
- Run the same fixtures with old vs new policy.
- Require "net_pnl_sum improves and win_rate improves on the fixture set" before proposing live change.
- Keep live changes gated behind backtest evidence + human review.

## Usage (offline)
python3 scripts/coinbase_offline_backtest_report.py --json
python3 scripts/coinbase_offline_backtest_report.py --fixture tests/fixtures/offline_backtest/tp_hit.json --take-profit-pct 3 --stop-loss-pct 1.5 --max-hold-minutes 90 --json

## Fixtures (required baseline)
- tp_hit.json : take_profit exit
- sl_hit.json : stop_loss exit
- hold_timeout.json : max_hold_time_exceeded
- fee_drag.json : gross positive, net negative due to fees

All tests pass with these; adding more price paths is encouraged for P2-025E.

## Safety / verification
- Full test suite (including isolation tests) must pass.
- py_compile + pytest -q
- Smoke emits the permission fields.
- Safety grep must find zero live/order/launchctl/.env patterns in the harness, report, tests, and docs.
- No config, risk, sizing, or symbol changes in this patch.
- Review branch only; no merge, no restart.

## Next
P2-025E will use this harness (and the journal) to design and validate improved exit logic (e.g. dynamic hold, trailing, fee-aware exits) entirely offline/simulated first.

Acceptance for live: any proposed exit change must show material improvement in net-of-fee backtest metrics on the fixture set (and not degrade other metrics) before any risk of live capital.
