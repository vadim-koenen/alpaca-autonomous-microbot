# REPLAY ECONOMICS FEE SCENARIO REPORT (P2-025L)

## What this report measures
- For the subset of journal EXIT cycles that have full OHLCV window coverage (48/49 as of P2-025K data), it replays the exact entry→exit price path using the deterministic harness (`coinbase_offline_backtest.py` journal-window replay).
- Separates **replay gross P/L** (path-dependent price move + slippage model on the actual bars in the window) from **fees under different assumptions**.
- Computes net under:
  - `journal_recorded_fees` (replay gross − the fees actually recorded in the journal for that cycle)
  - `taker/taker` (current default conservative 1.2%/1.2%)
  - `maker/maker` (0.4%/0.4% optimistic lower)
  - `zero_fee` (theoretical gross only, no drag)
  - `mixed_maker_taker` (maker entry / taker exit)
- Distribution stats per scenario: count, wins/losses/breakeven, win_rate, gross/fees/net sums, avg/median/best/worst net.
- Per-symbol, per-strategy, per-exit-reason breakdowns (where journal data supports).
- Timeout (max-hold) exit count and share.
- **Break-even fee rate**: the symmetric entry=exit rate at which the observed replay gross sums to exactly zero net (solved from aggregate gross and per-cycle notionals + exit notionals).
- **Notional sensitivity** (offline linear scaling only): what the taker/taker net sums would have been if every analyzed trade had used a fixed notional of $0.50 / $1 / $5 / $10 instead of its actual journal notional. Pure math; does **not** read or mutate live config, risk caps, or sizing.
- Direction match between replay net sign and journal-recorded net sign (under the taker baseline).
- Plain-English `verdict` + evidence blob.

## What it does NOT measure
- Live broker truth or actual fill quality beyond the journal's recorded gross/fees/net.
- Strategy signal logic (entries are taken verbatim from journal EXIT rows; no re-running of mean_reversion / probe / exploration rules).
- Intra-cycle management, position sizing policy, or risk (the replay uses the journal's actual per-cycle notional and hold time).
- Future performance or "fix" efficacy. This is a diagnostic on historical windows only.
- Authorization to scale, change notional, relax risk, add symbols, or deploy any strategy/exit change.

## Current coverage limitation (48/49)
- 1 cycle (ADA/USD in the current journal window) has no OHLCV bars in its [entry, exit] window in the local `data/offline_ohlcv/coinbase/` files → structured skip with `no_ohlcv_in_window`.
- All analysis and verdict are computed **only on the 48 covered cycles**.
- The skipped cycle's journal-recorded net is excluded from the "analyzed" aggregates (full seen net is more negative).
- ALGO/BTC/ETH/SOL have 100% window coverage in the current local data; the gap is ADA.

## Why this is offline-only
- Uses only `parse_journal_cycles`, `load_bars_from_fixture`, and `run_journal_window_replay` from the harness.
- No broker calls, no order placement/cancel/close/modify, no `--live-read-only`, never reads `.env` or secrets, never touches launchctl or runtime state.
- Always emits `trade_permission="none"`, `risk_increase="not_approved"`, `scaling_allowed=false`.
- The notional sensitivity math is performed after the fact on already-computed nets/grosses; it does not alter any live configuration file or constant.

## How to interpret fee scenarios
- **zero_fee net** ≈ replay gross: the raw edge the price path + harness exit logic would have delivered before any fees/spreads.
- **journal_recorded_fees net** (replay gross − journal fees): shows the P/L that would have occurred on the *simulated path* if the exact fees the live trades actually paid had been applied. Often less negative than live recorded because replay gross can differ from journal gross (different exit price due to bar granularity + slippage model).
- **taker/taker**: conservative baseline matching the harness default. Round-trip ~2.4%.
- **maker/maker**: what-if lower fees (e.g. post-only limits). Still does not prove a maker strategy would have achieved those fills.
- **mixed**: common realistic case (limit entry maker, market/taker exit).
- Large positive shift from zero_fee → any-fee scenario = strong evidence that **fee drag** (not direction or exit timing alone) is the dominant loss driver.
- Win rate under zero_fee vs under taker tells you how many trades were "fee-breakeven or better on path" vs turned negative purely by fees.

## Break-even fee threshold
- The rate (entry=exit) at which `sum(replay_gross) − sum(fees(r)) = 0`.
- If replay gross > 0 and notionals known, this is `gross_sum / sum(entry_n + exit_n)` per cycle.
- If gross ≤ 0 overall, or no positive edge on the paths, reports `null` + note "not calculable".
- In the P2-025L baseline on real 48: ~0.007394 (0.7394% per side). Any real fee structure above that turns the observed paths net-negative in aggregate under the current replay model.

## Notional sensitivity (offline math)
- Shows the *hypothetical* net under taker fees if the 48 trades had each used a uniform notional instead of their actual (varied) journal notionals (~0.5–6 range observed).
- Because both gross and fees scale linearly with notional (no fixed costs), `net_at_target = net_at_actual * (target / actual_n)`.
- $5 column ≈ the "as-if all were $5" version of the taker net sum (larger magnitude than actual because many actual notionals were <5).
- This is diagnostic only. It does **not** propose or authorize changing `final_trade_notional`, hard caps, or any live sizing.

## Current P2-025L headline results (real untracked data, 48/49 coverage)
(Exact numbers from `python3 scripts/coinbase_replay_economics_report.py --json` on the data present at commit time; see transcript for full JSON.)

- cycles_seen: 49
- cycles_analyzed: 48
- cycles_skipped: 1 (ADA no_ohlcv_in_window)
- coverage_rate: 0.979592
- journal_recorded_net_pnl_sum (full 49): -1.2282313482561078935
- journal_recorded_net for the 48 analyzed: -1.09034762
- replay_gross (on 48): +1.27830742
- direction_match (replay net sign vs journal recorded): 0.5
- timeout exits (max hold): 47 / 48 (share 0.979167)
- break_even_fee_rate: 0.007394
- verdict: **fee_drag_dominant**

Fee scenario nets (48 analyzed):
- zero_fee: +1.27830742 (win_rate 0.520833)
- maker/maker: +0.58673796
- journal_recorded_fees (replay gross − journal fees): +0.24898926
- mixed_maker_taker: -0.10994472
- taker/taker: -0.79640095

Notional sensitivity (taker baseline, offline scale):
- $0.50: -0.39984209
- $1: -0.79968418
- $5: -3.99842088
- $10: -7.99684176

## What evidence would justify later strategy / exit tuning
- Sustained high coverage (>>48/49 or the 1 gap closed with data).
- Replay gross still positive or near-zero under the current static exit policy on real paths.
- Break-even fee comfortably above realistic maker/taker rates.
- Direction match high (>>0.5) so that the harness is faithfully reproducing live outcome *signs*.
- Clear separation: zero_fee strongly positive while taker/maker still negative → fee study (post-only, lower tiers, etc.) is the next gated experiment.
- Only after the above would an "exit_logic_negative" or "directionally_negative" verdict on real data justify touching TP/SL/hold/max_trades logic, and even then only on review branch with full re-baseline.

## Invariants preserved by this report
- No live trading, no orders, no cancel/close/modify.
- No --live-read-only, no .env, no secrets, no auth headers.
- No launchctl, no runtime restart, no LaunchAgent mutation.
- No changes to config, risk caps, notional, max_open, max_trades_per_day, eligible symbols, SOL status, strategy thresholds, or any live behavior.
- `data/offline_ohlcv/` kept untracked.
- Review branch only; push review; no merge to main.
- All outputs include the standard safety flags.

This report exists to make the fee-drag vs. path/ exit vs. sizing drivers visible on the actual 48 covered windows before any further work. It does not authorize any live action.
