# OFFLINE_BACKTEST_REPLAY_HARNESS (P2-025D / P2-025E hardened)

## P2-025E Status (hardenings)
Claude review of P2-025D: harness is safe (offline, no live authority) but not yet trustworthy for strategy decisions.
Key finding from journal truth: live losses are **fee-drag dominated**, not merely exit logic.
- Journal: net ≈ -$1.09, gross ≈ -$0.06, fees ≈ $1.03 → **~94% of loss is fees**.
- P2-025D risked false confidence: TP/SL were close-only, exits static, fee assumptions understated taker drag, fixtures synthetic only.

**P2-025E hardenings address this** (still offline only, no live approval):
- Intra-bar TP/SL using candle high/low; SL precedence if both in same bar.
- Default fee scenario **taker/taker** (0.012/0.012 conservative); maker/maker optional via --fee-scenario (optimistic).
- New aggregates: net_pnl_per_trade, gross/net/return rates, cleared_fee_hurdle, percent_trades_clearing_fee_hurdle.
- Pluggable exit_policy scaffold (`--exit-policy static` default; `live_atr` is documented placeholder with deterministic output + TODO; full live ATR parity deferred, no import of strategy code).
- Journal-driven multi-entry replay (`--journal-fixture` + `--ohlcv-fixture`) for replaying actual historical entries against controlled price paths.
- 5 new fixtures + expanded tests + updated report JSON (schema v1 p2-025e, all safety flags, notes).
- This harness **still does not approve live strategy changes**. Future requirement: reproduce journal loss directionally (net negative, fee heavy) on fixtures before trusting "fixes".

Close-only TP/SL was insufficient. Taker/taker is the conservative gate. Maker scenarios are optimistic.

Next after harden: P2-025E exit logic experiments must improve net-of-fee metrics on the fixture set (incl. journal-driven) + pass all safety before any live proposal.

---
# OFFLINE_BACKTEST_REPLAY_HARNESS (P2-025D baseline)

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
python3 scripts/coinbase_offline_backtest_report.py --json --exit-policy static
python3 scripts/coinbase_offline_backtest_report.py --json --fee-scenario maker/maker --entry-fee-rate 0.006 --exit-fee-rate 0.006
python3 scripts/coinbase_offline_backtest_report.py --json --journal-fixture tests/fixtures/offline_backtest/journal_driven_multi_entry.json --ohlcv-fixture tests/fixtures/offline_backtest/fee_drag.json
python3 scripts/coinbase_offline_backtest_report.py --fixture tests/fixtures/offline_backtest/tp_hit.json --take-profit-pct 3 --stop-loss-pct 1.5 --max-hold-minutes 90 --json

## Fixtures (baseline + P2-025E)
- tp_hit.json, sl_hit.json, hold_timeout.json, fee_drag.json (P2-025D)
- intra_bar_tp.json : TP detected via high (close does not trigger)
- intra_bar_sl.json : SL via low
- both_tp_sl_same_bar.json : both levels crossed; SL wins
- fee_scenario_comparison.json : gross+ small move that fails taker but passes maker
- journal_driven_multi_entry.json : sample multi-entry journal for --journal-fixture tests

All tests pass with these.

## Safety / verification
- Full test suite (including isolation tests) must pass.
- py_compile + pytest -q (test_coinbase_offline_backtest.py + test_coinbase_offline_backtest_hardening.py)
- Smoke: default (taker), --exit-policy static, maker rates.
- Safety grep must find zero live/order/launchctl/.env patterns in the harness, report, tests, and docs.
- No config, risk, sizing, symbols, strategy thresholds, or LaunchAgent changes.
- Review branch only; push review; no merge, no restart, no live actions.

## Next (P2-025E continued)
Use the hardened harness + journal truth to experiment exit policies offline.
Any proposed change must:
- improve net_pnl_sum / win_rate / percent_clearing on the fixture set (incl. journal-driven + fee drag cases)
- keep taker/taker as conservative gate
- reproduce the observed journal loss character (fee dominated) before claiming improvement
- pass all safety, compile, tests, smokes
- still emit trade_permission=none etc.
- be on review branch, human reviewed, ff-only merge only after evidence.

This harness remains a gate, not trading authority.
