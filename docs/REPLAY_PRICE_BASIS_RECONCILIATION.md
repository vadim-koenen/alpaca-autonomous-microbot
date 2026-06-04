# REPLAY PRICE-BASIS / FILL-BASIS RECONCILIATION (P2-025N)

## Why P2-025N exists
P2-025M (fidelity reconciliation at 3c7aa96) proved the replay harness is not yet trustworthy for diagnosing fee drag vs. other drivers:

- cycles_seen: 50
- cycles_analyzed: 48
- cycles_skipped: 2
- direction_match: 0.50 (24 mismatches)
- journal_analyzed_gross: -0.06102946
- replay_gross: +1.27830742
- signed gross residual: +1.33933688
- replay_trustworthy: false
- failed gates: direction_match < 0.85, abs(signed net residual using journal fees) > $0.10

P2-025L fee scenarios (fee_drag_dominant, break-even ~0.74%, notional sensitivity) are not actionable. The residual shows replay manufactures gross edge relative to broker journal reality. P2-025N isolates the source: price-basis (replay entry/exit simulation vs. actual journal fill prices) and fill-basis (journal fills vs. nearest OHLCV candle high/low).

This is strictly diagnostic. No maker/post-only, no exit tuning, no live experimentation.

## P2-025M failed gates (recap)
- direction_match 0.50 (far below 0.85 threshold)
- signed net residual (using journal fees) +1.33933688 (far above $0.10 abs)
- 24/48 cycles had direction mismatch (replay sign vs journal recorded sign)
- Timeout exits: 47/48 (~97.9%)
- By-sym: ETH contributed most positive residual (+1.107), BTC negative (-0.337); ALGO 0.0 direction match.

## How entry residual, exit residual, and gross residual are defined
- replay_entry_price := journal entry fill_price (by design of journal-window replay harness; entry is forced to recorded broker fill)
- replay_exit_price := inferred from replay_gross: qty = notional / journal_entry; exit_p = journal_entry + (replay_gross / qty)
- entry_price_residual = replay_entry_price - journal_entry_price  (expected ~0.0)
- exit_price_residual = replay_exit_price - journal_exit_price
- gross_residual = replay_gross - journal_gross
- Attribution (qty-based): entry_contrib = entry_res * qty; exit_contrib = exit_res * qty; gross_res ≈ exit_contrib (when entry_res≈0)

All residuals computed on zero-fee replay run (pure price path + slippage model) vs journal recorded gross. Net residual uses journal-recorded fees on replay gross.

## How candle high/low containment is interpreted
For each analyzed cycle we locate the nearest 5m OHLCV candle to the (derived) entry_time and to the exit_time (by symbol).

- journal_entry_within_candle_hl: journal_entry_price ∈ [nearest_entry_candle.low, .high]
- journal_exit_within_candle_hl: journal_exit_price ∈ [nearest_exit_candle.low, .high]

True means the broker-recorded fill was inside the bar's traded range (plausible for a 5m candle). False may indicate:
- fill occurred on a different micro-price / sub-bar not captured by 5m ohlcv
- timestamp alignment (journal ts vs candle bucket)
- data source difference (journal from fills, ohlcv from public candles)
- partial gap or bar filtering

Current run (48): entry_within ~0.9167, exit_within ~0.8958. Most journal fills fall inside nearest candle ranges; the residual is not primarily from "impossible" fills outside bars.

## How timeout exits can amplify close-vs-fill mismatches
- 47/48 analyzed cycles are journal max-hold (timeout) exits.
- Replay for timeout uses: last bar close in window + adverse slippage (conservative sell).
- Journal exit_price is the actual broker fill (market or limit at the moment of timeout).
- Any difference between simulated close+slip vs real fill price at that instant produces exit_res and thus gross_res.
- Since entry is identical (journal fill), all observed residual (+1.339 gross) is attributed to exit price difference.
- TP/SL in replay sim can trigger on intra-bar h/l even inside a journal-timeout window, producing "bar high/low + adverse" basis for some cycles.

## What the current dominant residual driver appears to be
From run on real untracked data (50/48/2, same as 025M):

- signed_gross_residual: +1.33933688
- attributed_to_entry_price: ~0
- attributed_to_exit_price: +1.33933688
- unattributed: ~0
- residual_appears_mostly: exit-driven (primarily timeout close-vs-fill vs journal exit fills)
- dominant_driver: timeout_exit_basis_issue (close-vs-fill on max-hold exits)
- timeout count/share: 47 / 0.979167
- large_residual_flags: 48 (abs gross >0.05 or >0.5% price res on many)
- direction_match: 0.50 (24 mismatches)
- replay_trustworthy: false (per 025M gates; price-basis explains the failure)

By-symbol residual attribution shows exit_contrib carries essentially all gross residual per symbol (entry ~0 everywhere).

Candle containment high but still ~4-5 cycles per side have journal fill outside nearest h/l — these may be the largest per-cycle residuals.

Replay entry basis: always "journal exact (fill_price from journal; not derived from candle)" (48/48).
Replay exit basis split: ~25 "bar high + adverse (take_profit)", ~23 "bar low + adverse (stop_loss)" — because the deterministic simulate still evaluates TP/SL levels on the window bars even for journal-timeout cycles.

## What must be true before maker/post-only feasibility work
- replay_trustworthy = true under 025M gates (dir >=0.85, med abs res pct notional <=0.10, abs signed net res using journal fees <=0.10) on real data after any data improvements.
- Price-basis residual closed or explicitly modeled (e.g. better timestamped fills, tick-level simulation for timeout exits, or documented conservative bias that is stable and small).
- Skipped gaps (ADA full + ETH partial) closed to high coverage with same fidelity result.
- Explicit evidence that residual direction and magnitude no longer manufacture edge (replay gross ≈ journal gross within tolerance).
- Still pure offline, review branch only, no live, no risk/config changes, no maker code yet.

## Invariants
- Pure offline. Reuses parse_journal_cycles, _load_bars_for_journal, _compute_coverage..., run_journal_window_replay (zero-fee), load_bars_from_fixture, and fidelity inference helpers. No duplicate journal parsing.
- No broker calls, no orders, no --live-read-only, no .env/secrets, no launchctl, no runtime, no network.
- Always emits trade_permission=none / risk_increase=not_approved / scaling_allowed=false.
- data/offline_ohlcv/ remains untracked (working data only).
- Review push only; no merge to main.
- Does not implement maker/post-only, does not modify exit logic or simulate, does not add paper/live probes.
- Suggested gap-closure commands (for ADA/ETH) are offline/manual only; never executed in this patch.

This report makes the price/fill basis divergence visible per-cycle and in aggregate. The +1.339 gross residual is exit-driven (timeout close-vs-fill). Fidelity gates remain failed. Do not proceed to maker feasibility.

## Gap clarification (ADA/ETH)
- ADA/USD: 1 seen, 0 covered (full no_ohlcv_in_window). Journal window ~2026-06-03 21:38:41Z entry to 23:08:41Z exit. No bars in local data for that symbol/window.
- ETH/USD: 15 seen, 14 covered, 1 partial (the cycle with entry ~2026-06-04 00:21:40Z to 01:51:40Z has no bars in its window in current ETH file).
- ALGO/BTC/SOL: 100% coverage on current local untracked 5m files.

To close (offline, manual, do not commit data/):
1. Use acquisition plan or public fetcher dry-run (if available) to identify exact required range.
2. Manually export the missing windows from exchange UI/CSV for ADA/USD and the specific ETH cycle (or use unauth public candles fetcher if run offline with --fetch after review).
3. Place raw file(s), then:
   python3 scripts/coinbase_ohlcv_import_validate.py --input /path/to/raw_ada.csv --symbol ADA/USD --write
   python3 scripts/coinbase_ohlcv_import_validate.py --input /path/to/raw_eth_addl.csv --symbol ETH/USD --write --start "2026-06-04T00:00:00Z" --end "2026-06-04T02:00:00Z"
4. Re-run fidelity + price-basis. If coverage improves and gates still fail, the price-basis divergence is confirmed independent of gaps.

Gaps are not the main blocker for the residual diagnosis (verdict on 48 covered cycles).

## Commands run for this report (baseline)
python3 scripts/coinbase_replay_fidelity_reconciliation.py --json
python3 scripts/coinbase_replay_price_basis_reconciliation.py --json
python3 scripts/coinbase_replay_price_basis_reconciliation.py

All validation, safety, and git constraints followed exactly. Stop after reporting. Do not merge.