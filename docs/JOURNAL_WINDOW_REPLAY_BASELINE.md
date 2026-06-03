# JOURNAL_WINDOW_REPLAY_BASELINE (P2-025F)

## Why this exists
P2-025E hardened the offline backtest harness (intra-bar TP/SL with SL precedence, taker/taker default fees, policy/fee/journal support). Before using it to test "fixes" or exit optimizations, the harness must be proven to reproduce the **known live loss directionally**.

Journal truth (from `coinbase_journal_truth_pnl_report.py` and `journal_coinbase_crypto.csv`):
- ~48 live closed cycles
- 1 win / 47 losses (~2% win rate)
- net ≈ -$1.09
- gross roughly flat / slightly negative
- fees ≈ $1.03 (≈94% of the loss is fee drag)
- dominant exit: "max hold time 90min exceeded"

This patch adds a journal-window OHLCV replay baseline so the harness can be run against the **actual price paths** the live trades experienced (using local/fixture OHLCV for the entry→exit windows). The goal is directional reproduction of fee-dominated negative P/L, not yet profitability claims.

## How it works (offline)
- Parse journal for live EXIT cycles (header-name based, skips blank/WARN/non-EXIT/non-live/malformed).
- For each cycle derive/compute: symbol, strategy, entry_time (from exit_ts - hold parsed from reason), exit_time, entry_price (fill_price), exit_price, notional, recorded gross/fees/net, exit_reason, hold_minutes.
- Given OHLCV bars (fixture), for each cycle locate the sub-sequence of bars whose timestamps fall inside the [entry_time, exit_time] window.
- Replay the trade on that sub-sequence using the journal's entry_price/notional + harness fill (slippage) + fee model. The limited bar window causes exit at the end of the window (reproducing the actual hold period the live trade experienced).
- If no bars (or insufficient) in the window for a cycle → structured skip with reason (e.g. "no_ohlcv_in_window").
- Output both replayed nets and journal_recorded nets, direction match, breakdowns, per-strategy/per-symbol.

Default fee scenario is **taker/taker** (0.012/0.012) — conservative. Maker/maker is available for optimistic what-if.

## Relation to journal truth
- `journal_recorded_*` numbers come directly from the journal CSV (broker-backed fills/fees where recorded).
- Replayed numbers are **simulated** using the harness's deterministic OHLCV replay logic on the price path in the window.
- `replay_vs_journal_direction_match` helps validate that the simulation points the same way as reality (both negative, both positive, etc.).
- `journal_recorded_broker_backed` vs replayed/estimated is explicitly distinguished; replay is still an approximation (bar granularity, slippage model, no real partial fills/maker-taker flags from live).

## Taker/taker default and why it matters
Per prior review: fee drag was the primary driver of the observed loss. Using optimistic (maker) fees in the baseline would understate the hurdle any exit/policy change must clear. Taker/taker is the conservative gate for reproduction.

## This is still offline-only and cannot approve live trading
- No broker calls, no orders, no --live-read-only, no .env, no launchctl, no runtime mutation.
- Always emits `trade_permission="none"`, `risk_increase="not_approved"`, `scaling_allowed=false`.
- No changes to live config, caps (max_open=1, max_trades/day=3, notional 5/10), symbols, SOL exclusion, strategy thresholds, or LaunchAgent.
- Review branch only; push review; no merge.

## Limitations (current baseline)
- Real OHLCV coverage for the actual May 2026 journal dates may be incomplete or absent in the provided fixture. In that case the report will show high `cycles_skipped` with `no_ohlcv_in_window` — this is expected and useful signal.
- The replay uses the harness's current static TP/SL/hold logic (max_hold from the journal cycle's actual hold). It does not yet "re-execute" the exact live strategy code path.
- Bar granularity (5m in samples) + slippage model means replayed exit_price will be close but not identical to journal's recorded `exit_price`.
- Notional in some journal rows may be 0 or derived; the adapter falls back conservatively.

## Next steps after this baseline
- Expand real OHLCV ingestion (price path logs or external) for the actual trade windows so more cycles can be replayed.
- Or P2-025G: maker/post-only economics study using the same window replay (lower fee rates) once baseline reproduction is solid.
- Only after the harness directionally reproduces the known loss (and ideally the fee dominance) on real windows should "exit logic improvement" experiments be trusted as inputs to live proposals.

## Usage (offline)
```bash
python3 scripts/coinbase_journal_window_replay_report.py --json
python3 scripts/coinbase_journal_window_replay_report.py --json --max-cycles 10
python3 scripts/coinbase_journal_window_replay_report.py --json --journal tests/fixtures/journal_window_replay/sample_journal.json --ohlcv-fixture tests/fixtures/journal_window_replay/sample_ohlcv.json --fee-scenario maker/maker
```

## Safety / verification
- py_compile + pytest (this test file + prior offline backtest tests) + full suite.
- 2 smokes (default + --max-cycles).
- Safety grep must find zero live/order/launchctl/.env patterns in the new script, its test, and updated docs.
- No config/risk/sizing/symbol/strategy/LaunchAgent changes.
- Review branch only.

## Acceptance for moving forward
The harness (via this report) must show on available data:
- cycles_seen > 0
- either cycles_replayed > 0 with net_pnl_sum directionally negative (or fee drag visible), or clear structured skips when OHLCV coverage is missing.
- All safety invariants and output fields present.
- Full test suite green.
