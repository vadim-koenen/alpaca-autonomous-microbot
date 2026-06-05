# ACTIVE HANDOFF — Alpaca/Coinbase Autonomous Trading Bot

## P2-025Y — OHLCV Coverage Expansion And Synthetic Validation Rerun (review/p2-025y-increase-ohlcv-coverage-rerun-validation)
P2-025X is merged on main at 5a55399. Review branch only. No merge, no restart, no launchctl, no live trading, no `--live-read-only`, no broker/trading endpoints, no `.env`/secrets reads, no orders/cancels/closes/modifications, no paper/live probes, no live filter implementation, no maker/post-only implementation, no exit tuning, no live config/risk/notional/max-open/max-trades/symbol/strategy/LaunchAgent changes.

Added `docs/OHLCV_COVERAGE_EXPANSION_RERUN.md`. No code or config changed. `data/offline_ohlcv/` remains untracked local working data.

Expanded offline local OHLCV coverage with unauthenticated public Coinbase candles only:
- `ADA/USD`, `ALGO/USD`, `BTC/USD`, `ETH/USD`, `SOL/USD`
- window: `2026-05-01` to `2026-05-25`
- generated untracked CSV files under `data/offline_ohlcv/coinbase/`
- no auth, no API keys, no `.env`, no broker/trading clients, no Advanced Trade endpoints

Corrected validation found no malformed rows and no duplicate timestamps in the new files. Gap caveat: `ALGO/USD` has 539 detected gaps in the early public-data window; ADA/BTC/ETH/SOL each have 2 detected gaps.

Before expansion:
- bars_scanned: 9782
- synthetic_cycles_count: 32
- baseline_gross: -0.05962834
- baseline_win_rate: 0.4375
- validated_filters: []

After expansion:
- bars_scanned: 43333
- synthetic_cycles_count: 91
- baseline_gross: 0.16536982
- baseline_win_rate: 0.505495
- sample_size_status: preferred
- validated_filters: `baseline_all_synthetic_cycles`, `exclude_stop_loss`, `exclude_strategy_mean_reversion`, `exclude_symbol_ETH/USD`, `exclude_symbol_ADA/USD`, `exclude_symbol_BTC/USD`, `exclude_symbol_SOL/USD`, `dynamic_exclude_strategy_mean_reversion`, `dynamic_exclude_exit_reason_stop_loss`
- strongest diagnostic: `exclude_stop_loss`, N=66, gross=0.73010002, win_rate=0.696970, gross_delta_vs_baseline=0.56473020
- provisional-positive exploratory scenario: `exclude_ALGO_and_stop_loss`, N=31, gross=0.08846366, win_rate=0.580645
- rejected: `exclude_symbol_ALGO/USD`, `dynamic_exclude_strategy_momentum_breakout`, `dynamic_exclude_exit_reason_take_profit`, `dynamic_exclude_exit_reason_timeout`

Interpretation: the expanded offline sample makes stop-loss exclusion the highest-ROI diagnostic candidate, but it is still gross-only synthetic evidence. This does not authorize live implementation, exit tuning, paper/live probes, restart, config changes, or scaling. SOL remains excluded from live bot inventory/trading because it is externally staked.

Preserved truth: implementation_authorized=false, paper_probe_authorized=false, live_probe_authorized=false, scaling_authorized=false, trade_permission=none, scaling_allowed=false, risk_increase=not_approved. Leakage guards remain `no_future_bars_for_signal=true`, `exit_after_entry_only=true`, `no_journal_exit_leakage=true`.

Next recommended action:
- P2-025Z should be an offline-only stop-loss diagnostics/explanation report that determines whether stop-loss losers are avoidable entry-quality failures, exit-policy artifacts, or unavoidable adverse moves before any implementation proposal.

## P2-025X — Expanded Offline Filter Validation Using Synthetic Cycles (review/p2-025x-expanded-filter-validation-synthetic-cycles)
P2-025W is merged on main at 005a1a1. Review branch only. No merge, no restart, no launchctl, no live trading, no `--live-read-only`, no broker/trading endpoints, no `.env`/secrets reads, no orders/cancels/closes/modifications, no paper/live probes, no live filter implementation, no maker/post-only implementation, no exit tuning, no live config/risk/notional/max-open/max-trades/symbol/strategy/LaunchAgent changes.

Added `scripts/coinbase_synthetic_cycle_filter_validation.py`, `tests/test_coinbase_synthetic_cycle_filter_validation.py`, and `docs/SYNTHETIC_CYCLE_FILTER_VALIDATION.md`.

The report consumes P2-025W synthetic cycles through the offline generator and validates candidate filters against strict sample-size, gross, median, win-rate, concentration, and leakage gates.

Source generator summary:
- symbols_scanned: `ADA/USD`, `ALGO/USD`, `BTC/USD`, `ETH/USD`, `SOL/USD`
- bars_scanned: 9782
- synthetic_cycles_count: 32
- baseline_gross: -0.05962834
- baseline_win_rate: 0.4375
- leakage guards: `no_future_bars_for_signal=true`, `exit_after_entry_only=true`, `no_journal_exit_leakage=true`

Filter result summary:
- validated_filters: []
- provisional_positive_filters: []
- rejected_filters: all evaluated scenarios
- strongest rejected filter: `exclude_stop_loss` / `dynamic_exclude_exit_reason_stop_loss` improved gross to +0.22750788 with 0.7000 win rate but left only 20 cycles, below the 30-cycle minimum.
- `exclude_symbol_ALGO/USD` improved gross to +0.01172133 but left only 9 cycles and triggered concentration warning.
- `exclude_symbol_ETH/USD` improved gross to -0.04587091 but remained negative and left only 28 cycles.
- no scenario reached fully validated status.

Preserved truth: implementation_authorized=false, paper_probe_authorized=false, live_probe_authorized=false, scaling_authorized=false, trade_permission=none, scaling_allowed=false, risk_increase=not_approved. No filters were implemented. No strategy thresholds, live strategy, config, risk, runtime, price-path logger, or LaunchAgent state changed. `data/offline_ohlcv/` remains untracked.

Next recommended action:
- Increase offline OHLCV coverage and rerun synthetic generation plus P2-025X validation before considering any implementation proposal. Do not implement filters yet, tune exits, run paper/live probes, restart, or scale.

## P2-025W — Historical Signal Generator, Offline Only (review/p2-025w-historical-signal-generator)
P2-025V is merged on main at 2dea51e. Review branch only. No merge, no restart, no launchctl, no live trading, no `--live-read-only`, no broker/trading endpoints, no `.env`/secrets reads, no orders/cancels/closes/modifications, no paper/live probes, no live filter implementation, no maker/post-only implementation, no exit tuning, no live config/risk/notional/max-open/max-trades/symbol/strategy/LaunchAgent changes.

Added `scripts/coinbase_historical_signal_generator.py`, `tests/test_coinbase_historical_signal_generator.py`, and `docs/HISTORICAL_SIGNAL_GENERATOR.md`.

The generator reuses the P2-025V offline strategy runner adapter against local OHLCV bars and emits synthetic cycle records for expanded offline filter validation. It writes no cycle artifact unless `--output` is explicitly provided.

Headline smoke result:
- symbols_scanned: `ADA/USD`, `ALGO/USD`, `BTC/USD`, `ETH/USD`, `SOL/USD`
- bars_scanned: 9782
- signal_candidates_count: 32
- synthetic_cycles_count: 32
- gross_total: -0.05962834
- win_rate: 0.4375
- leakage guards: `no_future_bars_for_signal=true`, `exit_after_entry_only=true`, `no_journal_exit_leakage=true`
- readiness: `historical_signal_generator_ready=true`, `synthetic_cycle_journal_ready=true`, `expanded_filter_validation_ready=true`

Adapter path used: `OfflineMarketDataAdapter`, `_model_quote_from_bar`, `classify_regime`, `CryptoStrategy._momentum_breakout`, `CryptoStrategy._mean_reversion`, `CryptoStrategy._ema_crossover`, and `add_indicators`.

Preserved truth: implementation_authorized=false, paper_probe_authorized=false, live_probe_authorized=false, scaling_authorized=false, trade_permission=none, scaling_allowed=false, risk_increase=not_approved. Synthetic cycles are not realized P/L and are not predictive approval until separately validated. No live config/risk/runtime change. `data/offline_ohlcv/` remains untracked.

Next recommended action:
- Run expanded offline filter validation on generated synthetic cycles.

## P2-025V — Offline Strategy Runner Adapter, Offline Only (review/p2-025v-offline-strategy-runner-adapter)
P2-025U is merged on main at 40cb7a7. Review branch only. No merge, no restart, no launchctl, no live trading, no `--live-read-only`, no broker/trading endpoints, no `.env`/secrets reads, no orders/cancels/closes/modifications, no paper/live probes, no filter implementation, no maker/post-only implementation, no strategy changes.

Added `scripts/coinbase_offline_strategy_runner_adapter.py`, `tests/test_coinbase_offline_strategy_runner_adapter.py`, and `docs/OFFLINE_STRATEGY_RUNNER_ADAPTER.md`.

The adapter enables existing strategy logic to be exercised against historical OHLCV data offline.

Headline findings:
- strategy_logic_importable: true
- offline_strategy_runner_ready: true
- historical_signal_generation_ready: true
- Reusable Functions: `classify_regime`, `_momentum_breakout`, `_mean_reversion`, `_ema_crossover`, `add_indicators`.
- Blocked/Mocked: `_coinbase_exploration` is currently state-heavy and bypassed.

Next recommended action:
- Build the **Historical Signal Generator** that iterates over historical bars and applies this adapter to produce a synthetic trade journal for expanded backtesting.

Preserved truth: implementation_authorized=false, paper_probe_authorized=false, live_probe_authorized=false, scaling_authorized=false, trade_permission=none, scaling_allowed=false, risk_increase=not_approved. No live config/risk/runtime change. `data/offline_ohlcv/` remains untracked.

## P2-025U — Larger-History Offline Signal/Cycle Generation Scaffold (review/p2-025u-larger-history-signal-cycle-generation-scaffold)
P2-025T is merged on main at 0af96e3. Review branch only. No merge, no restart, no launchctl, no live trading, no `--live-read-only`, no broker/trading endpoints, no `.env`/secrets reads, no orders/cancels/closes/modifications, no paper/live probes, no filter implementation, no maker/post-only implementation, no exit tuning, no config/risk/notional/max-open/max-trades/symbol/strategy/LaunchAgent changes.

Added `scripts/coinbase_offline_signal_cycle_generation_scaffold.py`, `tests/test_coinbase_offline_signal_cycle_generation_scaffold.py`, and `docs/OFFLINE_SIGNAL_CYCLE_GENERATION_SCAFFOLD.md`.

The scaffold evaluates repository readiness for larger-history backtesting.

Headline findings:
- signal_generation_ready: false
- cycle_generation_ready: false
- historical_backtest_ready: false
- Gaps: Bid/ask/spread modeling, position/cooldown state simulation, and an offline-safe adapter for `strategy_crypto.py` logic are currently missing.
- Note: Older OHLCV data is insufficient for backtesting without the ability to reconstruct signals offline.

Next recommended action:
- Build an **Offline Strategy Runner** adapter that can process historical bars using existing strategy logic without requiring live broker components.

Preserved truth: implementation_authorized=false, paper_probe_authorized=false, live_probe_authorized=false, scaling_authorized=false, trade_permission=none, scaling_allowed=false, risk_increase=not_approved. No live config/risk/runtime change. `data/offline_ohlcv/` remains untracked.

## P2-025T — Offline Candidate Filter Backtest Validation (review/p2-025t-offline-candidate-filter-backtest-validation)
P2-025S is merged on main at 35100b2. Review branch only. No merge, no restart, no launchctl, no live trading, no `--live-read-only`, no broker/trading endpoints, no `.env`/secrets reads, no orders/cancels/closes/modifications, no paper/live probes, no filter implementation, no maker/post-only implementation, no exit tuning, no config/risk/notional/max-open/max-trades/symbol/strategy/LaunchAgent changes.

Added `scripts/coinbase_candidate_filter_backtest_validation.py`, `tests/test_coinbase_candidate_filter_backtest_validation.py`, and `docs/CANDIDATE_FILTER_BACKTEST_VALIDATION.md`.

The report evaluates P2-025S candidate filters against the historical window (currently 50 cycles). It applies strict validation gates (sample size, positive gross, win rate, concentration).

Headline findings:
- validated_filters: []
- any_filter_validated: false
- Result: None of the candidate filters (ETH exclusion, stop-loss exclusion, etc.) resulted in a positive predictive gross edge on the current 50-cycle window. The strategy remains gross-negative before fees.
- Status: All results are labeled "provisional" or "weak" due to small sample size (n=50) and limited window (10 days).

Next data needed:
- OHLCV data for period BEFORE 2026-05-25 to increase sample size and test robustness.
- Safe command provided in report using public fetcher (no auth/secrets).

Preserved truth: implementation_authorized=false, paper_probe_authorized=false, live_probe_authorized=false, scaling_authorized=false, trade_permission=none, scaling_allowed=false, risk_increase=not_approved. No live config/risk/runtime change. `data/offline_ohlcv/` remains untracked.

## P2-025S — Gross-Edge Failure Decomposition, Offline Only (review/p2-025s-gross-edge-failure-decomposition)
P2-025R is merged on main at 8cc9214. Review branch only. No merge, no restart, no launchctl, no live trading, no `--live-read-only`, no broker/trading endpoints, no `.env`/secrets reads, no orders/cancels/closes/modifications, no paper/live probes, no maker/post-only implementation, no exit tuning, no config/risk/notional/max-open/max-trades/symbol/strategy/LaunchAgent changes.

Added `scripts/coinbase_gross_edge_decomposition_report.py`, `tests/test_coinbase_gross_edge_decomposition_report.py`, and `docs/GROSS_EDGE_DECOMPOSITION.md`.

The report decomposes the negative predictive gross edge by symbol, strategy, exit reason, hold duration, and spread. It isolates why the current strategy loses before any fee considerations.

Headline findings:
- predictive_gross_total=-0.26885977
- gross_edge_positive=false
- win_rate=0.40
- dominant_loss_driver=exit_reason_timeout (49/50 cycles, -0.16357491 gross loss)
- worst_symbol=ETH/USD (-0.16344878 gross loss)
- worst_strategy=coinbase_exploration (-0.17444174 gross loss)
- concentration: worst 10 cycles account for -0.30111453 in loss.

Candidate filters for future backtest:
- exclude_stop_loss (Delta: +0.10528486)
- exclude_symbol_ETH/USD (Delta: +0.16344878)
- exclude_strategy_mean_reversion (Delta: +0.01838984)
- exclude_symbol_ADA/USD (Delta: +0.06435415)

Preserved truth: implementation_authorized=false, paper_probe_authorized=false, live_probe_authorized=false, scaling_authorized=false, trade_permission=none, scaling_allowed=false, risk_increase=not_approved. No live config/risk/runtime change. `data/offline_ohlcv/` remains untracked and unrelated untracked docs/scripts remain untouched. Next recommended action is offline backtest validation of these candidate filters on a larger dataset.

## P2-025R — Maker/Post-Only Feasibility Model, Offline Only (review/p2-025r-maker-post-only-feasibility-model)
P2-025Q is merged on main at 3a35f1b. Review branch only. No merge, no restart, no launchctl, no live trading, no `--live-read-only`, no broker/trading endpoints, no `.env`/secrets reads, no orders/cancels/closes/modifications, no paper/live probes, no maker/post-only implementation, no exit tuning, no config/risk/notional/max-open/max-trades/symbol/strategy/LaunchAgent changes.

Added `scripts/coinbase_maker_post_only_feasibility_report.py`, `tests/test_coinbase_maker_post_only_feasibility_report.py`, and `docs/MAKER_POST_ONLY_FEASIBILITY.md`.

The report uses P2-025Q's predictive live-exit-policy replay as the basis and compares journal-recorded fees, taker/taker, maker/maker, maker-entry/taker-exit, taker-entry/maker-exit, and zero-fee theoretical economics. It also models conservative non-fill and adverse-selection haircuts, per-symbol/per-strategy/per-exit-reason results, and notional sensitivity at $0.50, $1, $5, and $10. It does not write by default and does not implement maker/post-only execution.

Baseline parity preserved:
- cycles_seen=50, cycles_analyzed=50, cycles_skipped=0, coverage_rate=1.0
- predictive_replay_trustworthy=true, failed_predictive_gates=[]
- signed_gross_residual=-0.04524015, timeout_residual=-0.04006767
- forward_looking_fields_used=false, aligned_mode_used_for_prediction=false

Current maker feasibility headline:
- journal_recorded_on_analyzed_cycles.net_pnl_sum=-1.37856949
- predictive_gross_pnl_sum=-0.26885977
- taker/taker.net_pnl_sum=-2.57821663
- maker/maker.net_pnl_sum=-1.03864539
- maker_entry_taker_exit.net_pnl_sum=-1.80735557
- zero_fee_theoretical.net_pnl_sum=-0.26885977
- 30% adverse-selection + 30% non-fill maker/maker.net_pnl_sum=-1.07039283
- 50% adverse-selection + 50% non-fill maker/maker.net_pnl_sum=-1.08942061
- maker/maker.win_rate=0.02
- fee_break_even_threshold=null
- fee_fix_verdict=fees_alone_cannot_fix_negative_predictive_gross
- maker_feasible_offline=false

Failed feasibility gates: maker/maker net is not positive, maker/maker net after 30% non-fill/adverse-selection haircut is not positive, and maker/maker net win rate is below 0.45. The key conclusion is that fees alone cannot fix this because predictive gross is already negative before fees.

Preserved truth: implementation_authorized=false, paper_probe_authorized=false, live_probe_authorized=false, scaling_authorized=false, trade_permission=none, scaling_allowed=false, risk_increase=not_approved. `data/offline_ohlcv/` remains untracked and unrelated untracked docs/scripts remain untouched. Next recommended action is offline investigation of why predictive gross is negative before fees, without tuning exits, changing strategy thresholds, probing, restarting, or scaling.


# ACTIVE HANDOFF — Alpaca/Coinbase Autonomous Trading Bot

## P2-025Q — Close ADA/ETH OHLCV Gaps And Rerun Predictive Parity (review/p2-025q-close-ohlcv-gaps-and-rerun-parity)
P2-025P is merged on main at dbd95cf. Review branch only. No merge, no restart, no launchctl, no live actions, no `--live-read-only`, no broker/trading endpoints, no `.env`/secrets reads, no orders/cancels/closes/modifications, no paper/live probes, no maker/post-only implementation, no exit tuning, no config/risk/notional/max-open/max-trades/symbol/strategy/LaunchAgent changes.

Used explicit opt-in public unauthenticated Coinbase Exchange market-data fetch only (`scripts/coinbase_public_ohlcv_fetch.py --fetch --write`) for the two missing 5m OHLCV windows:
- ADA/USD: 2026-06-03T21:30:00Z to 2026-06-03T23:15:00Z, 22 bars, gap_count=0, untracked file `data/offline_ohlcv/coinbase/ADA-USD_5m_2026-06-03_2026-06-03.csv`
- ETH/USD: 2026-06-04T00:15:00Z to 2026-06-04T02:00:00Z, 22 bars, gap_count=0, untracked file `data/offline_ohlcv/coinbase/ETH-USD_5m_2026-06-04_2026-06-04.csv`

Coverage after gap close:
- `coinbase_journal_window_replay_report.py --json`: cycles_seen=50, cycles_with_ohlcv_window=50, cycles_without_ohlcv_window=0, coverage_rate=1.0
- `coinbase_live_exit_policy_parity_report.py --json`: cycles_seen=50, cycles_analyzed=50, cycles_skipped=0

Parity after full coverage:
- original_simulated_tp_sl_high_low: direction_match=0.52, gross_residual=1.33327563, exit_reason_match_rate=0.04, timeout_residual=1.26723778
- journal_exit_aligned_control: direction_match=1.0, gross_residual=0E-8, control_only=true
- predictive_live_exit_policy: direction_match=1.0, gross_residual=-0.04524015, timeout_residual=-0.04006767, median_abs_residual=0.00081072, p90_abs_residual=0.00647429, exit_reason_match_rate=0.96, timeout_exit_match_rate=1.0, exit_timestamp_delta_median=3.597180, exit_timestamp_delta_p90=4.663262, predictive_replay_trustworthy=true, failed_gates=[]
- forward_looking_fields_used=false, aligned_mode_used_for_prediction=false, original_replay_behavior_modified=false
- top mismatch cycles: ETH/USD mean_reversion stop-loss journal vs predictive max-hold; ADA/USD coinbase_exploration stop-loss journal vs predictive max-hold. Both remain within gates.

Preserved truth: journal-exit-aligned replay remains a reconciliation control, not predictive backtest evidence. P2-025Q only closes offline OHLCV coverage and reruns diagnostics. `trade_permission=none`, `scaling_allowed=false`, `risk_increase=not_approved`. Data files remain untracked and unrelated untracked docs/scripts remain untouched. Next possible review may scope maker/post-only feasibility without live implementation, but do not implement maker/post-only, tune exits, run probes, restart, or scale in this patch.

## P2-025P — Predictive Live Exit-Policy Parity Report (review/p2-025p-predictive-live-exit-policy-parity)
P2-025O is merged on main at 1e372da. Review branch commit is final branch HEAD in the verification packet. Review branch only. No merge, no restart, no launchctl, no live actions, no `--live-read-only`, no broker calls, no `.env`/secrets reads, no orders/cancels/closes/modifications, no paper/live probes, no maker/post-only implementation, no exit tuning, no config/risk/notional/max-open/max-trades/symbol/strategy/LaunchAgent changes.

Added an offline report that compares three modes:
- `original_simulated_tp_sl_high_low`: existing replay harness, unchanged.
- `journal_exit_aligned_control`: P2-025O reconciliation control only; uses journal exits and is not predictive evidence.
- `predictive_live_exit_policy`: offline predictive approximation using journal entry facts, candle-close scan decisions, TP/SL thresholds, and max-hold timeout. It does not use journal exit price or journal exit timestamp for prediction.

Predictive trust gates are intentionally strict: direction_match >= 0.90, exit_reason_match_rate >= 0.90, timeout_exit_match_rate >= 0.95, abs signed gross residual <= 0.10, timeout residual <= 0.05, median exit timestamp delta <= one scan/bar interval, forward_looking_fields_used=false, aligned_mode_used_for_prediction=false. If any gate fails, predictive_replay_trustworthy=false and the next action remains parity/gap closure, not maker/post-only or exit tuning.

Headline current offline result on covered cycles:
- cycles_seen=50, cycles_analyzed=48, cycles_skipped=2 (ADA/USD full gap + ETH/USD partial gap remain)
- original_simulated_tp_sl_high_low: direction_match=0.5, gross_residual=1.33933688, exit_reason_match_rate=0.0
- journal_exit_aligned_control: direction_match=1.0, gross_residual=0E-8, control_only=true
- predictive_live_exit_policy: direction_match=1.0, gross_residual=-0.03819130, timeout_residual=-0.04006767, median_abs_residual=0.00075784, p90_abs_residual=0.00325986, exit_reason_match_rate=0.979167, timeout_exit_match_rate=1.0, exit_timestamp_delta_median=3.622217, exit_timestamp_delta_p90=4.663262
- predictive_replay_trustworthy=true on covered 48/50 cycles, failed gates=[]
- forward_looking_fields_used=false, aligned_mode_used_for_prediction=false, original_replay_behavior_modified=false
- top mismatch is one ETH/USD stop-loss journal cycle modeled as max-hold by predictive close-scan approximation; residual small enough for gates.

Preserved truth: journal-exit-aligned replay is a reconciliation control, not predictive backtest evidence. Because ADA/ETH gaps remain, next action is close offline OHLCV gaps and rerun 50/50 before scoping maker/post-only feasibility. `trade_permission=none`, `scaling_allowed=false`, `risk_increase=not_approved`. Unrelated untracked offline data/docs/scripts remain untouched.

## P2-025O — Live Exit-Policy Fidelity / Journal-Exit-Aligned Replay Mode (review/p2-025o-live-exit-policy-fidelity)
P2-025N merged at 8316f4b (main confirmed at start of work). Review branch only. No merge, no restart, no live actions, no config/risk/sizing/symbol/strategy/LaunchAgent changes, no .env, no launchctl, no orders, no maker logic, no exit changes, no probes, no paper-trading. data/offline_ohlcv/ + 4 unrelated untracked untouched.

P2-025N finding (exit-driven): replay divergence (dir_match 0.50, signed gross res +1.33933688) is almost entirely from exit-basis (timeout_exit_basis_issue). Entry res ~0 by design. Replay simulates TP/SL (bar h/l + adverse) inside 47/48 journal "max hold"/timeout windows. Journal records actual timeout fill prices (43/48 within nearest candle h/l). This report adds a diagnostic journal-exit-aligned mode (no mutation of simulator) to test reconciliation when replay exit follows live journal exit ts/reason/price.

Added:
- `scripts/coinbase_live_exit_policy_fidelity.py`: new offline report. Reuses parse_journal_cycles, run_journal_window_replay (zero-fee for the *simulated* mode only), _load_bars_for_journal + _compute_coverage_and_covered from economics, load_bars_from_fixture, _find_nearest_bar/_price_within_candle/_is_timeout_exit from price-basis, _compute_replay_exit_price from fidelity (no dup parsing, *no change* to existing replay or live exit logic).
- Dual-mode per analyzed cycle (only cycles with OHLCV coverage; skipped accounting preserved): symbol/strategy, journal_exit_reason, simulated_replay_exit_reason (often take_profit even for journal timeout), journal_entry/exit_price, simulated_replay_exit_price (derived), journal-exit-aligned_replay_exit_price, journal/sim/aligned gross, simulated/aligned gross_residual, simulated/aligned direction_match, aligned_used_journal_exit_price (bool), aligned_fallback_note (None or "candle_close_fallback"), journal_exit_within_candle_hl, is_timeout, notional, residual_improved ("improved"/"worsened"/"unchanged").
- Aggregates: cycles_seen/analyzed/skipped (50/48/2), simulated/aligned direction_match + delta, simulated/aligned signed_gross_residual + residual_reduction_abs/pct, med/p90 abs before/after, sim/ali replay_trustworthy + failed_gates, timeout_only (count 47, before/after res + dir_match), by_symbol before/after (dir + res), by_exit_reason before/after, improvement flags, conclusion exit_policy_alignment_fixes_residual + remaining_blockers list.
- Skipped details for ADA (full) + ETH (partial) with exact ts + suggested offline gap-close cmds (unchanged from 025N).
- --json / default human / --top-n N / --output (no default write) / --journal / --ohlcv-fixture / --max-cycles. Always trade_permission=none / risk_increase=not_approved / scaling_allowed=false.
- `tests/test_coinbase_live_exit_policy_fidelity.py`: 12 tests covering the 10 required (aligned uses journal exit for timeout → res=0, residual improves, candle fallback when missing, dir match before/after + delta, trust gate logic + med_pct, skipped accounting, JSON schema + safety, no-net/auth/live, no mutation of run_journal_window_replay, deterministic fixture-based + in-memory).
- `docs/LIVE_EXIT_POLICY_FIDELITY.md`: why (025N exit diagnosis), recap of exit-driven residual, def of simulated vs journal-exit-aligned modes, when exact vs fallback, before/after gates + results, whether resolves, remaining blockers to maker, invariants, baselines.
- Updated ACTIVE_HANDOFF (this section) with branch + exact 025O headlines + "no live/risk/runtime impact".

Exact headline results on real untracked data (50/48/2, matches 025N coverage):
- cycles_seen: 50, cycles_analyzed: 48, cycles_skipped: 2 (ADA/USD full + ETH/USD partial), coverage_rate: 0.96
- simulated_direction_match: 0.5, aligned_direction_match: 1.0, direction_match_delta: 0.5
- simulated_signed_gross_residual: +1.33933688, aligned_signed_gross_residual: 0E-8
- residual_reduction_abs: 1.33933688, residual_reduction_pct: 1.0
- simulated_median_abs_gross_residual: 0.02601312, aligned: 0E-8
- simulated_p90_abs_gross_residual: 0.12189486, aligned: 0E-8
- simulated_replay_trustworthy: false, aligned_replay_trustworthy: true
- simulated failed gates: ['direction_match < 0.85 (got 0.5)', 'abs(signed total net residual using journal fees) > 0.10 (got 1.33933688)']
- aligned failed gates: []
- timeout-only (47/48=0.979167): sim_signed_gross_res +1.26723778 / dir_match 0.510638 ; aligned 0E-8 / 1.0
- by-symbol (examples): ALGO/USD sim_dir 0.0→1.0 res +0.40356051→0 ; ETH/USD 0.071429→1.0 res +1.10718981→0 ; BTC/USD 1.0→1.0 res -0.33740232→0 ; SOL 0.2→1.0
- by-exit-reason: all "max hold..." categories show sim positive res collapsing to 0 under alignment; non-timeout (stop-loss) already near-zero.
- exit_policy_alignment_fixes_residual: true
- remaining_blockers: ["Gaps (ADA/ETH) still present for full coverage.", "Even with alignment, the *simulated* harness (current TP/SL) remains untrustworthy (dir 0.5). Alignment proves the *cause* was exit policy mismatch, but does not change harness behavior.", "Live policy is timeout-heavy; fee_drag on long holds is still the economic reality.", "Next gated step requires gap close + re-run of simulated fidelity/price-basis before any maker consideration."]
- P2-025N price-basis baseline (recap): dir_match 0.5, signed gross res +1.33933688, entry contrib ~0, exit contrib +1.33933688, dominant timeout_exit_basis_issue, journal within hl entry 0.916667/exit 0.895833, replay entry "journal exact" 48/48, replay exit 25 high-tp + 23 low-sl, replay_trustworthy false.
- All validation: py_compile (6 incl. backtest), pytest targeted (journal 13 + econ 11 + fid 10 + price 11 + live 12), full tests 1072 passed.
- Safety: clean on impl (no actionable matches in 5 scripts + 3 docs + tests; ~400 hits are all explanatory "no .env / no launchctl" strings in docs/handoff + "no .env" docstrings + forbidden-guard asserts in tests. Zero executable net/auth/broker/launchctl/order code in the new script or modified paths).
- No live trading, no restart, no launchctl, no orders, no .env/secrets, no config/risk/sizing/symbol/strategy/LaunchAgent/maker/exit/probe/paper changes, no network.
- data/offline_ohlcv/ + 4 unrelated (PROFIT_TURNAROUND_PLAN.md, SENIOR_CONSULTANT_REVIEW_2026-06-02.md, SPOT_CHECK_PROTOCOL.md, scripts/audit_snapshot.sh) untouched (git status shows only ?? for them + data/).
- Review push only. Do not merge.

Current state (post-025O on review): journal-exit-aligned diagnostic complete. Alignment *does* reconcile residual (to 0) and direction (to 1.0) and makes "aligned" mode pass gates (trustworthy true). This confirms P2-025N: the problem was live exit policy (timeout fills) vs replay's simulated TP/SL inside those windows. Simulated mode (current harness) still fails gates (as expected; no change to it). 2 gaps remain (ADA/ETH details unchanged). No path to maker/post-only until gaps closed + simulated fidelity re-run passes on 50/50. No live/risk/runtime impact whatsoever.

Next likely (after 025O):
- Close ADA/ETH gaps via suggested offline/manual public fetch + coinbase_ohlcv_import_validate.py --write (no network in commands here; see skipped details in --json output of price-basis or this report).
- Re-run replay_price_basis + this live_exit_policy_fidelity on full 50/50 coverage. Only if the *simulated* mode then shows replay_trustworthy=true (dir>=0.85, abs net res<=0.10, med pct<=0.10) would a gated maker/post-only feasibility (future P2) be considered on a *fresh* review branch.
- Any live/probe/sizing/strategy still requires full evidence chain + explicit approval. Do not merge.

All invariants preserved: pure offline, no broker/order/env/launchctl/restart/live/config/maker/exit/probe mutation. Untracked data + 4 unrelated untouched.

---

## P2-025N — Replay Price-Basis / Fill-Basis Reconciliation (review/p2-025n-replay-price-fill-basis-reconciliation)
P2-025M merged at 3c7aa96. Review branch only. No merge, no restart, no live actions, no config/risk/sizing/symbol/strategy/LaunchAgent changes, no .env, no launchctl, no orders, no maker logic, no exit changes, no probes. data/offline_ohlcv/ + 4 unrelated untracked untouched.

Current blocker (post-025M): replay_trustworthy=false. direction_match=0.50 (24 mismatches), signed gross residual +1.33933688 (replay_gross +1.278 vs journal_analyzed_gross -0.061), abs net res using journal fees +1.339 > $0.10. P2-025L economics (fee_drag_dominant etc.) not actionable until fidelity gates pass. Price-basis needed to localize whether residual is entry-driven, exit-driven (esp. timeout close-vs-fill), or unknown.

Added:
- `scripts/coinbase_replay_price_basis_reconciliation.py`: new offline report. Reuses parse_journal_cycles, run_journal_window_replay (zero-fee), _load_bars_for_journal + _compute_coverage_and_covered from economics, load_bars_from_fixture, and small _compute_replay_exit_price / _infer... from fidelity (no dup parsing, no exit logic mods).
- Per analyzed cycle: cycle_index, symbol/strat/exit_reason, entry/exit ts + journal fill ts fields, journal vs replay entry/exit prices, nearest OHLCV candle ts for entry+exit + full ohlcv (o/h/l/c/v), entry/exit/gross residuals, residual_driver (entry_price_bias / exit_price_bias / both / missing_journal_price / missing_ohlcv / timestamp_alignment / candle_close_vs_fill / timeout_exit_basis_issue / unknown), journal_*_within_candle_hl bools, replay_entry_basis ("journal exact..."), replay_exit_basis (inferred close/hl from reason), is_timeout, is_large_residual, direction_match, notional.
- Mismatch cycles first in output.
- Aggregates: cycles_seen/analyzed/skipped, dir_match, mismatch_count, signed gross residual, attributed_to_entry_price (~0), attributed_to_exit_price (==gross), unattributed, residual_appears_mostly, by-symbol (with entry/exit contribs), by-exit-reason (with contribs), timeout-specific (47/48, contribs, dir), top-N worst residual cycles, top-N direction mismatches, driver counts + dominant, candle_containment rates (entry/exit within hl ~0.92/0.90), replay_basis_summary counts, large_flags count.
- Skipped details for ADA (full) + ETH (partial) with exact ts + suggested offline gap-close commands (import_validate --write after manual place; no network executed).
- --json / default human / --top-n N / --output (no default write) / --journal / --ohlcv-fixture / --max-cycles.
- Always trade_permission=none / risk_increase=not_approved / scaling_allowed=false + safety notes.
- `tests/test_coinbase_replay_price_basis_reconciliation.py`: 11 tests (entry res math==0 by design, exit/gross res attribution, direction mismatch class, candle hl containment, timeout basis class, missing journal price handling, skipped accounting, JSON schema + safety flags, no-forbidden, deterministic in-memory fixture cases).
- `docs/REPLAY_PRICE_BASIS_RECONCILIATION.md`: why (025M gates + consultant gap), definitions of entry/exit/gross res + attribution, candle containment interp, how timeout amplifies close-vs-fill, current dominant (exit-driven timeout), what must be true before maker, invariants, gap details + offline cmds, baseline cmds.
- Updated ACTIVE_HANDOFF (this section + 025M "next" note) with branch/commit + exact price-basis headlines.

Exact headline results on real untracked data (50/48/2, matches 025M):
- cycles_seen: 50, cycles_analyzed: 48, cycles_skipped: 2 (ADA full + ETH partial), coverage_rate: 0.96
- direction_match: 0.50, mismatch_count: 24
- signed_gross_residual: +1.33933688
- attributed_to_entry_price: ~0E-8
- attributed_to_exit_price: +1.33933688
- unattributed_or_unknown: ~0
- residual_appears_mostly: exit-driven (primarily timeout close-vs-fill vs journal exit fills)
- timeout count/share: 47 / 0.979167 , timeout gross_res ~1.267
- by-symbol examples: ETH largest positive exit contrib (+1.107), BTC negative (-0.337), ALGO dir_match 0.0
- dominant_driver: timeout_exit_basis_issue (close-vs-fill on max-hold exits)
- large_residual_flags: 48
- candle_containment: journal_entry_within_hl rate 0.916667, exit 0.895833 (most fills inside nearest candle hl)
- replay_entry_basis: always journal exact (48/48)
- replay_exit_basis_counts: bar high+slip (TP) 25, bar low+slip (SL) 23
- replay_trustworthy: false (per 025M gates; remains false)
- skipped: ADA/USD (1/1 full gap ~2026-06-03 21:38-23:08), ETH/USD (1/15 partial ~2026-06-04 00:21-01:51); ALGO/BTC/SOL full. Suggested offline cmds noted in doc/script output.
- All validation: py_compile (4), pytest targeted (journal 13 + econ 11 + fid 10 + price 11), full tests 1060 passed.
- Safety: clean on impl (no actionable matches; only "no .env" docstring + test forbidden guard list). Pre-existing explanatory in handoff/docs.
- No live trading, no restart, no launchctl, no orders, no .env/secrets, no config/risk/sizing/symbol/strategy/LaunchAgent/maker/exit/probe changes.
- data/offline_ohlcv/ + 4 unrelated (PROFIT_TURNAROUND_PLAN.md, SENIOR..., SPOT_CHECK..., audit_snapshot.sh) untouched (git status shows ?? only).
- Review push only.

Current state (post-025N on review): price-basis drilldown complete. Residual +1.339 is exit-driven (timeout close-vs-fill), entry res ~0 by harness design, most journal fills inside candle ranges, dominant timeout. replay_trustworthy remains false. 2 gaps (ADA/ETH) detailed with offline closure suggestions. No path to maker/post-only until gates pass after gap close + re-run. Stop after reporting; do not start next patch.

Next likely (after 025N):
- Close ADA/ETH gaps via suggested offline/manual fetch+import_validate --write (no network in this patch).
- Re-run fidelity + price-basis on improved coverage. Only if replay_trustworthy=true (dir>=0.85, med res pct<=0.10, net res <=$0.10) on real data would a gated maker/post-only feasibility (future P2) or exit experiment be considered on a fresh review branch.
- Any live/probe/sizing/strategy still requires full evidence chain + explicit approval. Do not merge.

All invariants preserved: pure offline, no broker/order/env/launchctl/restart/live/config/maker/exit/probe mutation. Untracked data + 4 unrelated untouched.

---

## P2-025K — Exchange public candles fallback + chunked acquisition (review/p2-025k-exchange-public-candles-fallback)
P2-025J at 3109bb2 (review only, no merge). Merged P2-025K at ae11960.

- Added Exchange public candles fallback with chunked acquisition (299-bar safe chunks to respect 300-bar limit) in scripts/coinbase_public_ohlcv_fetch.py.
- Chunked walk from start to end, dedup timestamps, sort ascending, throttle between requests.
- Preserves exact CSV schema for import_validate and replay_report.
- Dry-run default, explicit --fetch opt-in for network; no auth, no .env, no broker/trading endpoints ever.
- Updated docs/OHLCV_ACQUISITION_WORKFLOW.md explaining preference for Exchange public over Advanced Trade when no auth (historical candles without keys).
- Added tests with mocked HTTP for chunking, dedup, no-auth headers.
- Local OHLCV data (4 CSV files for ALGO/BTC/ETH/SOL 2026-05-25..06-03 5m) created under data/offline_ohlcv/coinbase/ but intentionally left untracked (per constraints; git status shows ?? data/offline_ohlcv/).
- Post-merge + data: replay coverage 48/49 cycles (coverage_rate 0.979592), cycles_replayed 48, 1 skipped (no_ohlcv_in_window, likely ALGO partial gaps at start).
- journal_recorded_net_pnl_sum: -1.2282313482561078935
- replay_vs_journal_direction_match: 0.5
- All validation (py_compile x4, pytest specific+full 1028 passed), safety scan clean (no actionable matches, only explanatory in docs/tests).
- No live trading, no restart, no launchctl, no orders, no .env/secrets, no config/risk/sizing/symbol/strategy/LaunchAgent changes.
- Review push only for code; handoff update committed to main after merge.

Current state: public unauthenticated Exchange candles now works with chunking for the journal window. 4 data files present but untracked. Replay now covers 48/49 cycles.

Next likely:
- P2-025L: replay economics / fee scenario report (taker/taker vs maker/maker on the now-covered real paths). Complete at e2d3ab5 on review/p2-025l-replay-economics-fee-scenarios.
- Investigate the 1 remaining skipped cycle (ADA no_ohlcv_in_window in current local data; ALGO now full coverage).

All invariants: offline/public-only, no broker/order/env/launchctl/restart/live/config mutation. Data kept untracked.

---

## P2-025L — Replay economics and fee scenario report (review/p2-025l-replay-economics-fee-scenarios)
P2-025K merged at ae11960 (bb1298c main at start of work). Review branch only. No merge, no restart, no live actions, no config/risk/sizing/symbol/strategy/LaunchAgent changes, no .env, no launchctl, no orders.

Current blocker (pre-025L): we had 48/49 coverage and directional reproduction (match 0.5) plus the known fee-dominated loss, but no decomposition of *why* the losses (fee drag vs. path/exit gross vs. sizing) on the real windows.

Added:
- `scripts/coinbase_replay_economics_report.py`: new offline report. Reuses `parse_journal_cycles`, `load_bars_from_fixture`, `run_journal_window_replay` (and the auto data/offline_ohlcv scan glue). Only analyzes cycles with OHLCV coverage; preserves full seen/skipped accounting.
- Loads the 48 covered cycles, runs zero-fee replay once for pure gross, then computes fee/net under 5 scenarios (journal_recorded_fees, taker/taker default, maker/maker, zero_fee, mixed_maker_taker) using the harness simulate math.
- Distributions (count/wins/losses/win_rate/gross/fee/net sums + avg/median/best/worst), per-sym/per-strat/per-exit, timeout count/share.
- Break-even fee rate (symmetric r where replay gross → zero net) or "not calculable".
- Notional sensitivity ($0.50/$1/$5/$10) via offline linear scaling of per-cycle gross/fees (no live config touched).
- Plain-English verdict + evidence: "fee_drag_dominant" | "directionally_negative" | "exit_logic_negative" | "inconclusive".
- --json (full machine schema), default human summary, optional --output, --max-cycles, --journal/--ohlcv-fixture.
- Always emits trade_permission=none / risk_increase=not_approved / scaling_allowed=false + safety notes.
- `tests/test_coinbase_replay_economics_report.py`: 11 tests (fee math, zero-fee net==gross, maker < taker drag ordering, skipped accounting, JSON schema + safety flags, no-forbidden, deterministic fixture economics with sample, in-memory positive/negative gross cases).
- `docs/REPLAY_ECONOMICS_REPORT.md`: what it measures/does not, 48/49 limitation, offline-only rationale, fee scenario interpretation, break-even/notional, what evidence would gate later tuning, invariants.
- Updated ACTIVE_HANDOFF (this section) with branch + exact headline numbers.

Exact headline results on real untracked data (48/49):
- cycles_seen: 49, cycles_analyzed: 48, cycles_skipped: 1 (ADA no_ohlcv_in_window), coverage_rate: 0.979592
- journal_recorded_net_pnl_sum (full): -1.2282313482561078935
- journal_recorded_net for analyzed 48: -1.09034762
- replay_gross (on 48): 1.27830742
- direction_match (replay net sign vs journal recorded): 0.5
- timeout exits: 47 (share 0.979167)
- break_even_fee_rate: 0.007394 (0.7394% symmetric)
- verdict: fee_drag_dominant
- Fee scenarios (net / wr on 48):
  - zero_fee: 1.27830742 / 0.520833
  - maker/maker: 0.58673796 / 0.520833
  - journal_recorded_fees (replay_gross - journal fees): 0.24898926 / 0.520833
  - mixed_maker_taker: -0.10994472 / 0.520833
  - taker/taker: -0.79640095 / 0.520833
- Notional sensitivity (taker baseline, offline scale):
  - $0.50: -0.39984209
  - $1: -0.79968418
  - $5: -3.99842088
  - $10: -7.99684176
- All validation: py_compile (2), pytest targeted (journal_window + economics 24 passed), full tests 1039 passed.
- Safety scan: clean on impl (no actionable matches); only explanatory "no .env / no launchctl / no orders" text in docs + forbidden-list asserts in tests.
- No live trading, no restart, no launchctl, no orders, no .env/secrets, no config/risk/sizing/symbol/strategy/LaunchAgent changes.
- data/offline_ohlcv/ and the 4 unrelated untracked files untouched (never added).
- Review push only.

Current state (post-025L on review): the economics report now decomposes the 48 covered windows. Clear evidence that replay gross on the actual paths was +1.278 while zero-fee net +1.278 (52% wr) vs taker net -0.796; journal recorded for same 48 was -1.09. Fee drag is the dominant driver (verdict fee_drag_dominant). Break-even ~0.74% per side. Notional scaling shows larger magnitude losses at $5+ uniform sizing because many actual trades used <5. Direction match only 0.5 and timeout 97.9% still visible. This does not authorize any live change or tuning; it is the required evidence gate.

Next likely (after 025L):
- P2-025M: replay fidelity reconciliation (per-cycle residual vs journal gross/net, direction_match, conservative replay_trustworthy gates). Do not proceed to maker/post-only or exit tuning until fidelity passes.
- Close the current gaps (ADA full + 1 ETH partial; ALGO now full in local data) if more OHLCV can be acquired for the exact windows.
- Only after fidelity passes (direction >=0.85, med residual <=10% notional, net res within $0.10) would a gated maker study be considered on review branch.

All invariants preserved: pure offline, no broker/order/env/launchctl/restart/live/config mutation. Untracked data policy followed.

---

## P2-025M — Replay Fidelity Reconciliation (review/p2-025m-replay-fidelity-reconciliation)
P2-025L merged at 483a76a. Review branch only. No merge, no restart, no live actions, no config/risk/sizing/symbol/strategy/LaunchAgent changes, no .env, no launchctl, no orders, no maker logic, no exit changes, no probes.

Current blocker (post-025L, per senior consultant): direction_match only 0.50 and replay-with-journal-fees net (+0.249) does not reconcile to realized analyzed journal net (-1.090). ~$1.34 gap across 48 cycles; replay may be manufacturing the apparent gross edge (+1.278). P2-025L fee scenarios not actionable until fidelity quantified and gates passed.

Added:
- `scripts/coinbase_replay_fidelity_reconciliation.py`: new offline report. Reuses parse_journal_cycles, load_bars_from_fixture, run_journal_window_replay (zero-fee for pure gross), coverage helpers from economics. Only analyzes covered cycles; preserves skipped accounting + details.
- Per-cycle: symbol/strat/exit, entry/exit ts, journal vs replay entry/exit prices + bases (journal exact for entry; high/low/close + adverse slip for replay exit), journal gross, replay gross, gross residual, journal fees, replay net with journal fees, net residual, sign match, residual % notional, direction_match, is_timeout.
- Distributions: signed/abs total gross res, mean/med/p75/p90/max abs, med % notional.
- Direction: overall match, mismatch count, timeout-specific, limited mismatch list.
- By-sym (analyzed/skipped, dir match, signed/med abs/net res), by-strat, by-exit.
- Skipped details (for current 2: ADA full + ETH partial): symbol, entry/exit ts, reason, fixable-by-re-fetch flag. Clarifies P2-025K "ALGO" vs P2-025L "ADA" vs current (ADA+ETH; ALGO full now).
- Conservative replay_trustworthy true/false + failed_gates + suspected drivers.
- Top-level safety flags always.
- `tests/test_coinbase_replay_fidelity_reconciliation.py`: 10 tests (gross/net residual math, direction/sign match, trustworthy false on poor dir or large res or missing fields, skipped accounting/details, JSON schema + safety, no-forbidden, deterministic fixture + in-memory).
- `docs/REPLAY_FIDELITY_RECONCILIATION.md`: why exists (consultant gap on 025L), definitions, trust gates, current verdict (false), skipped clarification, what must pass before 025N maker feasibility, invariants.
- Updated ACTIVE_HANDOFF (this section) with branch/commit + exact headlines.

Exact headline results (current untracked data, 50/48/2):
- cycles_seen: 50, cycles_analyzed: 48, cycles_skipped: 2, coverage_rate: 0.96
- skipped: ADA/USD (1/1, full gap), ETH/USD (1/15, partial); ALGO 7/7 full. Details include exact ts for the 2 gaps.
- journal_analyzed_gross: -0.06102946
- replay_gross: 1.27830742
- signed gross residual: +1.33933688 (matches consultant ~$1.34 gap)
- abs gross residual total: 2.25793123
- med abs gross: 0.02601312, p90: 0.12189486
- dir_match: 0.50 (24 mismatches), timeout_dir_match: ~0.51
- by-sym examples: BTC match 1.0 (negative res), ALGO match 0.0, ETH match 0.07 (large positive res)
- replay_trustworthy: false
- failed_gates: ['direction_match < 0.85 (got 0.5)', 'abs(signed total net residual using journal fees) > 0.10 (got 1.33933688)']
- suspected_drivers: low dir match (bias in exit/entry vs journal fills); timeout dominance amplifies discrepancy.
- All validation: py_compile (3), pytest targeted (journal 13 + economics 11 + fidelity 10 passed), full tests 1049 passed.
- Safety clean on impl (no actionable; explanatory in handoff + test guard lists only).
- No live trading, no restart, no launchctl, no orders, no .env/secrets, no config/risk/sizing/symbol/strategy/LaunchAgent changes, no maker/exit/probe code.
- data/offline_ohlcv/ + 4 unrelated untracked untouched.
- Review push only.

Current state (post-025M on review): fidelity report now quantifies the gap. replay_trustworthy=false on real paths. Direction 0.50, signed gross res +1.339 (replay manufactures edge), net res using journal fees also +1.339. 2 skipped (ADA+ETH) detailed with ts; ALGO now full. This blocks using P2-025L fee scenarios for decisions.

Next likely (after 025M, now post-025N):
- Close the 2 gaps (ADA full + ETH partial) with targeted manual/public fetch + import_validate --write for the exact windows (offline cmds only; see REPLAY_PRICE_BASIS doc and script --json output for precise suggested commands).
- Re-run fidelity + price-basis after gap closure. Only if trustworthy=true (dir>=0.85, med abs res pct notional <=0.10, abs signed net res using journal fees <=$0.10) on real data would a gated maker/post-only feasibility or exit experiment be considered on a fresh review branch.
- Any live/probe/sizing/strategy work still requires the full evidence chain + explicit approval. Stop after reporting; do not start next patch without new task.

All invariants preserved: pure offline, no broker/order/env/launchctl/restart/live/config/maker/exit/probe mutation. Untracked data + 4 unrelated untouched.

---

## P2-025I — Public/manual OHLCV acquisition workflow (review/p2-025i-public-manual-ohlcv-acquisition-workflow)
P2-025H merged at 9956488. Review branch only. No merge, no restart, no live actions, no config/risk/sizing/symbol/strategy/LaunchAgent changes, no .env, no launchctl, no orders.

Current blocker: journal-window replay still reports 0 coverage (48/48 skipped, "no_ohlcv_in_window") because no local OHLCV files exist for the 48 real EXIT cycles (ALGO/BTC/ETH/SOL, ~2026-05-25..06-03).

Added:
- scripts/coinbase_ohlcv_acquisition_plan.py: reads journal, derives required_symbols + exact [earliest_entry, latest_exit], recommends canonical filenames, detects missing in data/offline_ohlcv/coinbase/, emits exact import/validate --write commands for each symbol, full JSON report with network_enabled=false, acquisition_mode=manual_by_default, trade_permission=none etc.
- scripts/coinbase_public_ohlcv_fetch.py (opt-in): public unauthenticated market-data-only fetcher (legacy exchange /products/.../candles, no auth ever, no Advanced Trade endpoints, no .env). Default dry-run/no-net; --fetch to call, --write to normalize+persist same schema as validator. All tests mock HTTP; never real net in CI/tests.
- docs/OHLCV_ACQUISITION_WORKFLOW.md: current required symbols/dates, target dir, expected names, manual steps, public fetcher usage, exact replay cmd, strong warnings (no live, do not commit data, etc).
- tests/test_coinbase_ohlcv_acquisition_plan.py: required symbols/start/end/filenames/missing from fixture, safety flags, no-forbidden, isolation (no env), CLI, and mocked-HTTP tests for fetcher (url is public, no secret headers, dry-run never calls net, report has permissions).
- Updated ACTIVE_HANDOFF + cross-refs.

All outputs force trade_permission=none / risk_increase=not_approved / scaling_allowed=false.
Acquisition plan never performs network. Fetcher is strictly opt-in + mocked in tests.
Safety grep clean. No unrelated untracked touched. Review push only.

Current state: planner tells you exactly which 4 files + commands are needed. Manual export + validate --write (or opt-in public fetch) will populate data/ dir. Replay will then be able to use real windows instead of always skipping.

Next likely:
- P2-025J: run journal-window replay after OHLCV coverage exists (reproduce known loss directionally on real price paths from the journal windows).
- or P2-025J: maker/post-only economics study (lower fee scenario) only after replay coverage improves and baseline loss reproduction is confirmed on real data.

All invariants preserved: offline, no broker/order/env/launchctl/restart/live/config mutation.

---

## P2-025F — Journal-window OHLCV replay baseline (review/p2-025f-journal-window-replay-baseline)
P2-025E merged at 0dd1105. All work on review branch only. No merge, no restart, no live actions, no config/risk/sizing/symbol/strategy/LaunchAgent changes.

Purpose: add offline journal-window replay so the hardened harness can be validated against the known live loss (fee-drag dominated, ~2% win rate, net ~-1.09, dominant max-hold exits) **before** any exit/strategy "fix" experiments are run through it.

- Added journal-window replay adapter (parse_journal_cycles + run_journal_window_replay) to coinbase_offline_backtest.py (reuses _simulate_one_trade + existing journal entry support).
- Added scripts/coinbase_journal_window_replay_report.py (CLI --json --journal --ohlcv-fixture --fee-scenario etc; emits full required schema with cycles_seen/replayed/skipped, skip_reason_breakdown, recorded vs replayed nets, direction_match, per-strat/sym, dominant exit, safety flags).
- Added tests/fixtures/journal_window_replay/ (sample journal + ohlcv covering timeout/stop/fee-drag + skip case).
- Added tests/test_coinbase_journal_window_replay.py (parses by header, skips malformed, multi-cycle replay, fee-drag negative repro, skip breakdown, summaries, direction match, JSON+permissions, isolation proofs).
- Added docs/JOURNAL_WINDOW_REPLAY_BASELINE.md (why, reproduction requirement, journal_recorded vs replay, taker default, limitations, next).
- Updated this file + OFFLINE_BACKTEST_REPLAY_HARNESS.md (cross-ref).
- All outputs still force trade_permission=none / risk_increase=not_approved / scaling_allowed=false.
- Safety: no forbidden strings, no live calls, no mutation.
- Review push only.

Next likely:
- P2-025G maker/post-only economics study (using the window replay) or real OHLCV ingestion expansion for the actual journal dates (whichever gives better coverage first).
- Only after directional loss reproduction on real windows should exit-logic changes be proposed.

---

## P2-025G — Offline OHLCV ingestion for journal-window replay (review/p2-025g-offline-ohlcv-journal-window-coverage)
P2-025F at 0a28beb on main. Review only. No live mutation/restart/trading authority/config changes.

Added:
- Enhanced OHLCV loader in coinbase_offline_backtest.py: load_bars_from_fixture now supports .csv + .json, symbol column, header mapping (open/o etc), _normalize_symbol ( -_/ to / ), time/symbol filter, sort, skip malformed. Bar has optional symbol.
- Coverage analysis in journal_window_replay_report: computes cycles_with/without, coverage_rate, required_symbols, earliest/latest ts, per_symbol_coverage, missing_ohlcv_directory flag for data/offline_ohlcv/coinbase/ .
- sample_ohlcv.csv + updated json fixtures with symbols so replay can succeed for matching windows.
- Tests for csv load, coverage fields, replayed>0 + skipped with fixture.
- Doc updates in JOURNAL_WINDOW_REPLAY_BASELINE.md and ACTIVE_HANDOFF.

Current: real journal smoke will still show low/0 coverage unless local OHLCV files placed (no network fetch added; loader is fixture-only). With fixture, smokes show replayed>0 and coverage >0 for subset.

Next likely: P2-025H offline-only real OHLCV import/export tool (for user-exported csv from exchange), or maker/post-only study using now-replayable windows.

All invariants: offline, no broker/order/env/launchctl/restart/live.



## P2-025H — Local OHLCV import tool for journal-window replay (review/p2-025h-local-ohlcv-import-tool)
P2-025G at 09e1146 on main. Review branch only.

- Added scripts/coinbase_ohlcv_import_validate.py: safe local import/validate for CSV/JSON OHLCV.
  - Default dry-run (no write). Explicit --write to export normalized CSV to data/offline_ohlcv/coinbase/.
  - Auto symbol normalization, column mapping, sort/dedup, gap reporting, optional journal coverage hint.
  - No network by default, no auth/.env/broker. Emits full safety flags (trade_permission=none etc.).
- Enhanced replay report auto-discovery of local files in data/ dir for coverage (if no --ohlcv-fixture).
- Added tests/test_coinbase_ohlcv_import_validate.py (csv/json, norm, dups/gaps, dry-run vs write, safety, isolation).
- Added docs/OHLCV_LOCAL_IMPORT.md (usage, format, placement, why, safety, limitations).
- Updated ACTIVE_HANDOFF.

Current limitation: without local OHLCV files placed, real journal coverage remains 0. Tool + fixtures allow validation and population of the data dir.

All work offline, no live mutation, no restart, no trading authority.

Next likely:
- P2-025I: run full journal-window replay against local OHLCV once coverage exists (to reproduce loss directionally with real paths).
- or P2-025I: opt-in public unauthenticated candle fetcher (if local files still unavailable after manual placement).



## P2-025E — Harden offline Coinbase backtest harness (review/p2-025e-harden-offline-backtest-harness)
P2-025D at e93c286 on main. Review branch for hardening only. No merge, no restart, no live actions of any kind.
All changes offline/fixture-only; no config/risk/sizing/symbol/strategy/LaunchAgent/.env/launchctl/order changes.

Hardening scope (addresses Claude review of P2-025D):
- Intra-bar TP/SL detection (high/low); SL precedence if both in same bar. New fixtures + tests.
- Fee scenario modeling: default taker/taker (0.012/0.012 conservative); maker/maker optional (lower rates via CLI). New report fields: fee_scenario, gross_return_rate, round_trip_fee_rate, net_return_rate, cleared_fee_hurdle, percent_trades_clearing_fee_hurdle, net_pnl_per_trade.
- Pluggable exit policy scaffold: --exit-policy static (keeps prior); --exit-policy live_atr (documented placeholder with deterministic output + explicit TODO; full ATR parity with live strategy deferred, no risky imports).
- Journal-driven replay: --journal-fixture + --ohlcv-fixture; multi-entry simulation from journal (symbol/strategy/entry_time/entry_price/notional) against fixture candles. New fixture + tests.
- Updated report JSON (p2-025e schema), 5 new fixtures, expanded tests (incl. hardening test file), updated docs.
- All outputs still force trade_permission=none, risk_increase=not_approved, scaling_allowed=false.
- Safety: no forbidden action strings in source; full py_compile + pytest (old + new) + smokes + grep pass.
- Explicit: taker/taker default to avoid optimistic fee drag under-statement; close-only was insufficient; harness still does not approve live changes. Must eventually reproduce journal loss direction (fee ~94% of loss) on fixtures before exit "improvements" can be trusted for live.

- Added/updated: coinbase_offline_backtest.py, scripts/coinbase_offline_backtest_report.py, tests/test_coinbase_offline_backtest_hardening.py, 5 fixtures/, docs/OFFLINE_BACKTEST_REPLAY_HARNESS.md, docs/ACTIVE_HANDOFF.md
- Review branch only; push review; stop.

Next likely: continue P2-025E exit logic experiments (use hardened harness + journal to prove net-of-fee gains offline first).

## P2-025D — Offline backtest / replay harness (review/p2-025d-offline-backtest-replay-harness)
P2-025C merged at 30d0763; controlled restart complete; coinbase_probe_enabled=false now live.
No further restarts for this patch. All work offline/fixture-only.
- Added coinbase_offline_backtest.py (replay with TP/SL/hold/fees/slippage)
- Added scripts/coinbase_offline_backtest_report.py (--json, configurable policy)
- Added tests/test_coinbase_offline_backtest.py (TP, SL, hold, fee-drag net-negative, determinism, isolation, permission fields)
- Added 4+ fixtures under tests/fixtures/offline_backtest/
- Added docs/OFFLINE_BACKTEST_REPLAY_HARNESS.md
- Updated this file
- trade_permission=none, risk_increase=not_approved, scaling_allowed=false enforced in output
- Zero live broker, zero orders, zero runtime mutation, zero config/risk/sizing/symbol changes
- Review branch only; no merge

Next likely: P2-025E exit-logic overhaul (offline/simulated only, using this harness + journal-truth to prove net-of-fee improvement before any live proposal).

# ACTIVE HANDOFF — Alpaca/Coinbase Autonomous Trading Bot

## P2-025C — journal-truth P/L and probe shutoff (review/p2-025c-journal-truth-pnl-and-probe-shutoff)

P2-025C pivots from additional read-only scaffolding to direct loss control.
It adds an offline Coinbase journal-truth P/L report and defensively disables
the structurally uneconomic legacy `coinbase_probe_enabled` path.

Purpose:

- compute live closed-cycle P/L from the local Coinbase journal by CSV header
  name, not fixed index
- classify that readout as `journal_recorded_broker_backed`
- keep the stricter numeric-safe direct-capture gate intact for future scaling
- make clear that `unsafe_to_aggregate` is not the same as "no evidence"
- stop the 0.50 USD probe path pending backtest/replay evidence

Preserved truth:

- `coinbase_probe_enabled=false`
- `coinbase_probe_notional_usd` unchanged
- trade caps, notional caps, max-open, max-trades/day, eligible symbols, SOL
  exclusion, stop-loss, take-profit, hold time, and strategy thresholds unchanged
- no live broker calls
- no `--live-read-only`
- no `.env` or secrets reads
- no order/cancel/close/modify
- no runtime restart and no `launchctl`
- `trade_permission=none`
- `profit_readout=unsafe_to_aggregate`
- `aggregation_allowed=false`
- `scaling_allowed=false`
- `risk_increase=not_approved`

Next likely patches:

- P2-025D offline backtest/replay harness
- P2-025E exit-logic overhaul validated through the backtester
- P2-025F maker-first/post-only execution feasibility

## P2-025B — read-only market/trend context registry (review/p2-025b-read-only-market-context-registry)

P2-025B adds an offline, fixture-backed Coinbase market/trend context registry
and report script. It is standalone for this patch and does not feed live
runtime decisions.

Purpose:

- model Coinbase market data and product metadata as future execution-quality
  inputs, not trading authority
- model Coinbase level2 order book and order preview as future/disabled research
  paths
- model CoinGecko and future news/sentiment sources as advisory-only
- provide per-symbol context for BTC/USD, ETH/USD, ADA/USD, AVAX/USD, DOGE/USD,
  LINK/USD, and LTC/USD
- keep SOL/USD external/staked/non-bot inventory and non-tradable by the bot

Preserved truth:

- `trading_authority=none`
- `trade_permission=none`
- trend/news/sentiment context cannot trigger trades
- external context cannot change sizing, risk, strategy gates, or execution
  quality gates
- no live broker calls
- no `--live-read-only`
- no `.env` or secrets reads
- no order/cancel/close/modify
- no runtime state/log mutation
- no restart and no `launchctl`
- no live risk, sizing, symbol, strategy-threshold, runtime config, or
  LaunchAgent changes
- no derivatives/perps/prediction markets/stocks/ETFs/margin/leverage/options
  enabled
- `profit_readout=unsafe_to_aggregate`
- `risk_increase=not_approved`

Next likely patches:

- P2-025C Coinbase product metadata fixture/adapter
- P2-025D mandatory pre-trade preview/cost gate
- P2-025E maker-first/post-only feasibility
- P2-025F WebSocket level2 design/offline simulator
- P2-026 all-asset opportunity registry read-only

## P2-025A — Coinbase execution-quality registry foundation (review/p2-025a-coinbase-execution-quality-registry)

P2-025A adds an offline, fixture-backed Coinbase execution-quality registry and
report script for the already-approved controlled spot basket:

- BTC/USD
- ETH/USD
- ADA/USD
- AVAX/USD
- DOGE/USD
- LINK/USD
- LTC/USD

Purpose:

- rank symbols by bid/ask spread, maker/taker fee assumptions, slippage buffer,
  target notional, and required break-even gross move
- keep Coinbase preview PNL advisory-only because it excludes fees and slippage
- preserve SOL/USD as external/staked/non-bot inventory, excluded from ranking
  and bot-tradable inventory
- provide the foundation for future product metadata, preview/cost, maker-first,
  and fill-reconciliation gates

Preserved truth:

- no live broker calls
- no `--live-read-only`
- no `.env` or secrets reads
- no order/cancel/close/modify
- no runtime state/log mutation
- no restart and no `launchctl`
- no sizing/risk/cap/symbol/strategy-threshold changes
- no derivatives/perps/prediction markets/margin/leverage/options/stocks/ETFs
- `profit_readout=unsafe_to_aggregate`
- `aggregation_allowed=false`
- `scaling_allowed=false`
- `risk_increase=not_approved`

Next likely patches:

- P2-025B Coinbase product metadata fixture/adapter
- P2-025C mandatory pre-trade preview/cost gate
- P2-025D maker-first/post-only execution feasibility
- P2-025E broker-backed fill reconciliation improvement

## P2-024F — external/staked SOL no longer consumes bot max_open_positions slot (review/p2-024f-external-inventory-max-open-slot-fix)
P2-024D merged/restarted at main 41447eb. Expanded basket (BTC/ETH/ADA/AVAX/DOGE/LINK/LTC) live under shared pilot caps.
Post-P2-024D observation: expanded basket scanning, candidates (ADA/LTC) in dashboard, but no post-restart trades.
P2-024E root cause: RISK_GATE_BLOCK (external SOL on broker made broker.get_all_positions()=1, which was fed into AccountState.open_positions for risk check, so max_open=1 "reached" even with bot state=0).
Fix: main.py now populates AccountState.open_positions / symbols for risk/duplicate from bot SessionState (local bot-owned only). External SOL stays visible (state/external_inventory.json, position_mgr logs, dashboards/audit) but is excluded from the cap count and does not block candidates via max_open or manual_review.
- SOL remains excluded, non-tradable by bot, no adoption/close by code.
- max_open=1 still applies to true bot-owned positions.
- No risk/notional/caps increase, no SOL enablement, all prior guardrails + prohibitions followed.
- profit_readout unsafe_to_aggregate; next success = first closed broker-backed net P/L from expanded symbol.

## P2-024D review — controlled live Coinbase spot symbol expansion

**Branch:** `review/p2-024d-controlled-live-symbol-expansion`

P2-024C is merged on `main` at `3263ab3`. P2-024D expands the live Coinbase
spot candidate basket because BTC/ETH-only scope was producing too few
opportunities under the current trend, fee-drag, and risk gates.

Approved expanded live spot symbols:

- BTC/USD
- ETH/USD
- ADA/USD
- AVAX/USD
- DOGE/USD
- LINK/USD
- LTC/USD

Explicitly excluded:

- SOL/USD
- derivatives/perps
- prediction markets
- unsupported products
- invalid or stale quote products

Preserved truth:

- expansion increases opportunity count, not trade size
- shared caps remain active across all symbols
- `max_trade_notional_usd=10.00`
- `absolute_hard_trade_cap_usd=10.00`
- current balance final notional preview remains about `5.0000`
- `max_open_positions=1`
- `max_trades_per_day=3`
- `fee_drag_guard_enabled=true`
- `trade_permission=none` for dashboard/digest
- no runtime restart
- no `launchctl`
- no live broker calls during implementation/tests
- no `--live-read-only`
- no `.env` or secrets during tests
- no order/cancel/close/modify
- no buy/sell/preview/order placement
- no derivatives/perps/prediction-market live execution
- `profit_readout=unsafe_to_aggregate`
- `aggregation_allowed=false`
- `scaling_allowed=false`
- `risk_increase=not_approved`

Next success metric:

- direct broker-backed net P/L from the first closed expanded-symbol `$5-$10`
  cycle

---

## P2-024C review — dashboard observation loop and operator digest

**Branch:** `review/p2-024c-dashboard-observation-loop-operator-digest`

P2-024B is merged on `main` at `b87ebca`. P2-024C adds an offline finite
observation loop and operator digest on top of the Coinbase opportunity
dashboard.

New files:

- `scripts/coinbase_dashboard_observation_loop.py`
- `scripts/coinbase_operator_digest.py`
- `docs/COINBASE_DASHBOARD_OBSERVATION_LOOP.md`
- `tests/test_coinbase_dashboard_observation_loop_operator_digest.py`

Current-style expected readout remains:

- verdict `SIT_OUT_CONFIRMED`
- next required action
  `continue_observing_until_btc_eth_signal_clears_trend_fee_and_risk_gates`
- final trade notional preview `5.0000`
- BTC/USD and ETH/USD only
- SOL/USD excluded
- `trade_permission=none`
- `profit_readout=unsafe_to_aggregate`
- `aggregation_allowed=false`
- `scaling_allowed=false`
- `risk_increase=not_approved`

Preserved truth:

- no runtime restart
- no `launchctl`
- no live broker calls during implementation/tests
- no `--live-read-only`
- no `.env` or secrets during tests
- no order/cancel/close/modify
- no buy/sell/preview/order placement
- no strategy auto-trigger from trends
- no sizing changes
- no risk override
- no notional increase
- no symbol expansion beyond BTC/USD and ETH/USD
- no SOL trading
- no derivatives/perps/prediction-market live execution

---

## P2-024B review — offline Coinbase opportunity dashboard

**Branch:** `review/p2-024b-coinbase-opportunity-dashboard`

P2-024A is merged on `main` at `dce16d9`. The live Coinbase bot was restarted
successfully with target `com.vadim.coinbase-crypto-bot` and PID `52004`.

Current live/pilot context provided by the user:

- broker `coinbase`
- mode `live`
- open_positions `0`
- risk_halt_active `false`
- kill_switch_present `false`
- buying_power about `49.4345`
- equity about `50.3681`
- final trade notional preview `5.0000`
- balance-relative pilot percent `0.10`
- min notional `5.00`, max notional `10.00`, absolute hard cap `10.00`
- BTC/USD and ETH/USD only
- SOL/USD excluded
- `fee_drag_guard_enabled=true`

Latest post-restart observation:

- BTC/USD regime `downtrend`, allowed strategies `[]`
- ETH/USD regime `downtrend`, allowed strategies `[]`
- bot sat out
- no new `$5-$10` closed cycle yet
- trend layer remains `read_only_advisory`

P2-024B adds `scripts/coinbase_opportunity_dashboard.py`, an offline dashboard
that composes local heartbeat state, balance-relative sizing preview, trend
advisory, and fee-drag evidence into one operator readout.

Preserved truth:

- `trade_permission=none`
- no live trade triggers
- no strategy auto-trigger from trends
- no sizing changes
- no risk override
- no notional increase
- no symbol expansion beyond BTC/USD and ETH/USD
- no SOL trading
- no live broker calls during implementation/tests
- no `--live-read-only`
- no `.env` or secrets during tests
- no order/cancel/close/modify
- no buy/sell/preview/order placement
- `profit_readout=unsafe_to_aggregate`
- `aggregation_allowed=false`
- `scaling_allowed=false`
- `risk_increase=not_approved`

---

## P2-024A review — read-only Coinbase trend advisory registry

**Branch:** `review/p2-024a-read-only-trend-advisory-registry`

P2-023B is merged on `main` at `2657dd1`. The live Coinbase bot was restarted
successfully with target `com.vadim.coinbase-crypto-bot` and new PID `52004`.

Current live/pilot context provided by the user:

- broker `coinbase`
- mode `live`
- open_positions `0`
- risk_halt_active `false`
- buying_power about `49.4345`
- equity about `50.3681`
- balance-relative sizing active
- `pilot_trade_percent_of_balance=0.10`
- `min_trade_notional_usd=5.00`
- `max_trade_notional_usd=10.00`
- `absolute_hard_trade_cap_usd=10.00`
- BTC/USD and ETH/USD only
- SOL/USD excluded
- `fee_drag_guard_enabled=true`

Latest post-restart observation:

- BTC/USD regime `downtrend`, allowed strategies `[]`
- ETH/USD regime `downtrend`, allowed strategies `[]`
- bot sat out
- no new trade yet
- current bot is not yet pulling broader trend/news/sentiment context

P2-024A adds a read-only advisory layer:

- `scripts/coinbase_trend_signal_registry.py`
- `scripts/coinbase_trend_advisory_snapshot.py`
- source registry entries for local Coinbase market context, CoinGecko
  trending, CoinDesk RSS/news, and future disabled sources
- normalized schema `p2-024a.trend_advisory.v1`
- BTC/USD and ETH/USD only
- SOL/USD excluded from live advisory symbols
- positive external trend/news can only become `confirm_only`
- local downtrend with no allowed strategies remains `avoid` or `watch`

Preserved truth:

- advisory layer is read-only
- `trade_permission=none`
- no live trade triggers
- no sizing changes
- no risk override
- no live broker calls during implementation/tests
- no order/cancel/close/modify
- no buy/sell/preview/order placement
- no symbol expansion beyond BTC/USD and ETH/USD
- no SOL trading
- no derivatives/perps/prediction-market live execution
- no `.env` or secrets during tests
- next broker-backed profit readout still depends on the next closed `$5-$10`
  BTC/ETH cycle

---

## P2-023B review — balance-relative fee-aware Coinbase sizing and process audit

**Branch:** `review/p2-023b-balance-relative-fee-aware-sizing`

P2-023A is merged on `main` at `416e4e6`. P2-023B replaces the fixed-only `$5`
Coinbase pilot with 10%-of-balance sizing under a `$10` absolute hard cap.

Observed latest account snapshot provided by the user:

- equity `50.3762`
- buying_power `49.4345`
- open_positions `0`
- status `running`
- mode `live`
- risk_halt_active `false`
- kill_switch_present `false`

P2-023B sizing:

- basis: `buying_power_then_equity`
- effective balance: min(valid positive buying power, valid positive equity)
- pilot percent: `0.10`
- min fee-aware notional: `$5.00`
- max trade notional: `$10.00`
- absolute hard cap: `$10.00`
- BTC/USD and ETH/USD only
- SOL/USD excluded
- max open positions remains `1`
- max trades per day remains `3`

Fee-drag guard remains active using the measured ETH cycle:

- gross P/L `0.0025`
- total fees `0.0180`
- net P/L `-0.0155`
- minimum required gross move rate about `0.018970`

Process audit:

- Adds `scripts/coinbase_trading_process_audit.py`.
- Classifies LaunchAgents as `trading_bot`, `price_logger`, or `unknown`.
- Prior restart confusion around `com.vadim.price-path-logger.plist` is now
  explicitly guarded: do not restart unknown or price logger plists.

Preserved truth:

- no live broker calls during implementation/tests
- no `--live-read-only` execution during verification
- no `.env` or secrets
- no order/cancel/close/modify
- no SOL trading
- no symbol expansion beyond BTC/USD and ETH/USD
- no margin/leverage/options/futures/perps
- no unrestricted risk increase beyond the capped `$10` pilot
- no merge to main from this branch

---

## P2-023A review — controlled $5 fee-aware Coinbase pilot

**Branch:** `review/p2-023a-controlled-5usd-fee-aware-pilot`

P2-023A replaces ineffective `$1` Coinbase micro-trades with a controlled `$5`
fee-aware pilot gate.

Measured broker-backed evidence:

- ETH cycle `real-ethusd-029`
- entry filled_value `1.0000`
- entry fee `0.0060`
- exit filled_value `1.0025`
- exit fee `0.0120`
- gross P/L `0.0025`
- total fees `0.0180`
- net P/L `-0.0155`
- net direction negative

Conclusion:

- `$1` live micro-trades are no longer treated as meaningful live execution.
- The measured cycle was directionally right but fee-negative.
- Future Coinbase entries must clear measured fee drag plus spread/slippage
  buffer before a proposal is allowed.

P2-023A updates:

- Adds `coinbase_fee_aware_pilot.py`.
- Adds `scripts/coinbase_fee_drag_profitability_report.py`.
- Configures a controlled `$5` BTC/ETH-only Coinbase pilot:
  - `max_trade_notional_usd=5.00`
  - `pilot_trade_notional_usd=5.00`
  - `max_open_positions=1`
  - `max_trades_per_day=3`
  - BTC/USD and ETH/USD only
  - SOL/USD excluded
- Adds a fee-drag gate:
  - observed round-trip fee rate from broker-backed evidence
  - expected gross move must exceed fee rate plus spread/slippage buffer
  - otherwise skip with `fee_drag_expected_edge_too_small`

Preserved truth:

- `$5` is a controlled pilot, not unrestricted scaling.
- `scaling_allowed=false` beyond the `$5` pilot cap.
- risk increase beyond the controlled pilot is not approved.
- no live broker calls during implementation/tests
- no `--live-read-only` execution during verification
- no `.env` or secrets
- no order/cancel/close/modify
- no `logs/coinbase_fills.csv` writes
- no `append_coinbase_fill_row` activation
- no SOL trading
- no margin/leverage/options/futures/perps/commodities
- no merge to main from this branch

---

## P2-022F review — numeric-safe broker fact probe output

**Branch:** `review/p2-022f-numeric-safe-broker-fact-probe`

P2-022F adds explicit numeric-safe direct broker fact output to
`scripts/coinbase_read_only_broker_fact_probe.py` so the P2-022E builder and
P2-022D numeric readout can compute broker-backed P/L from real captured
financial values, while identifiers remain redacted.

Current good state:

- P2-022E is merged on `main` at `d992510`.
- P2-022E proved the offline builder/redactor can preserve numeric fields when
  actual numbers exist.
- The one-cycle live read-only capture for `real-ethusd-029` remained blocked
  because the probe emitted presence booleans/markers, not numeric
  `filled_value` and `total_fees` values.

P2-022F updates:

- Adds `--include-numeric-pnl-fields` / `--numeric-safe`.
- Numeric-safe probe JSON includes direct broker order fields such as
  `filled_value`, `total_fees`, `filled_size`, `average_filled_price`,
  `settled`, `status`, and `side` when available.
- Numeric-safe probe JSON includes direct broker fill fields such as `price`,
  `size`, `fee`/`commission`, `commission_detail_total`, `size_in_quote`,
  `product_id`, and `side` when available.
- Order IDs, client-order IDs, trade/fill IDs, account/portfolio/user IDs, and
  secret/auth/key/token/signature-like fields remain redacted.
- Default probe output remains presence-only unless the numeric-safe flag is
  explicitly requested.

Next step after merge:

- Retry exactly one human-approved numeric-safe read-only capture for the same
  ETH cycle (`real-ethusd-029`) using the new flag.
- Then run the offline one-cycle builder and numeric readout.

Preserved truth:

- `profit_readout_real_current=unsafe_to_aggregate` until numeric-safe broker
  values are captured and accepted for real-current reporting.
- `scaling_allowed=false`
- risk increase not approved
- no live broker calls during implementation/tests
- no `--live-read-only` execution during verification
- no `.env` or secrets
- no order/cancel/close/modify
- no `logs/coinbase_fills.csv` writes
- no `append_coinbase_fill_row` activation
- no risk/notional/symbol/config/strategy expansion

---

## P2-022E review — numeric-safe read-only capture/redaction bridge

**Branch:** `review/p2-022e-numeric-safe-read-only-capture`

P2-022E adds an offline numeric-safe redaction and one-cycle payload build step
so direct Coinbase read-only evidence can preserve broker financial numbers
needed by the P2-022D numeric P/L engine while still redacting identifiers and
secret-like material.

Current good state:

- P2-022D is merged on `main` at `47f1103`.
- The numeric readout engine works for complete direct numeric broker evidence.
- The real one-cycle payload remained blocked because `filled_value`/proceeds
  and fee amounts were redacted into presence markers, which prove field
  presence but are not numeric values.

P2-022E updates:

- Adds `--preserve-numeric-pnl-fields` support to
  `scripts/redact_broker_payload.py`.
- Adds `scripts/coinbase_one_cycle_numeric_safe_payload_builder.py`.
- Preserves direct broker numeric P/L fields such as `filled_value`,
  `total_fees`, `filled_size`, `average_filled_price`, per-fill `price`,
  `size`, `fee`/`commission`, `commission_detail_total`, `size_in_quote`, and
  `proceeds`.
- Redacts order IDs, trade/fill IDs, client order IDs, account/portfolio/user
  IDs, and secret/auth/key/token/signature-like fields.

Next step after merge:

- Rebuild a numeric-safe payload from already captured raw entry/exit files if
  present in `/tmp`.
- If raw files are absent, perform only one future human-approved read-only
  capture cycle, then run this offline numeric-safe builder and the P2-022D
  numeric readout.

Preserved truth:

- `profit_readout_real_current=unsafe_to_aggregate` until numeric-safe broker
  values are accepted for real-current reporting.
- `scaling_allowed=false`
- risk increase not approved
- no live broker calls during implementation/tests
- no `--live-read-only` execution during verification
- no `.env` or secrets
- no order/cancel/close/modify
- no `logs/coinbase_fills.csv` writes
- no `append_coinbase_fill_row` activation
- no risk/notional/symbol/config/strategy expansion

---

## P2-022D review — numeric broker-backed one-cycle P/L readout

**Branch:** `review/p2-022d-numeric-broker-backed-cycle-readout`

P2-022D adds an offline numeric P/L readout layer for direct Coinbase
broker-backed evidence cycles.

Current good state:

- P2-022C2 is merged on `main` at `586b5fb`.
- The real ETH cycle `real-ethusd-029` resolves as L4 direct broker evidence:
  - `verdict=EVIDENCE_RESOLVED`
  - `profit_readout=measured_broker_backed_limited`
  - `cycles_evaluated=1`
  - `complete_direct_cycles=1`
  - entry/exit direct order IDs, fill IDs, fees, and filled value/proceeds are
    available as broker-backed evidence.
- Numeric realized P/L still requires numeric-safe local extraction of
  `filled_value`/proceeds and fee amounts.
- Redacted presence markers prove completeness but are not numeric values.

P2-022D updates:

- Adds `scripts/coinbase_broker_backed_pnl_readout.py`.
- Computes limited-cycle gross P/L, total fees, and net P/L with `Decimal` only
  when direct numeric broker values are present.
- Blocks numeric P/L when values are redacted presence markers.
- Keeps local journal P/L advisory only.

Preserved truth:

- `profit_readout_real_current=unsafe_to_aggregate` until numeric-safe broker
  values are accepted for real-current reporting.
- `scaling_allowed=false`
- risk increase not approved
- no live broker calls
- no `--live-read-only` execution during verification
- no `.env` or secrets
- no order/cancel/close/modify
- no `logs/coinbase_fills.csv` writes
- no `append_coinbase_fill_row` activation
- no risk/notional/symbol/config/strategy expansion

---

## P2-022C2 review — adapt one-cycle read-only payload

**Branch:** `review/p2-022c2-adapt-one-cycle-read-only-payload`

P2-022C2 adapts the clean one-cycle Coinbase read-only capture payload into the
offline broker evidence adapter and profit evidence resolver schemas.

Current good state:

- P2-022C1 is merged on `main` at `d39ef3e`.
- The one-cycle human-approved read-only capture for `real-ethusd-029` succeeded
  for both entry and exit broker reads after the probe compatibility fix.
- Entry and exit both showed direct broker-backed order/fill evidence presence:
  filled size, average filled price, filled value, total fees, settlement, per-fill
  fees, and stable fill identifiers.
- The remaining blocker is offline-only: the clean payload used
  `cycles[].entry_broker_payload_redacted` and
  `cycles[].exit_broker_payload_redacted`, while the adapter/resolver previously
  expected normalized `evidence_cycles`.
- No more live broker reads are needed until this adapter mapping is verified
  offline.

P2-022C2 updates:

- `scripts/coinbase_read_only_broker_fact_probe.py` keeps `--output json`
  stdout as pure JSON by sending the live-read-only warning banner to stderr.
- `scripts/coinbase_broker_evidence_adapter.py` recognizes
  `schema_version=p2-022c.one_cycle_read_only_payload.v1`.
- `scripts/coinbase_profit_readout_evidence_resolver.py` can evaluate that
  payload shape directly in offline mode.

Preserved truth:

- `profit_readout_real_current=unsafe_to_aggregate` until this branch is merged
  and offline resolver verification passes.
- Fixture-only one-cycle readout may become `measured_broker_backed_limited`.
- `aggregation_allowed_real_current=false`
- `scaling_allowed=false`
- risk increase not approved
- no live broker calls
- no `--live-read-only` execution during verification
- no `.env` or secrets
- no order/cancel/close/modify
- no `logs/coinbase_fills.csv` writes
- no `append_coinbase_fill_row` activation
- no risk/notional/symbol/config/strategy expansion

---

## P2-022C1 review — read-only probe compatibility fix

**Branch:** `review/p2-022c1-fix-read-only-probe-compatibility`

P2-022C1 fixes the Coinbase read-only broker fact probe compatibility issue found
during the first one-cycle human-approved capture attempt.

Current good state:

- P2-022B is merged on `main` at `2b89d82`.
- The paired evidence request builder is ready and can produce checklist-ready
  BTC/ETH paired order requests.
- The attempted one-cycle capture for `real-ethusd-029` failed before broker
  evidence was captured because:
  - the checklist emitted stale probe syntax using `--json`;
  - `scripts/coinbase_read_only_broker_fact_probe.py` passed unsupported
    `dry_run=True` to the current `BrokerCoinbase()` constructor.
- P2-022C1 updates planned checklist probe commands to use `--output json`.
- P2-022C1 updates the probe to construct `BrokerCoinbase()` only after explicit
  `--live-read-only` opt-in and to report structured read-only safety fields.

Next step after merge:

- Retry exactly one human-approved read-only Coinbase evidence capture cycle.
- Keep capture limited to listed BTC/ETH order IDs and date windows.
- Redact any captured broker payload before offline adapter/resolver use.

Preserved truth:

- `profit_readout_real_current=unsafe_to_aggregate`
- `aggregation_allowed_real_current=false`
- `scaling_allowed=false`
- risk increase not approved
- no live broker calls during implementation or tests
- no `--live-read-only` execution during verification
- no `.env` or secrets
- no order/cancel/close/modify
- no `logs/coinbase_fills.csv` writes
- no `append_coinbase_fill_row` activation
- no risk/notional/symbol/config/strategy expansion

---

## P2-022B review — paired Coinbase evidence request builder

**Branch:** `review/p2-022b-paired-evidence-request-builder`

P2-022B turns the successful one-off `/tmp` paired evidence request generation
into a deterministic offline repo script:

- `scripts/coinbase_paired_evidence_request_builder.py`
- `docs/PAIRED_COINBASE_EVIDENCE_REQUEST_BUILDER.md`
- `tests/test_coinbase_paired_evidence_request_builder.py`

Latest good state:

- `main` includes P2-021C5.
- Live execution is repaired.
- SOL/USD is external/staked, excluded from active recovery, and excluded from
  Coinbase candidate cycles.
- Manual paired discovery succeeded with real BTC/ETH rows:
  `uuid_btc_eth_rows=60` and `paired_cycles_count=8`.
- The generated request can pass the human-approved read-only capture checklist.

The next step after merge is a human-approved read-only Coinbase broker evidence
capture for the listed BTC/ETH entry and exit order IDs, followed by redaction,
offline adapter normalization, and offline profit evidence resolution.

Preserved truth:

- `profit_readout_real_current=unsafe_to_aggregate`
- `aggregation_allowed_real_current=false`
- `scaling_allowed=false`
- risk increase not approved
- no live broker calls
- no `--live-read-only` execution
- no `.env` or secrets
- no order/cancel/close/modify
- no state/log mutation outside explicit output path
- no `logs/coinbase_fills.csv` writes
- no `append_coinbase_fill_row` activation
- no risk/notional/symbol/config/strategy expansion

---

## P2-021C5 review — exclude external inventory from Coinbase candidates

**Branch:** `review/p2-021c5-exclude-external-inventory-candidates`

P2-021C5 removes authoritative external/staked inventory symbols from Coinbase
live entry candidate evaluation. After P2-021C4, `manual_review_position_open`
is resolved and broker recovery no longer rehydrates user-staked SOL/USD into
active `open_positions`, but SOL/USD could still consume scan/risk cycles and
produce safe-but-wasteful journal rows such as `already have open position in
SOL/USD`.

The new candidate filter excludes a symbol only when
`state/coinbase/external_inventory.json` proves all of:

- `external_inventory_classification=external_staked_position`
- `staked_external_position=true`
- `bot_inventory=false`
- `tradable_by_bot=false`
- `manual_close_allowed=false`
- `blocks_new_entries=false`

BTC/USD and ETH/USD remain eligible candidates. Missing or malformed external
inventory fails safely by excluding nothing. True active bot-owned unresolved
positions still flow through the existing blocker/risk logic.

Preserved truth:

- `profit_readout_real_current=unsafe_to_aggregate`
- `aggregation_allowed_real_current=false`
- `scaling_allowed=false`
- risk increase not approved
- no live broker calls
- no `--live-read-only`
- no `.env` or secrets
- no order/cancel/close/modify
- no auto-close or auto-sell SOL
- no risk/notional/symbol/config expansion
- no `logs/coinbase_fills.csv` writes
- no `append_coinbase_fill_row` activation

---

## P2-021C4 review — external-inventory-aware broker recovery

**Branch:** `review/p2-021c4-external-inventory-aware-broker-recovery`

P2-021C4 fixes the post-P2-021C3 restart path where broker-position recovery
could rehydrate the user-staked SOL/USD position back into active
`open_positions` with `recovery_source=broker_position`.

The authoritative classification remains:

- `staked_external_position=true`
- `external_inventory_classification=external_staked_position`
- `tradable_by_bot=false`
- `manual_close_allowed=false`
- `bot_inventory=false`
- `blocks_new_entries=false`

Recovery now treats matching broker SOL observations as external inventory only:
no active open-position restore, no broker-recovered active position, no
journal-reassociated active position, no SOL close/sell/remediation attempt, and
no P/L inference from SOL.

Watchdog/operator status now distinguish historical manual-review rows from a
current active SOL entry blocker when authoritative external inventory exists.

Preserved truth:

- `profit_readout_real_current=unsafe_to_aggregate`
- `aggregation_allowed_real_current=false`
- `scaling_allowed=false`
- risk increase not approved
- no live broker calls
- no `--live-read-only`
- no `.env` or secrets
- no order/cancel/close/modify
- no risk/runtime/config/background changes
- no `logs/coinbase_fills.csv` writes
- no `append_coinbase_fill_row` activation

Post-merge verification should restart or run the normal operator status checks
only under existing operator procedures and confirm `open_positions` remains
bot-inventory-only while SOL/USD stays in `external_inventory.json`.

---

## P2-021C3 review — manual-review blocker remediation

**Branch:** `review/p2-021c3-manual-review-blocker-remediation`

P2-021C3 adds an offline, local, operator-approved state-normalization path for
stale `manual_review_position_open` blockers caused by proven external/staked
non-bot-tradable SOL inventory.

Live problem: Coinbase can be running with buying power and still produce no
entries because `state/coinbase/open_positions.json` contains a stale SOL/USD
manual-review blocker with `broker_close_capability_unconfirmed`.

Safety semantics:

- Do not close SOL.
- Do not sell SOL.
- Do not treat SOL as bot inventory.
- Do not infer realized P/L from SOL.
- No risk increase, notional increase, symbol expansion, leverage, or margin.
- `profit_readout_real_current=unsafe_to_aggregate`
- `aggregation_allowed_real_current=false`
- `scaling_allowed=false`

The remediation script defaults to dry-run. Apply requires
`--apply --operator-approved-external-inventory-normalization`, creates a
timestamped backup, moves proven external/staked SOL out of active bot
`open_positions`, and preserves an audit record in local external inventory.

---

## P2-021C2 (stacked on P2-021C review branch) — anti-stale manual-review blocker watchdog

**Branch:** `review/p2-021c2-anti-stale-manual-review-blocker-watchdog` (stacked on review/p2-021c-read-only-evidence-capture-bridge at dc34054; P2-021C not yet merged to main)

P2-021C2 adds a read-only, offline anti-stale watchdog (`scripts/coinbase_stale_blocker_watchdog.py`) that detects when a `manual_review_position_open` entry blocker has aged beyond a configurable threshold (default 180 minutes).

It computes blocker age, counts, severity, and distinguishes:
- True unresolved bot-owned positions (escalates to STALE_BLOCKER_REQUIRES_OPERATOR_ACTION, still blocks trading).
- External/staked/non-bot locked inventory (reported as external; never auto-closed or treated as bot inventory).
- Stale state bugs (repeated blocks with no actual open manual-review position).

The watchdog is integrated into the operator status aggregator for visibility.

**Current live problem addressed:**
The bot was running with buying power but 0 trades all day due to repeated `ENTRY_BLOCKED reason=manual_review_position_open`, with no age tracking or escalation in the main status tools.

**Preserved truth (no relaxation of gates):**
- `profit_readout_real_current=unsafe_to_aggregate`
- `aggregation_allowed_real_current=false`
- `scaling_allowed=false`
- risk increase not approved
- staked SOL remains external locked inventory, not bot inventory
- No auto-close of any position
- No auto-clear of unresolved bot-owned positions
- No live broker calls in this patch or verification

This patch does not unblock trading. It only makes indefinite silent suspension impossible by forcing explicit stale-blocker state and operator action requirements. It connects directly to the P2-021C read-only evidence capture bridge for the safe, human-approved path forward.

---

## P2-021C review — human-approved read-only evidence capture bridge

**Branch:** `review/p2-021c-read-only-evidence-capture-bridge`

P2-021C adds an offline checklist bridge for a future human-approved Coinbase
read-only capture. It does not call live broker APIs, does not execute
`--live-read-only`, does not import broker clients, does not read `.env`, and
does not write runtime state/logs.

The bridge documents the exact future order IDs, product IDs, date windows,
direct broker fields, redaction requirements, adapter input path, adapter
command, and resolver command needed to feed real captured facts into P2-021B
and P2-021A after explicit human approval.

Preserved current truth:

- `profit_readout_real_current=unsafe_to_aggregate`
- `aggregation_allowed_real_current=false`
- `scaling_allowed=false`
- risk increase not approved
- staked SOL remains external locked inventory, not bot inventory

---

## P2-021A review — profit readout direct evidence resolver

**Branch:** `review/p2-021a-profit-readout-evidence-resolver`

P2-021A adds an offline-only profit readout evidence resolver:

- `scripts/coinbase_profit_readout_evidence_resolver.py`
- direct broker evidence fixtures under `tests/fixtures/coinbase_profit_readout/`
- `tests/test_coinbase_profit_readout_evidence_resolver.py`
- `docs/PROFIT_READOUT_EVIDENCE_RESOLUTION.md`

The resolver keeps `profit_readout=unsafe_to_aggregate` unless closed bot-owned
entry+exit cycles contain direct order ids, fill/trade ids, direct fees, and
direct proceeds/filled_value for both legs.

Complete direct broker evidence can produce:

- `profit_readout=measured_broker_backed_limited`
- `aggregation_allowed=true` for the supplied closed cycles only
- `scaling_allowed=false` because risk increase remains not approved

Preserved blockers and safety:

- staked SOL remains external locked inventory, not bot inventory
- local journal P/L never unlocks aggregation
- incomplete direct evidence stays `unsafe_to_aggregate`
- no live broker calls
- no `--live-read-only`
- no `.env` or secrets
- no order/cancel/close/modify
- no runtime/risk/config/background changes
- no state/log mutation
- no `logs/coinbase_fills.csv` writes
- no `append_coinbase_fill_row` activation
- risk increase not approved

---

## P2-020A review — staked SOL external inventory semantics

**Branch:** `review/p2-020a-staked-sol-external-inventory`

New project fact from Vadim: the current SOL position shown in Coinbase is staked by the user. The bot cannot trade it or close it.

P2-020A classifies this SOL as external staked inventory / externally locked inventory rather than bot-tradable inventory.

Preserved safety state:
- SOL should be excluded from bot-tradable inventory.
- No close/remediation recommendation should be made for this SOL while it is staked.
- `profit_readout=unsafe_to_aggregate`
- `aggregation_allowed=false`
- `scaling_allowed=false`
- risk increase still not approved until P/L evidence and safe tradable-inventory logic are clean

No live broker calls, no `--live-read-only`, no `.env` reads, no order/cancel/close/modify, no runtime/risk/config/background/state/log mutations.

---

## P2-019H complete — second overnight handoff pack (GREEN docs-only)

**Branch:** `review/p2-019h-second-overnight-handoff-pack`

**Functional patch commit:** (final merge of this run)

P2-019H added `docs/SECOND_OVERNIGHT_STATUS_HANDOFF.md` and closed the second overnight autonomy run.

Records all GREEN patches executed (P2-019A–G), the two review-only branches (P2-017D and P2-018E), final state, and exact transcript locations + copy commands.

Pure GREEN docs closure.

---

## P2-019H complete — second overnight handoff pack (GREEN docs-only)

**Branch:** `review/p2-019h-second-overnight-handoff-pack`

**Functional patch commit:** (closing commit of this run)

P2-019H added `docs/SECOND_OVERNIGHT_STATUS_HANDOFF.md` and performed the final ACTIVE_HANDOFF.md update.

Records:
- 8 GREEN patches executed and self-merged (P2-019A through P2-019H)
- 2 review-only branches left untouched (P2-017D and P2-018E)
- Final state: profit_readout=unsafe_to_aggregate, risk increase not approved
- Exact transcript locations and pbcopy commands

Pure GREEN docs closure of the second overnight autonomy run.

---

## P2-019G complete — external signal layer safety runbook (GREEN docs-only)

**Branch:** `review/p2-019g-external-signal-layer-safety-runbook`

**Functional patch commit:** `e7a9bec`

P2-019G added `docs/EXTERNAL_SIGNAL_LAYER_SAFETY_GATE.md`.

Documents that external syndicated crypto/news/trend context remains disabled until broker truth and P/L evidence gate are complete. Explicit constraints, future sequence, and enforcement rules defined.

Pure GREEN docs-only.

---

## P2-019F complete — redaction and sensitive-field policy for broker payloads (GREEN)

**Branch:** `review/p2-019f-broker-payload-redaction-policy`

**Functional patch commit:** `8b2380a`

P2-019F added:
- `docs/BROKER_PAYLOAD_REDACTION_POLICY.md`
- `scripts/redact_broker_payload.py` + tests

Defines mandatory redaction rules for sensitive broker fields (account_id, secrets, long identifiers, etc.) and provides a simple offline helper.

Pure GREEN.

---

## P2-019E complete — manual SOL remediation decision tree runbook (GREEN docs-only)

**Branch:** `review/p2-019e-manual-sol-remediation-decision-tree`

**Functional patch commit:** `bb1846b`

P2-019E added `docs/SOL_MANUAL_REMEDIATION_DECISION_TREE.md`.

Documents the safe human decision flow for the unresolved SOL position, explicit prohibitions, and required evidence (direct entry + exit facts + human approval) before the blocker can be cleared.

Pure GREEN docs-only.

---

## P2-019D complete — operator daily digest generator, offline only (GREEN)

**Branch:** `review/p2-019d-offline-operator-daily-digest`

**Functional patch commit:** `0e20afc`

P2-019D added a lightweight offline daily digest:

- `scripts/operator_daily_digest.py`
- `tests/test_operator_daily_digest.py`

Produces text + JSON with current gate status and explicit safety warnings.

Pure GREEN (read-only).

---

## P2-019C complete — offline golden reconciliation regression runner (GREEN)

**Branch:** `review/p2-019c-offline-golden-reconciliation-regression-runner`

**Functional patch commit:** `4691023`

P2-019C added a single offline regression harness:

- `scripts/run_offline_reconciliation_regression.py`
- `tests/test_run_offline_reconciliation_regression.py`

Runs key checks (evidence gate, dashboard, zero-qty fixtures, malformed payloads) and reports the required summary fields with current gate status.

Pure GREEN (offline only).

---

## P2-019B complete — reconciliation JSON contract registry (GREEN)

**Branch:** `review/p2-019b-reconciliation-json-contracts`

**Functional patch commit:** `0864be5`

P2-019B added:
- `docs/RECONCILIATION_JSON_CONTRACTS.md` — stable top-level field contracts for all main reconciliation scripts
- `tests/test_reconciliation_json_contracts.py` — lightweight offline validation

The document explicitly marks P2-017D and P2-018E scripts as review-only only (not on main).

Pure GREEN (docs + offline tests).

---

## P2-019A complete — unmerged review branch audit pack (GREEN docs-only)

**Branch:** `review/p2-019a-unmerged-review-branch-audit-pack`

**Functional patch commit:** `50734e5`

P2-019A added `docs/UNMERGED_REVIEW_BRANCH_AUDIT.md`.

This document tracks YELLOW review branches that must not be merged without explicit ChatGPT review:

- review/p2-017d-coinbase-full-fill-payload-capture (f8dc271) — first live read-only capture for matched SOL trade; original transcript did not include exact required live JSON fields.
- review/p2-018e-local-review-gate-reconciliation-safety (e53b426) — review gate expansion with noisy static scanning.

The document includes:
- Why each branch is unmerged
- Exact pre-merge verification requirements
- Explicit “do not merge overnight” rule
- Expected ChatGPT review questions
- Re-assertion that profit_readout remains unsafe_to_aggregate and risk increase is not approved

This is pure GREEN docs-only work.

Verification passed: git diff --check clean, required phrases present, clean fast-forward merge to main.

---

## P2-018F complete — overnight final handoff and status pack (GREEN docs-only)

**Branch:** `review/p2-018f-overnight-handoff-pack`

**Functional patch commit:** `53db020`

P2-018F added:
- `docs/OVERNIGHT_STATUS_HANDOFF.md` (full summary of the overnight run)
- Master transcript at `/tmp/overnight_master_verification_transcript.txt`

Records all GREEN patches executed and self-merged, P2-018E left as review-only, P2-017D untouched per instructions, and final state.

Pure GREEN docs closure of the overnight autonomy run.

---

## P2-018D complete — operator reconciliation dashboard, offline only (GREEN)

**Branch:** `review/p2-018d-offline-reconciliation-dashboard`

**Functional patch commit:** `de2f9de`

P2-018D added a strictly offline one-page reconciliation dashboard:

- `scripts/coinbase_reconciliation_dashboard.py`
- `tests/test_coinbase_reconciliation_dashboard.py`

Produces clear operator output including:
- Current blocker state
- SOL status
- Fee/value availability
- Explicit "DO NOT SCALE RISK. DO NOT CLOSE AUTOMATICALLY." warning
- Next safe action

Pure GREEN (read-only, no broker/.env/writes).

---

## P2-018C complete — offline reconciliation fixture pack (GREEN)

**Branch:** `review/p2-018c-reconciliation-fixtures-and-regression-tests`

**Functional patch commit:** `8f7c680`

P2-018C added a set of offline synthetic fixtures for long-term regression safety:

- tests/fixtures/coinbase_reconciliation/
  - sol_open_missing_fee_value.json
  - sol_entry_exit_direct_facts_complete.json
  - sol_zero_qty_noise_rows.csv
  - broker_truth_unavailable.json
  - malformed_fill_payloads.json

- tests/test_coinbase_reconciliation_fixtures.py (5 tests)

These fixtures protect critical invariants:
- Zero-qty rows must never be treated as real fills
- Missing fee/filled_value keeps the evidence gate blocked
- Malformed payloads must not crash consumers
- Direct entry+exit facts are the threshold for aggregation eligibility (in test scenarios)

This is pure GREEN (fixtures + tests only).

---

## P2-018B complete — offline P/L evidence gate checker (GREEN)

**Branch:** `review/p2-018b-offline-pl-evidence-gate-checker`

**Functional patch commit:** `50b26fa`

P2-018B added a strictly offline, read-only evidence gate checker:

- `scripts/coinbase_pl_evidence_gate.py`
- `tests/test_coinbase_pl_evidence_gate.py` (7 tests)

The checker consumes a probe JSON and reports:
- `verdict`, `profit_readout`, `net_pnl_available`, `aggregation_allowed`, `scaling_allowed`
- Entry/exit fee + filled_value availability
- `zero_qty_rows_excluded` (always true per policy)
- Clear blockers and required_next_evidence

Current snapshot (as of this patch) correctly produces:
- BLOCKED + unsafe_to_aggregate
- sol_on_broker=true blocker
- aggregation_allowed=false, scaling_allowed=false

This is pure GREEN (offline only, no broker/.env/writes/runtime changes).

Verification passed: git diff --check clean, all tests green, smoke matches expected state, clean fast-forward merge.

---

## P2-018A complete — BROKER_TRUTH_AND_PL_EVIDENCE_GATE runbook (GREEN docs-only)

**Branch:** `review/p2-018a-broker-truth-evidence-gate-runbook`

**Functional patch commit:** `0253cae`

P2-018A added the authoritative evidence ladder document:

- `docs/BROKER_TRUTH_AND_PL_EVIDENCE_GATE.md`
- Defines L0–L5 evidence levels required before `profit_readout` can leave `unsafe_to_aggregate`
- Explicitly documents current state (SOL held, fee/filled_value missing, net_pnl_available=false)
- Prohibits treating zero-qty rows as fills, using avg_entry_price=0, risk scaling while blockers exist
- Requires explicit human approval for any manual remediation/close of the open SOL position
- Gate enforcement language for all future patches

This is pure docs-only (GREEN). No runtime, config, risk, order, or background behavior changed.

Verification passed: git diff --check clean, required strings present, clean fast-forward merge to main.

---

## P2-017C complete — read-only Coinbase full fill payload/proceeds field discovery for matched SOL lot

**Branch:** `review/p2-017c-coinbase-fill-payload-field-discovery`

**Functional patch commit (approved review 08bc67c, fast-forward merged to main):** `08bc67c`

P2-017C (YELLOW review branch, approved after verification and merged ff-only to main) adds a dedicated read-only discovery tool that inspects the recent_fills_sample (and any nested structures) from a prior hardened broker probe to determine exactly which direct fee, filled_value/proceeds, order linkage, and timing fields are present (or explicitly null) for the currently open matched SOL lot.

New artifacts:
- `scripts/coinbase_fill_payload_field_discovery.py`
- `tests/test_coinbase_fill_payload_field_discovery.py`

The script:
- Operates in default offline mode against an existing probe JSON only.
- Focuses on the known matched BUY trade_id = 1f10a7cb-3fe5-4cbb-b990-f74c39529fc9.
- Reports presence vs non-null status for fee and filled_value.
- Scans for candidate nested fee/value/order fields.
- Keeps `profit_readout=unsafe_to_aggregate` and `net_pnl_available=false` while direct non-null values are absent.

**Current verified readout (as of P2-017C):**
- profit_readout: unsafe_to_aggregate
- discovery_status: matched_trade_found_but_fee_and_value_missing
- broker_truth_available: true
- source_mode: offline_probe_json
- fills_inspected_count: 20
- products_seen: ['ETH/USD', 'SOL/USD']
- matched_trade_id: 1f10a7cb-3fe5-4cbb-b990-f74c39529fc9
- matched_trade_found: true
- matched_trade_product_id: SOL-USD
- matched_trade_side: BUY
- matched_trade_size: 0.0122504
- matched_trade_price: 81.63
- matched_trade_fee_present: true
- matched_trade_fee_non_null: false
- matched_trade_filled_value_present: true
- matched_trade_filled_value_non_null: false
- matched_trade_order_id_present: false
- candidate_fee_fields: ['fee']
- candidate_value_fields: ['filled_value']
- candidate_order_id_fields: []
- missing_direct_fee_count: 20
- missing_direct_filled_value_count: 20
- net_pnl_available: false
- risk increase: not approved
- next action: controlled deeper read-only fill payload capture for the matched trade_id (not scaling or closing the SOL position)

**Safety (re-asserted):**
- Default mode: zero broker calls, zero .env reads, zero file mutations.
- No append_coinbase_fill_row, no logs/coinbase_fills.csv writes.
- No strategy/risk/sizing/config/runtime/LaunchAgent changes.
- Optional --live-read-only mode (if ever implemented) is strictly opt-in and never used in verification.

All verification commands passed using the pre-existing hardened probe JSON only. No --live-read-only during this patch. Merged to main after explicit approval.

---

## P2-017B complete — read-only Coinbase fill/position lifecycle reconciliation report

## P2-017B complete — read-only Coinbase fill/position lifecycle reconciliation report

**Branch:** `review/p2-017b-coinbase-fill-position-lifecycle-reconciliation`

**Functional patch commit (approved review e11ac84, fast-forward merged to main):** `e11ac84`

P2-017B (YELLOW review branch, approved after verification and merged ff-only to main) adds a focused read-only lifecycle report that consumes a hardened live broker probe JSON and answers whether recent fills in the broker sample can explain the currently held SOL position reported by the exchange.

New artifacts:
- `scripts/coinbase_fill_position_lifecycle_reconciliation.py`
- `tests/test_coinbase_fill_position_lifecycle_reconciliation.py`

The report:
- Parses open_positions_on_broker and recent_fills_sample from the probe.
- Normalizes SOL-USD ↔ SOL/USD product IDs.
- Detects exact/near-exact size match between current broker SOL long and a recent BUY fill.
- Emits only clearly labeled **provisional estimates** (gross_cost = size × price for the matched BUY; gross_unrealized_pnl = current_market_value − gross_cost).
- Explicitly reports `fees_available=false`, `filled_value_available=false`, `net_pnl_available=false` when those fields are null/missing in the sample.
- Keeps `profit_readout=unsafe_to_aggregate` and `verdict=BLOCKED` (SOL still held on broker).
- Excludes zero-qty journal rows by design (they are never treated as real fills).

**Current verified readout (from hardened live probe /tmp/coinbase_live_probe_hardened_current.json as of P2-017B):**
- verdict: BLOCKED
- profit_readout: unsafe_to_aggregate
- broker_truth_available: true
- SOL held on broker: true
- current_sol_qty: 0.0122504
- current_sol_market_value: 1.0134755
- current_sol_price: 82.715
- likely_current_sol_entry_trade_id: 1f10a7cb-3fe5-4cbb-b990-f74c39529fc9
- likely_current_sol_entry_size: 0.0122504
- likely_current_sol_entry_price: 81.63
- likely_current_sol_entry_gross_cost_estimate: 1.000000152
- current_sol_gross_unrealized_pnl_estimate: 0.013475348000000054
- fees_available_for_current_sol_entry: false
- filled_value_available_for_current_sol_entry: false
- net_pnl_available: false
- recent_sol_fills_count: 10
- recent_eth_fills_count: 10
- recent_fills_missing_fee_count: 20
- recent_fills_missing_filled_value_count: 20
- reconciliation_status: current_sol_likely_matched_to_recent_buy_but_pnl_unsafe
- risk increase: not approved
- next action: direct per-fill fee + filled_value/proceeds reconciliation (not scaling or closing the SOL position)

**Safety (re-asserted):**
- Zero broker calls, zero .env reads, zero file mutations in the new script and tests.
- No append_coinbase_fill_row, no logs/coinbase_fills.csv writes.
- No strategy/risk/sizing/config/runtime/LaunchAgent changes.

All verification commands passed using the pre-existing hardened probe JSON only. No --live-read-only during this patch. Merged to main after explicit approval.

---

## P2-017A complete — Coinbase live broker-truth probe schema hardening + read-only reconciliation summary

## P2-017A complete — Coinbase live broker-truth probe schema hardening + read-only reconciliation summary

**Branch:** `review/p2-017a-coinbase-broker-truth-schema-and-summary`

**Functional patch commit (approved review 805ddfe, fast-forward merged to main):** `805ddfe`

P2-017A (YELLOW review branch, approved after verification and merged ff-only to main) hardens the live broker reconciliation probe JSON contract so every output path (default and --live-read-only) explicitly includes:
- live_read_only, broker_calls_made, broker_read_successful (booleans)
- broker_error_type, credential_status
- sol_on_broker / eth_on_broker (true/false/null with unknown-state semantics)
- open_orders, recent_fills_sample, open_positions_on_broker
- Full required top-level keys for downstream consumers.

Added new pure read-only summarizer:
- `scripts/coinbase_broker_truth_summary.py`
- Consumes prior probe JSON + local state/closed_positions + runtime/heartbeat + journal (safe columns only)
- Never calls broker, never reads .env, never mutates files
- Gracefully handles old probe JSONs missing the new booleans (reports schema_missing_fields)
- Produces reconciliation_status, broker_truth_available, recommended_next_action, zero-qty journal counts, etc.

**Current verified readout (from live probe + local state as of P2-017A):**
- build momentum: positive
- trading/profit readout: unsafe_to_aggregate
- SOL held on broker: true (per live read-only probe; conflicts with local dropped/re-associated/unconfirmed evidence)
- open orders: 0
- recent fills sample: 20
- risk increase: not approved
- next action: reconciliation (not strategy/risk scaling or sizing changes)
- broker close capability for the open SOL position remains unconfirmed
- local_open_positions_count: 1
- local_open_position_symbols includes SOL/USD
- local_journal_recent_zero_qty_rows_count: 51

Tests added:
- tests/test_coinbase_live_broker_reconciliation_probe_schema.py
- tests/test_coinbase_broker_truth_summary.py

All verification commands (py_compile, pytest subsets, git diff --check, default probe --json, summary using pre-existing /tmp probe JSON only) passed on review branch. No --live-read-only run in this patch. No new broker calls. Merged to main after explicit approval; no self-merge.

**Safety invariants (re-asserted):**
- No orders, cancels, closes, modifications
- No writes to logs/coinbase_fills.csv or append_coinbase_fill_row
- No mutation of state/coinbase/*.json or runtime
- No LaunchAgent / background / runtime config changes
- No secrets printed or committed
- Default probe path: zero broker calls
- Summary: zero network, zero .env, zero writes

**Next after P2-017A:** Continue reconciliation proof work toward direct sell proceeds + per-fill fees + stable trade_id availability before any fill logger activation or risk scaling. SOL broker-held blocker remains the gating item. Profit readout stays unsafe_to_aggregate until direct broker facts for exits are proven.

---

## P2-016A complete — Grok execution protocol and external signal context plan

## P2-016A complete — Grok execution protocol and external signal context plan

Functional patch commit: `061fabc`

P2-016A added durable project docs to reduce copy/paste overhead and preserve future roadmap discipline:

* `docs/GROK_EXECUTION_PROTOCOL.md`

  * defines Controlled Autonomy workflow for Grok
  * standardizes branch, test, commit, merge, handoff, and transcript expectations
  * allows self-merge for low-risk docs/tests/read-only diagnostic work after verification
  * preserves hard blocks around orders, risk, sizing, runtime, LaunchAgents, and strategy changes

* `docs/EXTERNAL_SIGNAL_CONTEXT_PLAN.md`

  * preserves future syndicated crypto/news/trend context layer
  * target sources include CoinGecko, CoinDesk RSS/news, Financial Modeling Prep crypto news, LunarCrush, and similar reputable feeds
  * layer remains advisory-only until broker reconciliation and direct P/L truth are solid
  * no direct buy/sell triggers, sizing/risk/cap changes, or strategy overrides
  * intended sequence: source registry → read-only collector → context signal aggregator → weak watchlist/skip/observe input after validation

Safety / scope:

* docs-only functional patch
* no runtime/config/order/risk/strategy changes
* no broker API calls
* no file/log/journal/state mutation outside docs
* no fill logger writes
* no leverage, margin, futures, perps, options, commodities, GOLD/SILVER/XAU/XAG enabled

Profit / momentum readout:

* build momentum: strong positive
* process velocity: improved via Controlled Autonomy docs
* trading/profit readout: unsafe-to-aggregate until successful broker truth and direct fill/proceeds/fees reconciliation are proven

## P2-015B complete — Coinbase live probe adapter compatibility and unknown-state semantics

Functional patch commit: `c9d8f05`

P2-015B fixed the Coinbase live broker reconciliation probe after P2-015A exposed a broker adapter compatibility issue:

* removed incorrect `dry_run=True` constructor usage for `BrokerCoinbase`
* classified broker adapter errors separately from actual broker truth
* preserved explicit `--live-read-only` gating
* preserved default zero-broker-call behavior
* corrected unknown-state semantics:

  * if no successful broker read occurs, `sol_on_broker` is `null`, not `false`
  * if no successful broker read occurs, `eth_on_broker` is `null`, not `false`
  * broker holdings are not reported as proven false unless direct broker data was successfully fetched
* added/updated tests covering adapter error and unknown-state behavior

Current default result:

* `verdict`: `BLOCKED`
* `profit_readout`: `unsafe_to_aggregate`
* `live_read_only`: `false`
* `broker_calls_made`: `false`
* `sol_on_broker`: `null`
* `eth_on_broker`: `null`

Safety / scope:

* no runtime/config/order/risk/strategy files changed
* no default broker/API calls
* no order placement/cancel/close/modify calls
* no file mutation calls in production script
* no journal/state/runtime/log writes
* no `logs/coinbase_fills.csv` writes
* no `append_coinbase_fill_row` production call
* no `.replace()` call in production script per conservative safety gate
* no leverage, margin, futures, perps, options, commodities, GOLD/SILVER/XAU/XAG enabled

Profit / momentum readout:

* build momentum: strong positive
* trading/profit readout: unsafe-to-aggregate
* broker truth still requires a successful `--live-read-only` run with valid read-only Coinbase credentials

## P2-015A complete — read-only Coinbase live broker reconciliation probe

Functional patch commit: `2f2ab7a`

P2-015A added an explicit opt-in Coinbase live broker reconciliation probe:

* new script: `scripts/coinbase_live_broker_reconciliation_probe.py`
* new tests: `tests/test_coinbase_live_broker_reconciliation_probe.py`
* default mode performs ZERO broker/API calls
* live broker reads require explicit `--live-read-only`
* `--json` emits valid machine-readable output in both default and live-read-only paths
* default JSON includes `live_read_only=false` and `broker_calls_made=false`
* probe is designed to compare direct broker account/position/order/fill truth against local SOL/USD orphan/reconciliation evidence

Current default result:

* `verdict`: `BLOCKED`
* `profit_readout`: `unsafe_to_aggregate`
* `live_read_only`: `false`
* `broker_calls_made`: `false`
* next action: re-run with `--live-read-only` after confirming read-only Coinbase API credentials

Safety / scope:

* no runtime/config/order/risk/strategy files changed
* no default broker/API calls
* no order placement/cancel/close/modify calls
* no file mutation calls in production script
* no journal/state/runtime/log writes
* no `logs/coinbase_fills.csv` writes
* no `append_coinbase_fill_row` production call
* no `.replace()` call in production script per conservative safety gate
* no leverage, margin, futures, perps, options, commodities, GOLD/SILVER/XAU/XAG enabled

Profit / momentum readout:

* build momentum: strong positive
* trading/profit readout: unsafe-to-aggregate
* no risk/cap/aggressiveness increase is justified until direct broker close/fill/proceeds/fees truth is proven

## P2-014E complete — read-only Coinbase operator status aggregator

Functional patch commit: `662dc1d`

P2-014E added a single read-only Coinbase operator status aggregator:

- new script: `scripts/coinbase_operator_status.py`
- new tests: `tests/test_coinbase_operator_status.py`
- aggregates local fill/proceeds/P&L reconciliation status
- aggregates open/orphan position status
- aggregates prediction/price-data coverage status where available
- emits text and machine-readable `--json`
- provides top-level `verdict`, `profit_readout`, blockers, and next recommended action

Current local operator result:
- `verdict`: `BLOCKED`
- `profit_readout`: `unsafe_to_aggregate`
- `sol_blocker_detected`: `true`
- blocker count: `8`
- next action: urgently investigate and resolve SOL/USD broker-close status before aggregating P/L or increasing risk

Safety / scope:
- no runtime/config/order/risk/strategy files changed
- no broker API calls added
- no `.env` reads added
- no network calls added
- no file mutation calls in production script
- no fill logger writes enabled
- no `logs/coinbase_fills.csv` writes
- no `append_coinbase_fill_row` production call
- no leverage, margin, futures, perps, options, commodities, GOLD/SILVER/XAU/XAG enabled

Profit / momentum readout:
- build momentum: strong positive
- trading/profit readout: unsafe-to-aggregate
- no risk/cap/aggressiveness increase is justified

## P2-014D complete — read-only open/orphan Coinbase position status report

Functional patch commit: `39a3408`

P2-014D added a read-only operator report for Coinbase open/orphan position status:
- current/open position evidence
- dropped/re-associated/orphan evidence
- broker close capability status
- manual-review requirements
- profit/readout blockers
- machine-readable `--json` output

Current report result:
- SOL/USD unresolved/re-associated broker-close blocker detected from local journal evidence
- broker close capability remains unconfirmed unless direct later evidence proves otherwise
- realized P/L remains unsafe-to-aggregate while open/orphan status is unresolved
- report is intentionally conservative and advisory-only

Safety / scope:
- no runtime/config/order/risk/strategy files changed
- no broker API calls added
- no `.env` reads added
- no fill logger writes enabled
- no `logs/coinbase_fills.csv` changes
- no `append_coinbase_fill_row` production call
- no leverage, margin, futures, perps, options, commodities, GOLD/SILVER/XAU/XAG enabled

Profit / momentum readout:
- build momentum: strong positive
- trading/profit readout: unsafe-to-aggregate
- no risk/cap/aggressiveness increase is justified

## P2-014C complete — local review-gate automation for Grok/Codex patches

Functional patch commit: `1e66b94`

P2-014C added reusable local review-gate scaffolding to reduce copy/paste, false positives, and human verification errors during Grok/Codex buildout.

Changed files:
- `scripts/local_review_gate.py`
- `tests/test_local_review_gate.py`
- `docs/GROK_CODEX_REVIEW_GATE.md`

Purpose:
- verify review branches with one command
- check expected changed files
- block protected runtime/config/order/risk/log files
- require explicit permission for `docs/ACTIVE_HANDOFF.md` changes
- avoid false positives where `append_coinbase_fill_row` appears only in protective tests
- block production fill logger writes/references unless explicitly approved
- produce compact final reports for ChatGPT merge review

Safety / scope:
- no live trading behavior changed
- no strategy/order/risk/symbol/cap/config/runtime behavior changed
- no broker API calls added
- no `.env` reads added
- no fill logger writes enabled
- `logs/coinbase_fills.csv` remains protected
- no leverage, margin, futures, perps, options, commodities, GOLD/SILVER/XAU/XAG enabled

Profit / momentum readout:
- build momentum: strong positive
- trading/profit readout: still unsafe-to-aggregate
- no risk/cap/aggressiveness increase is justified


## P2-014B complete — read-only fill/proceeds/P&L reconciliation readout

Functional patch commit: `1eb2007`

P2-014B improved `scripts/coinbase_fill_proceeds_reconciliation_report.py` and its tests so the local reconciliation report now clearly separates:
- direct broker facts available from local rows
- locally derived values
- unsafe/missing values
- matched-pair summaries
- open/unresolved position evidence
- SOL/USD broker-close blocker evidence

Verified:
- `tests/test_coinbase_fill_proceeds_reconciliation_report.py`: 16 passed
- `tests/test_coinbase_fill_logging_contract_check.py`: 10 passed
- `tests/test_coinbase_entry_exit_capture.py`: 5 passed
- report smoke passed
- patch remained read-only/local CSV inspection only

Current report result:
- direct order/client-order coverage exists
- direct sell proceeds are not available locally
- direct fees are not available locally in enough form for immutable P/L aggregation
- no paired cycle has both actual buy cost and direct sell proceeds locally available
- realized P/L remains unavailable / unsafe-to-aggregate
- SOL/USD open/re-associated blocker remains active
- broker close capability remains unconfirmed

Safety / scope:
- no runtime/config/order/risk/strategy files changed
- no fill logger writes enabled
- no `append_coinbase_fill_row` production call
- no `.env`, `logs/coinbase_fills.csv`, LaunchAgent, state, runtime, or broker API behavior changed
- no leverage, margin, futures, perps, options, commodities, GOLD/SILVER/XAU/XAG enabled

Profit / momentum readout:
- build momentum: positive
- trading/profit readout: unsafe-to-aggregate
- no risk/cap/aggressiveness increase is justified


## P2-014A — ACTIVE_HANDOFF live status preservation + P2-014 preflight (docs-only)

Functional patch commit (latest complete): `e90e678` (P2-013C: read-only local price data coverage diagnostics + targeted regressions)

P2-014A (this patch): docs-only update to preserve latest live Coinbase operational/reconciliation blocker status in ACTIVE_HANDOFF.md. No runtime strategy, config, risk, order, .env, LaunchAgent, or logging behavior changes of any kind. This patch exists solely to improve operational/profit truth by documenting grim reality accurately.

**Preserved live status (as of latest local auto-sync; treat strictly as operational/reconciliation blocker, NOT strategy success):**
- Coinbase equity around $45.73
- SOL/USD open/re-associated (bot-origin position)
- broker close capability unconfirmed
- close failures logged (position may have been dropped from tracking after 3 failed close attempts)
- latest functional patch remains e90e678
- no risk/aggressiveness increase justified

P2-013C diagnostic results (retained for continuity):
- outcome evaluator remains read-only
- price data status remains read-only
- local run still reports `Evaluable telemetry rows: 0`
- hit rates remain non-actionable until dense local price coverage exists
- strategy tuning remains premature

Safety / scope (unchanged):
- no strategy/order/risk/symbol/cap/config/runtime changes
- no leverage, margin, futures, perps, options, commodities, GOLD/SILVER/XAU/XAG order placement enabled
- fill logger remains blocked
- `append_coinbase_fill_row` is not called by production code
- no `.env`, `logs/`, or `coinbase_fills.csv` changes
- profit/readout remains required in every status update and handoff

Profit / momentum readout:
- last verified realized P&L remains `-$0.0358` unless newer journal/status output proves otherwise
- current outcome scoring is still not actionable because evaluable telemetry rows remain `0`
- **current profit readout is unsafe-to-aggregate until direct fill/proceeds/fees reconciliation is proven** (see P2-014 preflight below)
- no risk/cap/aggressiveness increase is justified

<!-- This file is the shared context layer between Claude (advisor) and ChatGPT/Copilot (executor). -->
<!-- Update this file after every session. Both AIs read from here. Do not let it go stale. -->

**Last updated:** 2026-06-03 13:14 — automated sync; Coinbase equity $51.42, 0 bot-tracked positions, SOL/USD external inventory, 0 proposals/scan, no errors. (Prior:) P2-014C complete; added local review-gate automation for Grok/Codex patches to reduce copy/paste, false positives, and human verification error. Latest functional patch commit 1e66b94. No strategy/order/risk/symbol/cap/config/runtime behavior changed. Profit readout remains unsafe-to-aggregate until direct fill/proceeds/fees and open-position status are proven.
**Updated by:** Grok (per P2-014A ritual)
**Repo:** https://github.com/vadim-koenen/alpaca-autonomous-microbot.git  
**Branch:** review/p2-014a-coinbase-live-status-and-reconciliation-preflight

## P2-014 Preflight — Profit Readout Safety (reconciliation blocker)

**Current profit readout (realized P&L, outcome scoring, hit rates) is unsafe-to-aggregate** until direct fill/proceeds/fees reconciliation is proven from broker data for entry and exit legs.

This is especially critical given the open SOL/USD position (broker close capability unconfirmed after logged close failures; position possibly dropped from tracking).

Existing reconciliation modules/scripts/tests already exist and should be reused for the next step:
- `coinbase_order_fills_reconciliation.py` (P2-011F) — pure `reconcile_order_with_fills()` returning `ReconciliationResult` with `direct_broker_fact` / `locally_derived` / `unavailable` classifications for proceeds, fees, filled_value, logger_ready gate, raw payloads preserved, blocking_reasons.
- `coinbase_entry_exit_capture.py` (P2-011G) — inert `capture_leg` / `capture_entry` / `capture_exit` wrappers over the above (never called from live paths in current code).
- `scripts/coinbase_fill_proceeds_reconciliation_report.py` + `tests/test_coinbase_fill_proceeds_reconciliation_report.py`
- `tests/test_coinbase_fill_logging_contract_check.py`
- `tests/test_coinbase_entry_exit_capture.py`

**Next patch should focus on read-only reconciliation reporting**: exercise the above modules against the current journal (and any available local broker history/fixtures for the open SOL position and recent exits) to determine whether stable per-fill trade_ids, actual sell proceeds on exits, and per-fill fees are recoverable. Produce advisory report only. No network calls in tests, no writes, no append_coinbase_fill_row, no live behavior changes, no config/risk/strategy modifications.

Until that proof exists, all P&L, expectancy, and "profit" numbers must be treated as provisional/unsafe-to-aggregate. The SOL position with unconfirmed broker close is an explicit reconciliation blocker.

No risk/aggressiveness increase or strategy changes are justified while this state persists.

---

## 1. Project Identity

Two bots, one repo, running on a Mac under launchd.

| Bot | Exchange | Status | Config file |
|---|---|---|---|
| **Coinbase bot** | Coinbase Advanced | ✅ PRIMARY — active optimization | `config_coinbase_crypto.yaml` |
| **Alpaca bot** | Alpaca | ⏸ SECONDARY — on hold | `config.yaml` |

**Coinbase bot** is the active focus. Running $1 controlled exploration across BTC/USD, ETH/USD, SOL/USD. All current patches (P2-001x through P2-002) are Coinbase-only.

**Alpaca bot** is running but on hold — constant stale quote skips during off-hours, zero trades placed, not current priority. Will revisit when equity market hours align or when Coinbase work reaches a stable plateau.

Note: repo name (`alpaca-autonomous-microbot`) reflects the project's origin. Both bots live here.

---

## 2. Hard Rules (both AIs must respect these always)

```
DO NOT:
  - restart bots
  - run launchctl
  - run live mode manually
  - place / cancel / modify orders
  - edit .env
  - read or print secrets or API keys
  - touch broker_*.py, order_manager.py, risk_manager.py, main.py
  - touch launchd/, state/, runtime files
  - change config_coinbase_crypto.yaml or config.yaml risk caps
  - raise notional, exposure caps, max open positions, or daily loss cap
  - connect prediction/ML outputs to live trading decisions
  - approve paper-to-live model promotion

ALWAYS:
  - Advisory/read-only patches are Class 1 (safest)
  - Live behavior changes are Class 2+ (require explicit approval)
  - New report/script files are always Class 1
  - Tests must accompany new scripts
  - Every new file must have ADVISORY ONLY comment block at top
```

---

## 3. Current Live State

| Item | Value |
|---|---|
| Coinbase equity | $56.23 |
| Coinbase status | RUNNING_BY_LAUNCHD (last loop 2026-06-03 16:03 UTC, status=running, halt=none) |
| Alpaca equity | $10.00 |
| Alpaca status | RUNNING_BY_LAUNCHD (last loop 2026-05-31 08:23 CDT, outside market hours) |
| Kill switch | INACTIVE (trading allowed) |
| Open positions | 0 bot-tracked (SOL/USD seen at broker, classified external/staked/non-bot inventory; not rehydrated) |
| Last Coinbase trade | 2026-05-25T12:06:37 UTC (ALGO/USD SKIPPED — max trades/day) |
| Last Coinbase exit | 2026-06-03T01:31:01 UTC (BTC/USD, max-hold, -0.93%) |
| Trades today | 0 |
| Current regime | downtrend (0 proposals/scan; bot correctly sitting out) |
| Live track record | 48 completed exits, 1 win / 47 loss (2.1% win rate), profit factor 0.003, net ≈ -$1.09 |
| Capital-add gates | 1/5 passing (only Gate 1 trade-count met) |

---

## 4. Coinbase Controlled Exploration Config (do not change)

```yaml
controlled_exploration:
  enabled: true
  approved_symbols: [BTC/USD, ETH/USD, SOL/USD]
  max_single_trade_notional_usd: 1.00
  max_total_exploration_exposure_usd: 6.00
  max_round_trips_per_day: 12
  max_entries_per_symbol_per_day: 4
  per_symbol_cooldown_minutes: 30
  daily_stop_loss_usd: 3.00
  max_consecutive_losses: 3
  max_open_positions: 2

fee_model:
  maker_fee_pct: 0.006   # 0.60%
  taker_fee_pct: 0.012   # 1.20%
  # Round-trip taker break-even: 2.40% gross move required
```

---

## 5. Completed Milestones

| ID | Name | Status |
|---|---|---|
| P1-001 | Shadow learner schema/scaffold | DONE |
| P1-002 | Shadow learner log/state ingestion | DONE |
| P1-003/004 | Outcome labeling scaffold | DONE |
| P1-004B/F | Price history + retrospective/prospective samples | DONE / advisory |
| P1-006 | News/trend context scaffold | DONE |
| P1-006C | Prospective diagnostics — no deployable edge found | DONE |
| P1-006D | Scoring reconciliation | DONE / committed |
| P2-001 | Controlled Coinbase exploration | DONE / live |
| P2-001B | State-aware LRU rotation (BTC→ETH→SOL proven) | DONE / committed `adbebf4` |
| P2-001C | Coinbase exploration fee/performance report | DONE / committed `0a6c82c` |
| P2-001D | Controlled exploration status accuracy fix | DONE / committed `e10a722` |
| P2-001E | Coinbase exit quality report | DONE / committed `535298c` |
| P2-001F | Coinbase maker order audit | DONE / committed `f835e74` |
| P2-001G | Patch completion automation | DONE / committed `5fcca5c` |
| P2-001H | Coinbase live-only performance re-baseline | DONE / committed `9ac606a` |
| P2-001I | Handoff automation daemon | DONE / committed `0028733` |
| P2-002 | Review and commit advisory prediction features | DONE / committed `012ab07` |
| P2-003 | Intra-hold price path logger | DONE / committed `bd89891` |
| P2-004 | Dynamic equity-based Coinbase sizing groundwork | DONE / committed `4903014` |
| P2-005 | Coinbase Price-Path MFE/MAE Analyzer | DONE / committed `7ddf6d7` |
| P2-006 | Coinbase Sizing / Execution / Profitability Reconciliation Report | DONE / committed `49135bc` |
| P2-007 | Coinbase Fill / Proceeds Reconciliation Report | DONE / committed `1b6ce77` |
| P2-008 | Coinbase Immutable Fill Logging Contract Spec | DONE / committed `fbe3867` |
| P2-009 | Open-Source Bot Plumbing Survey | DONE / committed `1b49c11` |
| P2-010 | Coinbase Fill Logging Implementation Discovery | DONE / committed `0bc4d87` |
| P2-010B | Stabilize Coinbase Fill Logging Discovery Report | DONE / committed `d1de493` |
| P2-010C | Remove Volatile Skipped Paths From Discovery Report | DONE / committed `3a7a953` |
| P2-011A | Coinbase Fill Logger Scaffold | DONE / committed `818ded7` |
| P2-011B | Coinbase Fill Response Discovery | DONE / committed `90f68fa` |
| P2-011C | Coinbase Raw Payload Fixture Proof | DONE / committed `081c04b` |
| P2-011D-alt | Coinbase Fills Payload Discovery | DONE / committed `0b2a629` |
| P2-011E | Coinbase Historical Fills Wrapper Proof | DONE / committed `af1eb87` |

---

## 6. Git State (as of last update)

```
Latest functional patch commit: `d67c37c`
Commit hashes for handoff updates should be verified with `git log`; this file intentionally avoids storing a self-referential handoff commit hash.
Clean: no dirty tracked files (except handoff update)

Recent commits:
  90f68fa P2-011B: Coinbase Fill Response Discovery
  818ded7 P2-011A: Coinbase Fill Logger Scaffold
  3a7a953 P2-010C: Remove Volatile Skipped Paths From Discovery Report
  d1de493 P2-010B: Stabilize Coinbase Fill Logging Discovery Report
  0bc4d87 P2-010: Coinbase Fill Logging Implementation Discovery
  1b49c11 P2-009: Open-Source Bot Plumbing Survey
  fbe3867 P2-008: Coinbase Immutable Fill Logging Contract Spec
  1b6ce77 P2-007: Coinbase Fill / Proceeds Reconciliation Report
  49135bc P2-006: Coinbase Sizing / Execution / Profitability Reconciliation Report
```

P2-002 advisory prediction features are committed (`012ab07`); do not connect to live decisions without explicit approval.

---

## 7. Current Performance Diagnosis

From confirmed live trade data (6 completed cycles):

| Cycle | Gross | Fee | Net |
|---|---|---|---|
| BTC/USD #1 | -$0.0074 | -$0.0120 | **-$0.0193** |
| ETH/USD #1 | -$0.0046 | -$0.0120 | **-$0.0166** |
| SOL/USD #1 | +$0.0150 | -$0.0121 | **+$0.0029** ✓ |
| BTC/USD #2 | +$0.0039 | -$0.0120 | **-$0.0081** |
| ETH/USD #2 | -$0.0050 | -$0.0120 | **-$0.0169** |
| SOL/USD #2 | -$0.0082 | -$0.0120 | **-$0.0202** |

- **All 26 journal exits are max-hold exits** — SL/TP thresholds have never triggered
- Fee per round trip ≈ $0.012 at $1 notional
- Break-even requires 2.4% gross move in 90 min; actual avg is ~0.1–0.5%
- 1 of 6 net positive. Current expectancy is negative.
- Root cause: fee drag + forced time exits, not execution failure

---

## 8. Active Patch Queue

### IN PROGRESS
**P2-011H completed the narrow opt-in dry-run Coinbase capture seam proof in the actual entry/exit flow. Key finding: `position_manager.py` now has a disabled-by-default `dry_run_capture=False` seam that can call the inert capture/reconciliation helpers only when explicitly enabled, storing results in memory via `_dry_run_captures` and performing no writes. Dedicated tests prove default constructor compatibility, default-disabled behavior, opt-in entry/exit capture behavior, no `append_coinbase_fill_row` calls, no logger writes, and logger readiness remaining blocked when broker facts are missing. Logger hook remains blocked. Next safe patch: P2-011I — controlled dry-run broker-data capture/probe proof to exercise the seam with real or captured broker payloads, still no writes. Do not tune TP/SL, hold time, notional size, symbols, predictions, risk caps, config, runtime, or live strategy until actual fills/proceeds/fees are captured and reconciled.**

### QUEUED (blocked — data + explicit approval required)
- **SL/TP/hold-time tuning** — Class 2; use P2-001E exit-quality and P2-005 MFE/MAE reports only after ≥20 price-path samples, ~2+ weeks of P2-003 data, and explicit human approval

### DO NOT START YET
- Any TP/SL/hold-time config changes
- Notional increase
- P2-003 entry quality gate
- Connecting P2-002 features to live decisions
- Alpaca equity work (after-hours stale quotes are expected, not a bug)

---

## 9. How to Update This File

**After Claude session:** Claude updates sections 3, 6, 7, 8 based on what was reviewed.  
**After Copilot execution:** Update section 8 (mark patch done, add new queued item).  
**After each git push:** Update section 6 with new HEAD commit.  

Keep this file committed and pushed. Both AIs reference it at session start.

---

## 10. Session Start Checklist

For any AI beginning a session on this project:

```bash
cd /Users/vadimkoenen/Documents/Claude/Projects/Investing/alpaca-autonomous-microbot

# 1. Confirm repo state
git status --short
git log --oneline -5

# 2. Confirm bots running
bash scripts/status.sh

# 3. Confirm exploration state
CONFIG_FILE=config_coinbase_crypto.yaml python3 scripts/controlled_exploration_status.py

# 4. Read this file
cat docs/ACTIVE_HANDOFF.md
```

Do not recommend or execute anything until all four commands have been run and reviewed.

---

## 11. Automated Status Log
<!-- Appended automatically by Claude scheduled tasks. Do not edit manually. -->
<!-- Format: YYYY-MM-DD HH:MM | equity=$X | positions=X | regime=X | errors=X | head=commit -->

- 2026-05-29 20:30 | equity=$40.94 | positions=0 | regime=dead_chop | errors=0 | head=adbebf4
- 2026-05-30 02:53 | equity=$40.94 | positions=0 | regime=dead_chop | errors=0 | head=8bbaae0 | P2-001D committed+pushed, auto-sync installed, P2-001E now active
- 2026-05-30 03:35 UTC | head=535298c | P2-001E committed+pushed; Class 2 SL/TP/hold tuning awaiting explicit approval
- 2026-05-30 03:53 UTC | head=f835e74 | P2-001F committed+pushed; 6/6 entries likely passive-priced; actual maker/taker fee flags still unproven
- 2026-05-30 03:56 UTC | head=f835e74 | P2-001F committed+pushed; 6/6 entries likely passive-priced; actual maker/taker fee flags still unproven
- 2026-05-30 04:05 UTC | head=5fcca5c | P2-001G complete; Automates ACTIVE_HANDOFF updates, handoff commits, pushes, and raw GitHub verification
- 2026-05-30 04:12 UTC | head=9ac606a | P2-001H complete; Re-baselines Coinbase exploration using live-only BTC/ETH/SOL data excluding dry_run, ALGO, probe, and recovered noise
- 2026-05-30 04:23 UTC | head=0028733 | P2-001I complete; Adds polling daemon to automate ACTIVE_HANDOFF updates
- 2026-05-30 12:41 | equity=$40.94 | positions=0 | regime=dead_chop | errors=0 | head=b4da00f
- 2026-05-30 12:41 UTC | head=012ab07 | P2-002 complete; Shadow learner features reviewed for future-data leakage and committed
- 2026-05-30 12:52 UTC | head=bd89891 | P2-003 complete; Adds read-only Coinbase price path logger to collect intra-hold snapshots for true MFE/MAE analysis before Class 2 tuning
- 2026-05-30 14:28 UTC | head=4903014 | P2-004 complete; Adds Coinbase-only dynamic equity sizing framework while preserving hard $1 trade cap, exposure cap, stop-loss cap, and existing risk gates
- 2026-05-30 14:44 UTC | head=7ddf6d7 | P2-005 complete; Adds advisory-only Coinbase price-path MFE/MAE analyzer, tests, and runbook to evaluate intra-hold excursions before any Class 2 tuning.
- 2026-05-30 18:26 UTC | head=49135bc | P2-006 complete; Adds advisory-only Coinbase sizing/execution reconciliation report, tests, and runbook. The report explains fixed-cap controlled exploration, legacy $0.50 vs $1.00 sizing, missing sell-fill data, fee drag, max-hold exits, and why P/L must remain unavailable when sell proceeds are not present.
- 2026-05-30 19:15 UTC | head=1b6ce77 | P2-007 complete; Adds advisory-only Coinbase fill/proceeds reconciliation report, tests, and runbook. Confirms 37 exit/sell rows, zero direct sell proceeds, zero fee rows, zero reconstructable gross/net P/L pairs; realized P/L must remain n/a until immutable fill/proceeds/fee logging is fixed.
- 2026-05-30 19:35 UTC | head=fbe3867 | P2-008 complete; Adds Coinbase immutable fill logging contract spec, read-only contract checker, and tests. Confirms `logs/coinbase_fills.csv` is missing and realized P/L must remain n/a until actual fill/proceeds/fee logging is implemented safely.
- 2026-05-30 19:45 UTC | head=1b49c11 | P2-009 complete; Adds open-source bot plumbing survey, read-only reference checker, and tests. Integrates Freqtrade, Hummingbot, Jesse, OctoBot, and CCXT as architecture references only. No external code copied, no installs, no live behavior changes, no strategy tuning. Next patch should be P2-010 read-only Coinbase fill logging implementation discovery.
- 2026-05-30 19:50 UTC | head=0bc4d87 | P2-010 complete; Adds read-only Coinbase fill logging implementation discovery, generated report, scanner, and tests. Identifies broker/status/journal seams for future append-only fill logging. No live behavior changes, no external API calls, no config/risk/state/runtime/launchd changes, and no strategy tuning.
- 2026-05-30 19:55 UTC | head=d1de493 | P2-010B complete; Stabilizes Coinbase fill logging discovery report generation and tests deterministic regeneration. No live behavior changes, no external API calls, no config/risk/state/runtime/launchd changes, and no strategy tuning.
- 2026-05-30 20:00 UTC | head=3a7a953 | P2-010C complete; Removes volatile `.git/` skipped-path preview entries from the Coinbase fill logging discovery report and confirms deterministic regeneration. No live behavior changes, no external API calls, no config/risk/state/runtime/launchd changes, and no strategy tuning.
- 2026-05-30 23:06 UTC | head=818ded7 | P2-011A complete; Adds tested append-only Coinbase fill/proceeds/fee logger scaffold, deterministic CSV schema, append/header safety tests, raw payload serialization tests, and implementation plan. No broker/journal hook, no live behavior changes, no external API calls, no config/risk/state/runtime/launchd changes, and no strategy tuning.
- 2026-05-30 23:26 UTC | head=90f68fa | P2-011B complete; Adds read-only Coinbase fill response discovery script, generated report, and tests. Confirms logger hook remains blocked because direct sell proceeds and actual exit-leg fees are not yet proven from current broker response handling. No broker/journal hook, no live behavior changes, no external API calls, no config/risk/state/runtime/launchd changes, and no strategy tuning.
- 2026-05-31 03:34 UTC | head=081c04b | P2-011C complete; Added raw Coinbase order/status + fills fixture proof and committed required fixtures. Tests passed. Logger hook remains blocked because direct sell proceeds and current exit-leg stable fill-level idempotency are still not proven from the current broker response path. No live behavior/config/risk/runtime/strategy changes.
- 2026-05-31 03:38 UTC | head=0b2a629 | P2-011D-alt complete; Added Coinbase fills payload discovery with fixtures/tests. Finding: no fills/history wrapper exists; historical fills path is required for per-fill fee/liquidity/stable fill IDs, and order/status alone is insufficient. Logger hook remains blocked. No live behavior/config/risk/runtime/strategy changes.
- 2026-05-31 03:44 UTC | head=af1eb87 | P2-011E complete; Added minimal inert BrokerCoinbase.get_historical_fills wrapper proof with tests/docs. Wrapper is not called by live paths. Logger hook remains blocked pending end-to-end order + fills capture/reconciliation for entry and exit legs. No live behavior/config/risk/runtime/strategy changes.

---
### 2026-06-03 Auto-check
- Coinbase equity: $51.42
- Open positions: 0 (SOL/USD on broker = external/staked, not bot-tracked)
- Regime: dead_chop / range (0 proposals/scan)
- Trades today: 2 (live PLACED; both legs of one BTC/USD round trip)
- Last trade: 2026-06-03T01:31:01 UTC (BTC/USD exit, max-hold, -0.93%)
- Errors today: 0
- Capital gate status: 1/5 gates passing
- Notes: Live track record net-negative — 48 exits, 1 win / 47 loss (2.1% win rate), profit factor 0.003, net ≈ -$1.09; current consecutive loss streak 18, all of last 10 exits losing. Exits dominated by max-hold (90min) time stops, not strategy targets. Equity sits at $51.42 only because of deposited capital + external staked SOL, NOT trading gains. Gate 2 (win rate ≥50%), Gate 3 (PF ≥1.3), Gate 4 (≥14 days live; 8d), and Gate 5 (≤2 losses in last 10) all FAIL. Do not add capital. Alpaca bot idle (market closed, $10, 0 trades). All systems running, no errors. RED FLAG: time-stop-driven losses persist — backtester/strategy fix still the gating priority before any size or capital increase.

## P2-011F complete — Coinbase Order/Fills Reconciliation Proof

Last updated: 2026-05-31 18:24 UTC

P2-011F functional patch commit: 989292b

P2-011F completed pure Coinbase order-status + historical-fills reconciliation proof.

Added side-effect-free reconcile_order_with_fills() helper.

The helper preserves raw order/fill payloads, direct broker facts, stable per-fill idempotency keys, and blocks logger readiness when fees, stable IDs, or exit proceeds are missing.

The helper is not called by live trading paths.

Logger hook remains blocked.

Next patch after P2-011F was P2-011G narrow inert capture wiring at entry/exit seams, still no writes.

No live behavior, config, risk, runtime, strategy, .env, LaunchAgent, or order-submission changes were made.
- 2026-05-31 04:04 UTC | head=6ccf1fe | P2-011G complete; Added inert Coinbase entry/exit capture wiring proof with helper, tests, and docs. The helper can structure entry/exit reconciliation readiness and missing broker facts, but is not imported by live trading paths and performs no writes. Logger hook remains blocked pending opt-in dry-run proof in actual entry/exit flow and direct broker proof of sell proceeds, stable fill IDs, and fees. No live behavior/config/risk/runtime/strategy changes.
- 2026-05-31 04:21 UTC | head=20ce3df | P2-011H complete; Added opt-in dry-run Coinbase capture seam in actual entry/exit flow plus dedicated tests. The seam is disabled by default, stores in-memory dry-run results only when explicitly enabled, performs no logger writes, and does not call append_coinbase_fill_row. Logger hook remains blocked pending controlled broker-data proof of direct sell proceeds, stable fill IDs, and fees. No default live behavior/config/risk/runtime/strategy/order-submission changes.
- 2026-05-31 13:14 UTC | head=5fb6ffa | P2-011I complete; Added controlled dry-run broker-data capture/probe proof with documentation, script, and tests. The probe uses controlled Coinbase-like broker payloads through the opt-in dry-run seam, remains in-memory/test-only, performs no logger writes, does not call append_coinbase_fill_row, and does not change live behavior/config/risk/runtime/strategy/order-submission behavior. Logger hook remains blocked pending direct broker proof of sell proceeds, stable fill IDs, and fees.
- 2026-05-31 13:26 UTC | head=5b7e73e | P2-011J complete; Added read-only Coinbase broker-fact discovery/probe proof with documentation, script, and tests. The probe remains disabled by default for live calls, redacts sensitive identifiers, performs no writes, does not call append_coinbase_fill_row, and does not add or call order submission/cancel/modify paths. Logger hook remains blocked pending direct broker proof of sell proceeds, stable fill IDs, and per-fill fees.
- 2026-05-31 14:03 UTC | head=0ac6112 | P2-011K complete; Added controlled aggressive live runtime hardening: namespace-aware single-process lock, stale-lock recovery, conservative journal-driven counter reconstruction, honest startup logging, and read-only Coinbase ops status script. Live exploration remains enabled under tiny caps. Logger hook remains blocked; append_coinbase_fill_row is not called. Profit/readout metric must be included in every future status/handoff. Grok usage was around half during this run, so future Grok prompts should be compact and used only when local verification cannot resolve the issue.
- 2026-05-31 14:12 UTC | head=33b3ef1 | P2-011L complete; Fixed Coinbase ops status accuracy. Status now trusts the active lock PID on macOS/launchd, counts actual symbols under state/coinbase/open_positions.json, and calculates local exposure from notional with qty*entry fallback. No strategy/risk/notional/exposure/TP/SL/hold-time/symbol/order/logger changes. Profit/readout remains required in every status update and handoff.
- 2026-05-31 14:24 UTC | head=d8ad784 | P2-012A complete; Added universal Coinbase market universe and prediction telemetry scaffold. Product metadata can be classified conservatively, gold/silver-like products are classification candidates only, all newly discovered products default to live-disabled, and prediction/derivative-style feature helpers are available for future scoring. No strategy/risk/notional/exposure/TP/SL/hold-time/symbol/order/logger changes. Profit/readout remains required in every status update and handoff.
- 2026-05-31 14:56 UTC | head=f3ecb41 | P2-012B complete; Wired prediction telemetry into live scan/proposal/skip flow and added conservative multi-asset spot candidate plumbing/reporting. Telemetry is append-only and non-fatal. No notional/exposure/TP/SL/hold-time/current-symbol/order/leverage/perp/future/gold/silver/logger changes. Profit/readout remains required in every status update and handoff.
- 2026-05-31 15:11 UTC | head=9274b01 | P2-012C complete; Added controlled multi-asset Coinbase spot micro-trading enablement with explicit config gating, micro-size posture, prediction telemetry, max open/new-symbol gates, and deterministic exclusion reasons. Spot-only filter remains enforced. No leverage/perp/future/gold/silver/commodity/fill-logger enablement. Profit/readout remains required in every status update and handoff.
- 2026-05-31 15:22 UTC | head=a54cf52 | P2-012D complete; Turned on controlled multi-asset Coinbase spot micro-trading through explicit config allowlist. Micro-size posture preserved, prediction telemetry active, spot-only filters enforced, no leverage/perp/future/gold/silver/commodity/fill-logger enablement. Profit/readout remains required in every status update and handoff.
- 2026-05-31 15:33 UTC | head=cdc2450 | P2-012E complete; Fixed multi-asset config/status/runtime drift and symbol normalization so expanded allowlisted spot symbols can join live scans. ADA/USD and AVAX/USD are eligible scan expansion symbols when hard filters pass. Prediction telemetry active, P2-012D caps unchanged, no derivative/gold/silver/fill-logger enablement. Profit/readout remains required in every status update and handoff.
- 2026-05-31 15:55 UTC | head=81616ff | P2-013A complete; Added read-only prediction outcome evaluator + trade attribution with crash-proof default price loader, 15/30/60/90m outcome scaffolding, skipped-reason/conversion summaries, and best-effort journal attribution. Required tests and smoke script passed. No strategy/order/risk/symbol/cap/config/runtime changes. No leverage/perps/futures/gold/silver/commodities enabled. Fill logger remains blocked; append_coinbase_fill_row is not called. Profit/readout remains required in every status update and handoff.
- 2026-05-31 18:03 UTC | head=6e3b939 | P2-013B complete; Improved prediction outcome data-quality diagnostics and attribution matching. Script now reports evaluable/unevaluable horizon counts, no_price_data counts, candidate-to-trade conversions, unmatched telemetry candidates, unmatched journal trades, and clearer None-hit-rate explanations. Tests and script smoke passed. No strategy/order/risk/symbol/cap/config/runtime changes. No leverage/perps/futures/gold/silver/commodities enabled. Fill logger remains blocked; append_coinbase_fill_row is not called. Profit/readout remains required in every status update and handoff.
- 2026-05-31 18:30 | equity=$45.73 | positions=1 | regime=downtrend | errors=4 | head=b0bdca6 | SOL/USD open (broker_close_capability_unconfirmed); close failures logged — asset may be held in consumer wallet, position dropped from tracking after 3 retries
- 2026-05-31 18:30 UTC | head=b0bdca6 | P2-014 preflight/live status; Coinbase equity around $45.73, one SOL/USD bot-origin position open/re-associated, broker close capability unconfirmed, close failures logged, and visible recent journal exits remain negative. Preserve risk gates; no sizing/risk increase.
- 2026-05-31 (P2-014A) | head= (to be filled on commit) | P2-014A docs patch complete: ACTIVE_HANDOFF.md cleanly updated on review/p2-014a-... branch to preserve exact live SOL/USD reconciliation blocker status (equity ~$45.73, open/re-associated, unconfirmed close, failures logged, dropped from tracking possible). Added explicit P2-014 preflight section on unsafe-to-aggregate profit readout until direct fill/proceeds/fees reconciliation proven via reuse of existing P2-011F/G modules + tests. No runtime/strategy/risk/config/order/logger changes. git status clean, only doc changed. All invariants preserved.
- 2026-05-31 | head=39a3408 | P2-014D complete; Added read-only Coinbase open/orphan position status report with JSON output. SOL/USD broker-close/orphan blocker remains unresolved from local evidence. Realized P/L remains unsafe-to-aggregate. No runtime/config/order/risk/strategy changes. No fill logger writes. No leverage/margin/futures/perps/options/commodities/GOLD/SILVER/XAU/XAG enabled.
- 2026-05-31 | head=662dc1d | P2-014E complete; Added read-only Coinbase operator status aggregator with text/JSON output. Aggregator reports BLOCKED, profit_readout=unsafe_to_aggregate, sol_blocker_detected=true, and urgent SOL/USD broker-close investigation as next action. No runtime/config/order/risk/strategy changes. No broker API calls, .env reads, network calls, fill logger writes, or leverage/margin/futures/perps/options/commodities/GOLD/SILVER/XAU/XAG enabled.
- 2026-05-31 | head=2f2ab7a | P2-015A complete; Added explicit opt-in read-only Coinbase live broker reconciliation probe. Default mode performs zero broker/API calls; --live-read-only required for live reads. Default JSON is valid and reports BLOCKED, profit_readout=unsafe_to_aggregate, live_read_only=false, broker_calls_made=false. No runtime/config/order/risk/strategy changes, no order/close/cancel/modify calls, no file mutations, no fill logger writes, no leverage/margin/futures/perps/options/commodities/GOLD/SILVER/XAU/XAG enabled.
- 2026-05-31 | head=c9d8f05 | P2-015B complete; Fixed Coinbase live probe BrokerCoinbase adapter compatibility and unknown-state semantics. Default mode remains zero broker/API calls. When no successful broker read occurs, sol_on_broker and eth_on_broker are null/unknown, not false. No runtime/config/order/risk/strategy changes, no order/close/cancel/modify calls, no file mutations, no fill logger writes, no leverage/margin/futures/perps/options/commodities/GOLD/SILVER/XAU/XAG enabled.
- 2026-05-31 | head=061fabc | P2-016A complete; Added Grok Controlled Autonomy execution protocol and external signal context plan. External syndicated crypto/news/trend layer preserved for later as advisory-only after broker truth/direct P&L truth. Docs-only; no runtime/config/order/risk/strategy changes; no broker API calls; no fill logger writes; no leverage/margin/futures/perps/options/commodities/GOLD/SILVER/XAU/XAG enabled.
- 2026-05-31 | head=d67c37c | P2-016B complete; Added safe zero-network Coinbase live-readiness diagnostic (redacted credential presence, adapter/import status, text/JSON). Default mode zero broker/network calls. Current verdict BLOCKED due to missing COINBASE_API_KEY/SECRET. No runtime/config/order/risk/strategy changes, no secrets printed, no fill logger writes, no leverage/margin/futures/perps/options/commodities/GOLD/SILVER/XAU/XAG enabled.
- 2026-06-03 13:14 | equity=$51.42 | positions=0 | regime=no_proposals | errors=0 | head=e93c286
- 2026-06-03 UTC | head=e93c286 base | P2-025E committed on review/p2-025e-harden-offline-backtest-harness; hardened intra-bar TP/SL (SL precedence), taker/taker default + maker opt, pluggable policy scaffold (live_atr placeholder), journal-driven multi replay, new report fields/aggregates/fixtures/tests, docs; all safety flags, no live actions, no merge, unrelated untracked untouched. Review push only.
- 2026-06-03 UTC | head=0dd1105 | P2-025F committed on review/p2-025f-journal-window-replay-baseline; added journal-window replay adapter + report + fixtures + tests + docs. Offline baseline for reproducing known live loss (fee drag) before exit experiments. No live state, no restart, no trading authority. Review push only.

- 2026-06-03 UTC | head=0a28beb | P2-025G: OHLCV loader (csv/json), coverage report in replay, fixtures with symbols, doc. Real coverage may be 0 without local data/ dir. No live changes.
- 2026-06-03 16:03 | equity=$56.23 | positions=0 | regime=downtrend | errors=0 | head=09e1146
- 2026-06-03 UTC | head=09e1146 | P2-025H: local OHLCV import/validate tool (dry-run default, --write for normalized export), auto data/ dir discovery in replay report, tests, docs. No live changes.
