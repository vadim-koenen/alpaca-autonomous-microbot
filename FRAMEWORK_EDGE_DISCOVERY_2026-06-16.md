# Edge-Discovery Framework — after 3 dead lanes (2026-06-16)

Author: Claude (senior eng/advisor). Audience: the operator + GPT (PM).
This is the deliverable requested after the third lane failed. It is brutally honest by design.

---

## 0. What "a framework that will succeed" can honestly mean

I cannot hand you a framework **guaranteed to produce a profitable bot**. Anyone who claims that
is lying or selling something. What I *can* deliver — and what actually protects your capital — is a
framework that is guaranteed to do one of two things:

> **(A) find a real, deployable edge if one exists within your reach, or
> (B) prove cheaply that none does, and stop you before you bleed more.**

That is the only definition of "success" that survives contact with reality. By that definition the
work so far has *already been succeeding*: it spent ~$1.61 and a month to falsify three hypotheses
that would have cost real money to discover live. The framework below makes the next round of that
faster, cheaper, and aimed at the parts of the space where retail can actually win.

---

## 1. The empirical state: three lanes, all dead

| Lane | Test | Result | Why it died |
|---|---|---|---|
| **1. Price-technical (crypto)** | P2-044H, 54 live trades | NO_EDGE | Gross ≈ 0 *before* fees; entries indistinguishable from random |
| **2. News / sentiment** | P2-045, 110k headlines | NO_NEWS_EDGE | "Signal" was a momentum proxy + a counting artifact; corrected = negative |
| **3. Equities-swing (SPY/QQQ)** | P2-044D gate, real ETF | NO_GO | Positive EV (+40–75 bps/trade) but **loses to buy-and-hold**; 0% of params survive OOS |

Note lane 3's failure mode is *different and instructive*: it's not that the strategy lost money — it
made money. It's that **it couldn't beat the trivial benchmark of just holding the asset**, and no
parameter set generalized out-of-sample. That is the single most important clue in this whole project.

---

## 2. Root cause: all three are the same losing bet

Strip away the surface differences and **all three lanes are the identical hypothesis**:

> "Use public information (price, or news) to **predict the short-term direction** of a **liquid asset**,
> then take a **directional** position."

That is the most crowded, most arbitraged, lowest-edge corner of the entire market. You are competing
against thousands of better-capitalized, faster, better-informed participants for the same public
signal. **The efficient-market null wins by default here, and it has — three times.** Continuing to draw
new hypotheses from this same well (a 4th indicator, a 5th data source, an ML model on the same OHLCV)
will keep failing for the same structural reason. The execution was never the problem. The *category* is.

**The framework's core move: stop hunting predictive edge on liquid assets. Hunt structural edge instead.**

---

## 3. The edge taxonomy — where retail loses vs. where retail can win

There are only a few fundamentally different ways to make money in markets. Sorted by realistic
retail accessibility:

| Edge type | What you're paid for | Retail-viable? | Your lanes |
|---|---|:--:|---|
| **Predictive / directional** | Forecasting price better than the crowd | ❌ Almost never | Lanes 1, 2, 3 — all here |
| **Carry / risk-premium harvest** | *Bearing a risk* others pay to offload | ✅ **Yes** | untested |
| **Liquidity provision / market-making** | Supplying immediacy (the spread) | ⚠️ Hard (infra) | untested |
| **Structural / flow arbitrage** | Forced/mechanical flows you front-run | ⚠️ Niche | untested |
| **Cross-venue arbitrage** | Same asset, two prices | ❌ HFT eats majors | untested |

The pattern is decisive: **everything you've tested is in the one row retail loses. Everything untested
is in rows where the edge is *structural* — you get paid for providing something or bearing something
real, not for being a better forecaster.** Structural edges persist *because they are compensation for
genuine risk or service*, not because a signal hasn't been arbitraged yet.

---

## 4. The ranked hypothesis portfolio (what to test next)

Each is a *structural* edge, with honest EV, effort, risk, and the kill-criterion. Test in order.

### #1 — Crypto funding-rate / basis carry (market-neutral) — **recommended next**
- **The edge (structural):** perpetual-futures longs pay shorts a *funding rate* (often +5–30% annualized
  when sentiment is bullish). Hold **spot long + perp short** in equal size → delta-neutral; you collect
  funding regardless of price direction. The cash-and-carry basis trade is the same idea on dated futures.
- **Why it can work where prediction failed:** you are paid for *providing leverage to over-eager longs*,
  a real service with real demand. No directional forecast required — which is exactly the skill you've
  proven (3×) you don't have.
- **EV / effort / risk:** historically real, single-to-low-double-digit % annualized net; moderate build
  (need a venue with perps + spot, funding-history backtest); **risks are real and must be modeled** —
  exchange/counterparty risk, liquidation on the short leg, funding flipping negative, execution slippage
  on two legs. Capacity is small-account-friendly.
- **Kill criterion:** if net-of-all-cost carry (funding − borrow − fees − slippage − tail-loss reserve)
  is ≤ a T-bill, it's dead. **This is the highest EV-per-effort untested hypothesis.**

### #2 — Time-series / cross-sectional momentum as a *portfolio* (not single-asset)
- **The edge (risk-premium):** trend-following across *many uncorrelated assets* is the most robust
  documented anomaly (works ~100 yrs, multi-asset). Lane 3 failed because it ran momentum on **one** asset
  vs. a benchmark it structurally couldn't beat. At the **portfolio** level, rebalanced **monthly**, the
  edge is diversification of many small independent trend bets, not beating buy-and-hold on SPY.
- **Why it differs from lane 3:** the unit of edge is the *cross-section of dozens of assets*, and the
  benchmark is a risk-parity / cash blend, not 100%-long one ticker.
- **EV / effort / risk:** modest Sharpe (~0.5–0.8) historically; low frequency (monthly) = cheap to run
  and PDT-safe; main risk is whipsaw in choppy regimes and that it's *widely known* (crowded but not dead).
- **Kill criterion:** fails if net-of-cost Sharpe < ~0.4 OOS across folds, or doesn't beat 60/40.

### #3 — Options premium selling (defined-risk, cash-secured)
- **The edge (insurance premium):** implied vol > realized vol on average → selling cash-secured puts /
  covered calls harvests the variance-risk premium. You're paid for *insuring* others.
- **Risk:** explicitly *not* free — left-tail crash risk. Only viable **defined-risk** and **small**.
- **Kill criterion:** if net premium after a realistic tail-loss reserve ≤ T-bill, dead.

### #4 — Structural flow anomalies (research-only until one is concrete)
- Index-rebalance front-running, ETF creation/redemption, monthly/overnight seasonal drift, options-expiry
  pinning. Persist because of *forced* flows. Lower priority — each needs its own falsification.

---

## 5. The universal gate every candidate must clear (so we never repeat P2-045)

The news lane produced a **false positive** because the harness lacked these. Bake them into every test:

1. **De-overlap / correct unit of observation.** One independent observation per decision, not per
   data-row. (P2-045's t=5.0 came from counting one rally 100×.)
2. **Beat the *right* benchmark.** Market-neutral → beat T-bills. Long-biased → beat buy-and-hold *and*
   risk-parity. Never "beats zero."
3. **OOS robustness, not a point estimate.** Must survive a *parameter grid* out-of-sample (≥ ~60% of
   combos), not one cherry-picked set. (Lane 3 scored 0% — that's what killed it, correctly.)
4. **Full real costs.** Fees + spread + slippage + borrow/funding + a tail reserve, on *every* leg.
5. **Capacity & operational risk.** Does it survive at $10–$1000? Counterparty, liquidation, downtime.
6. **Pre-registration.** Write the pass/fail thresholds *before* running, so we can't move the goalposts.

Order is unchanged and non-negotiable: **offline gate → paper repro → bounded live.** Nothing live until
a gate passes. "No edge / stop" remains a valid, valuable outcome at every step.

---

## 6. The honest decision tree

```
Test #1 (funding carry) offline gate
├── PASS  → paper-repro the carry harvester (still NO live) → bounded live A/B → scale only on M5
├── FAIL  → Test #2 (multi-asset momentum portfolio) → same gate
│            ├── PASS → paper → ...
│            └── FAIL → Test #3 (defined-risk premium selling) → same gate
│                        ├── PASS → paper → ...
│                        └── FAIL → STOP. The EV-maximizing move is NOT a bot.
```

**The terminal branch is real and not a failure.** If structural edges #1–#3 all fail their offline gates,
the rational, capital-maximizing conclusion is: **don't run a trading bot.** For a $10–$1000 account the
honest alternatives that *do* have positive expected value are (a) **DCA into BTC/equities** and hold (you
already flagged this as GO, independent of the bot), (b) **T-bills / money-market** at current rates, or
(c) treat the bot as a *paid education project* with a hard, pre-set budget cap and zero expectation of
profit. Each of those beats feeding a zero-edge directional bot.

---

## 7. Single best next step

**Build and run the offline funding-rate carry gate (#1).** It is the only untested hypothesis that
(a) does *not* require the directional-forecasting skill you've now disproven three times, (b) gets paid
by a real structural mechanism, and (c) is testable offline on free historical funding-rate data before
one dollar moves. Reuse the existing gate harness shape (real costs, OOS folds, pre-registered thresholds,
de-overlapped). If it fails the gate, proceed down the tree in §6 — and take the terminal "stop" branch
seriously if you reach it.

**Bottom line:** you have not proven trading is hopeless. You have proven — rigorously, three times — that
*directional prediction on liquid public markets* is hopeless **for a retail operator**, which is the
expected and well-documented result. The untested half of the map (structural / carry edges) is exactly
where small operators occasionally do win. That is where the next unit of effort goes. And if that half
also comes up empty, the framework will have succeeded by telling you, cheaply, to stop.
