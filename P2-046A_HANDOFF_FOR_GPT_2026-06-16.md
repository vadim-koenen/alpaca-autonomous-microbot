# Claude → GPT Handoff — P2-046A Accumulator/Allocator pivot (2026-06-16)

Author: Claude (senior eng, local terminal). Audience: GPT (PM) + collaborators.
`docs/ACTIVE_HANDOFF.md` is the project authority. This is the slice handoff so you can
continue if my credits run out.

## The pivot (decided with the operator this session)

All three signal lanes are falsified on real data (price-technical P2-044H, news P2-045,
equities-swing P2-044D). The operator and I agreed: **there is no accessible directional edge for
a retail bot** ("that's insider trading, and we don't have it"). So the bot's JOB changes from
**trader** to **systematic accumulator/allocator**: DCA into a diversified basket, hold, rebalance,
optionally buy bigger tranches when an asset is cheap vs its own long-run trend. Full reasoning:
`FRAMEWORK_EDGE_DISCOVERY_2026-06-16.md`.

Critical honesty guard carried into the pivot: **"buy at the lows" is allowed only as a MECHANICAL
rule (buy more cheap units vs a trailing MA), never as prediction. "Jump into upswings via news" is
the FALSIFIED hypothesis (P2-045) and is NOT built. News, if built, is advisory + risk-alert only,
never an entry signal.**

## What was built (P2-046A) — first deliverable of the pivot

`accumulator_allocator.py` + `tests/test_p2_046a_accumulator_allocator.py` (**15 tests pass**, pure
stdlib, reuses `equities_swing_backtest_gate` for Bar/load/synthetic). It is the OFFLINE laboratory
check: does the valuation overlay actually beat plain DCA across a basket, capital-neutral, BEFORE we
build it live? Causal MA, budget-neutral plain-vs-overlay, optional drift-band rebalance, pre-registered
verdict VALUATION_OVERLAY_HELPS / NO_BENEFIT / INSUFFICIENT_DATA. Offline only, /tmp output, no broker.

## Decision-grade result (real 5-asset basket, equal weight, 2021–2026, 1255 common bars)

```
python3 accumulator_allocator.py --csv BTC=BTC_daily.csv SPY=SPY_clean.csv QQQ=QQQ_daily.csv \
  GLD=GLD_clean.csv SLV=SLV_clean.csv --rebalance-every 13 --rebalance-band 0.25 --print
```

| Strategy | Multiple | Max DD |
|---|---:|---:|
| **plain_dca** | **1.85x** (~13%/yr) | **15.7%** |
| overlay_dca | 1.77x (−4.5%) | 14.3% |

**Verdict: NO_BENEFIT.** Two findings:
1. **The pivot works.** Plain DCA into the diversified basket = 1.85x with only 15.7% max drawdown
   (vs BTC-alone ~70% DD). Steady growth, gentle drawdowns, compounds as capital is added — the
   operator's actual goal.
2. **The dip-overlay does NOT help.** It lowered cost basis on 4/5 assets but cut the result 4.5%:
   in a rising market the idle dry powder it banks costs more than the cheaper entries save. Only a
   mild drawdown reducer. **Build plain DCA + diversification + rebalance; keep the overlay OFF (or
   demoted to optional risk-damper). Do NOT build the live dip-buyer as a return feature.**

> Note: an earlier BTC-only quick-look (1.86x vs 1.60x) looked favorable only because it wasn't
> budget-neutral (overlay deployed more total). The rigorous capital-fair, diversified test reverses it.

## Data used (NOT committed — regenerate on the Mac)

```
python3 fetch_alpaca_bars.py --symbol BTC/USD --years 5  --out BTC_daily.csv
python3 fetch_alpaca_bars.py --symbol SPY    --years 10 --out SPY_daily.csv   # drop pre-2020 orphan -> SPY_clean.csv
python3 fetch_alpaca_bars.py --symbol QQQ    --years 10 --out QQQ_daily.csv
python3 fetch_alpaca_bars.py --symbol GLD    --years 10 --out GLD_daily.csv   # -> GLD_clean.csv (>=2020-07-27)
python3 fetch_alpaca_bars.py --symbol SLV    --years 10 --out SLV_daily.csv   # -> SLV_clean.csv (>=2020-07-27)
```
(SPY/GLD/SLV have one pre-2020 orphan bar from the free IEX feed; filter to date>=2020-07-27.)

## Next steps for GPT (build order — stay offline until a gate + paper pass)

1. **Robustness pass on the basket result** (the project's history is overfitting). Re-run plain-vs-overlay
   across sub-periods/folds and a few weight sets to confirm NO_BENEFIT is stable, not a one-window
   artifact. If overlay is reliably ≤ plain, freeze the overlay OFF for v1.
2. **P2-046B — allocation + rebalance design**: finalize basket + target weights + rebalance band on a
   *risk-adjusted* basis (drawdown, not just return). Plain DCA is the v1 engine.
3. **P2-046C — news module as a SEPARATE non-trading service**: advisory dashboard + named-event risk
   circuit-breaker (alert/pause, never auto-sell). No entry signals. Reuse `fetch_alpaca_news.py`.
4. **Paper repro (M4) → bounded live (M5)**: contributions on a schedule, caps unchanged.

## Governance (unchanged)

`runtime/STOP_TRADING` present. No live trading, no restart, no orders, no runtime mutation. Alpaca
keys in `.env`, never printed/committed. Live remains NO-GO; nothing here authorizes live. Review
branch `review/p2-045-news-edge-research` (commit on it; no merge to main without `MERGE_APPROVED`).

## Structured readout

```text
PIVOT=trader->accumulator_allocator
P2_046A_BUILT=true  TESTS=15_passed
REAL_BASKET=BTC,SPY,QQQ,GLD,SLV (equal weight, 2021-2026)
PLAIN_DCA=1.85x ~13%/yr maxDD=15.7%
OVERLAY_DCA=1.77x (-4.5%) maxDD=14.3%
VERDICT=NO_BENEFIT (build plain DCA; overlay OFF/optional risk-damper)
DIP_BUY_AT_LOWS=mechanical_only_not_prediction; not worth complexity v1
NEWS=advisory+risk_alert_only_NOT_entry_signal (P2-045 falsified)
LIVE=NO-GO  RESTART=NO-GO  COMMITTED_DATA=false
NEXT=robustness_then_alloc_rebalance_design(P2-046B)
```
