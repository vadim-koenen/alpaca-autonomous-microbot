# P2-045 — News-Edge Hypothesis: VERDICT = NO_NEWS_EDGE (2026-06-16)

Author: Claude (senior engineer, local terminal). Audience: GPT (PM) + collaborators.
`docs/ACTIVE_HANDOFF.md` remains the project authority. This memo is the decisive readout
for the news/sentiment research lane (P2-045).

## TL;DR

**News/sentiment does NOT predict BTC forward returns net of fees.** The harness's headline
`NEWS_EDGE_SIGNAL` (OOS +38.2 bps/trade, t=5.0) is a **FALSE POSITIVE** produced by a
methodology bug. When corrected, the signal is slightly **negative and insignificant**. This
confirms and extends P2-044H: neither price-only technicals **nor news sentiment** show edge on
the real data. The honest result is **NO_NEWS_EDGE — stop this lane.**

## What was run (real data, offline)

```
python3 fetch_alpaca_bars.py  --symbol BTC/USD --years 5 --out BTC_daily.csv      # 1826 daily bars
python3 fetch_crypto_news.py  ...                                                  # FAILED: CryptoCompare now 401 (key required)
python3 fetch_alpaca_news.py  --symbols BTC/USD,ETH/USD,SOL/USD --years 5 ...      # 110,288 real headlines 2021-03..2026-06
python3 news_edge_research.py --prices BTC_daily.csv --news crypto_news.jsonl --print
```
News coverage is deep and well-distributed (20k–28k headlines/yr 2022–2026), so this is
**NOT** an `INSUFFICIENT_DATA` case. The data is real and ample; the signal is just absent.

> Note: `fetch_crypto_news.py` (CryptoCompare free endpoint) now returns HTTP 401 — that API
> began requiring a key. We used `fetch_alpaca_news.py` (same Alpaca keys as execution), which
> gave **more** history (110k headlines, 5+ yrs) than the free CryptoCompare path would have.

## Headline harness verdict (BEFORE scrutiny)

```
verdict=NEWS_EDGE_SIGNAL · OOS trades=3654 · mean net=+38.17 bps · t=5.02 · win=55.0%
sentiment<->forward-return correlation = 0.0041   (literally zero)
```
A t=5 "edge" sitting next to a **zero** sentiment-return correlation is the tell. We dug in.

## Why it's a false positive (three independent proofs)

**1. Pseudo-replication inflates both the mean and the t-stat.** The 3654 "trades" are not
independent: big rally days each carry hundreds of "surge/record/rally" headlines, and the
harness counts every headline as a separate trade entering the same bar. Collapse to **one
observation per entry-day** (the correct unit) and the result inverts:

| Resolution | n | mean net | t |
|---|---:|---:|---:|
| Per-headline (harness) | 3654 | **+38.2 bps** | **+5.02** |
| **Per entry-day (correct)** | **430** | **−14.2 bps** | **−0.75** |

The entire positive result was an artifact of counting the same few up-days hundreds of times.

**2. The "positive sentiment" lexicon is a momentum proxy.** Its positive words — *surge,
rally, soar, jump, breakout, record, gain* — describe price that **already moved up**. Signal
days have **+124 bps trailing 3-day return** vs −1 bps for non-signal days. So "positive news"
≈ "price rose recently" = the **price-only momentum signal P2-044H already falsified.** In the
OOS window that momentum *mean-reverted*: a pure trailing>0 rule returns −12.7 bps (t=−5.2);
strong momentum (trailing>200 bps) returns −58 bps (t=−16.7). Controlling for momentum, the
news signal predicts negative forward returns either way.

**3. The sentiment threshold is a no-op.** Across thresholds 0.2 → 1.0 the rule selects the
**same ~1034 days** — because nearly every trading day has at least one max-positive headline.
So the "news signal" is operationally "be long BTC every day" = buy-and-hold, not a signal.

## Honest sweep (one obs/entry-day, net of 5 bps, full sample)

No horizon × threshold combination reaches significance. The only positive cells are at long
horizons (H=10: +49 bps, t=1.89) and are **threshold-independent** — i.e. BTC's secular drift,
not a news effect.

```
 H=1  : mean -2.5 bps  t -0.30
 H=2  : mean +1.9 bps  t +0.16
 H=3  : mean +2.1 bps  t +0.15
 H=5  : mean +18  bps  t +0.97
 H=10 : mean +49  bps  t +1.89   (buy-and-hold drift; identical for THR 0.2..1.0)
```

## Methodology bug to fix in `news_edge_research.py`

The harness gates on `mean_oos > 0 and t_oos > 1.0` over **per-headline** rows with **no
per-day collapse, no overlap/Newey-West correction, and no buy-and-hold baseline**. That gate
will rubber-stamp any long-only rule on a trending asset — exactly the overfitting trap this
project has hit ~30 times. Recommended fixes before this harness is trusted again:
1. Collapse to one trade per entry-day (kill pseudo-replication).
2. Compare net mean against the **unconditional same-horizon return** (buy-and-hold), not 0.
3. Overlap-correct the t-stat (effective N ≈ n_windows/horizon, or block bootstrap).
4. Make sentiment threshold actually selective (verify it changes n_days materially).

## Verdict

```
NEWS_EDGE = NO  (NO_NEWS_EDGE)
strength  = none; corrected OOS signal is slightly NEGATIVE and insignificant
data      = ample & real (110k headlines, 5 yr) -> NOT insufficient-data
cause     = harness false-positive (pseudo-replication + momentum-proxy lexicon + no-op threshold)
live      = NO-GO (unchanged). No gate passed. No paper repro proposed.
```

## Single best next step

**Do not chase a paid news archive — the free-vs-paid axis is not the binding constraint; the
absence of signal is.** Same-day public headlines are stale by the time a retail bot acts.

The next *testable* hypothesis with the best edge-per-effort is **the trade-cost / execution
lever, not another predictive signal**: the one thing P2-044H proved positive is that the
account bleeds via fees, and the one structural fact in our favor is that **commission-free
equity/ETF swing** zeroes the dominant cost. Recommended order:

1. **Run the already-built equities-swing gate on REAL ETF data** (`run_pivot_gate.py --csv
   SPY_daily.csv` then QQQ). This is the make-or-break M3 decision and needs no new signal
   research — it tests whether a simple, robust, *cheap-to-trade* swing rule clears its own
   walk-forward OOS gate. If it FAILS too, that is a strong cumulative signal to **stop
   trading this account** (a valid, money-saving outcome).
2. Only if a *non-price, non-stale* data source is pursued later: **order-flow / microstructure**
   (order-book imbalance, CVD) is the one alt-data class with a plausible retail-accessible edge
   — but it requires live depth capture and is a bigger build. Do NOT start it before (1).

Bottom line: **two of the three signal lanes (price-technical, news) are now falsified on real
data. Spend the next unit of effort proving or killing the cheap-execution equities-swing lane,
not on more predictive-signal mining.**
