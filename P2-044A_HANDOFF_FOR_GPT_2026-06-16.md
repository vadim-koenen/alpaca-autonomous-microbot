# Claude → GPT Handoff — P2-044A Pivot Feasibility Matrix (2026-06-16)

Author: Claude (Cowork, terminal execution layer). Audience: GPT (PM) + collaborators.
Authoritative over chat memory for this slice. `docs/ACTIVE_HANDOFF.md` remains the project authority.

## ★ DECISIVE FINDING (P2-044H, 2026-06-16) — read first

Ran `analyze_live_journal.py` on the ACTUAL 54 live trades. The bot's **gross P&L BEFORE any
fees is −$0.17** on ~$120 cumulative position value. Re-priced under every venue:

| Venue | Round-trip | Net on the real 54 trades |
|---|---:|---:|
| coinbase_taker (current) | 2.40% | −$3.05 |
| coinbase_maker | 1.20% | −$1.61 |
| alpaca_crypto | 0.50% | −$0.77 |
| alpaca_equities | 0.00% | **−$0.17** |

**Diagnosis = NO_EDGE.** Mean gross return is −0.12%/trade, gross direction win-rate 42.6%
(worse than a coin flip), t-stat −1.52. Even at ZERO fees the strategy loses. Therefore the
binding constraint is NOT fees and NOT the venue — it is that the entry signal has no predictive
power. No venue switch, fee tier, or parameter patch can make a zero-edge signal profitable.
The only paths to profit are (a) a genuinely predictive signal, validated offline on real OHLCV
with the P2-044B/C/D gates BEFORE any live trade, or (b) stop trading this strategy. This
supersedes the earlier "pivot venue" framing: cheaper venues help only if an edge exists, and on
the live evidence it does not.

## NEXT RESEARCH LANE (P2-045) — does NEWS add the edge price-technicals lacked?

P2-044H proved the PRICE-ONLY technical signals have no edge. The untested lever is alternative data.
`news_edge_research.py` (P2-045A) backtests whether news/sentiment predicts forward returns net of
fees (offline, out-of-sample, >=30 events). `fetch_alpaca_news.py` (P2-045B) pulls real historical
news from Alpaca (same keys). End-to-end on the Mac:
```bash
# PREFERRED crypto pipeline (CryptoPanic crypto news; fetch_alpaca_bars auto-routes BTC/USD to crypto):
python3 fetch_alpaca_bars.py  --symbol BTC/USD --years 5 --out BTC_daily.csv
python3 fetch_crypto_news.py  --currencies BTC,ETH,SOL --pages 30 --out crypto_news.jsonl   # CryptoCompare, free, no key
python3 news_edge_research.py --prices BTC_daily.csv --news crypto_news.jsonl --print
# (Alpaca equity-leaning news alternative: fetch_alpaca_news.py --symbols BTC/USD,ETH/USD --years 5 --out news.jsonl)
```
Verdict NEWS_EDGE_SIGNAL / NO_NEWS_EDGE / INSUFFICIENT_DATA. A positive result earns an offline gate
+ paper repro, never a direct live trade. This is a legitimate hypothesis but not guaranteed to exist.

NOTE on environment: this work was built in Cowork's sandbox (no external network, read-only .git), so
the FETCH steps must run on the Mac — via Claude Code (local terminal + network + git + .env) or GPT.
The analysis step (news_edge_research.py) runs anywhere once the CSV/JSONL exist.

## TL;DR

The P2-044 decision is **STOP the falsified Coinbase short-horizon thesis + run ONE offline pivot screen before any new strategy code.** That screen is now built and green. It is **offline-only, advisory, no broker, no runtime mutation, not committed.** Your job: review, then branch + commit **on the Mac** (sandbox `.git` is locked — see below).

**Recommended pivot lane to carry into a real-cost backtest gate: `alpaca_equities_etf_swing`** (commission-free, multi-day swing on a liquid ETF, PDT-safe). This is NOT a profit claim — it only earns the right to a P2-043D-style walk-forward. Live stays NO-GO.

## Repo state (verified)

```
MAIN_COMMIT=f8db5d16fe4fbaecbbc2b81c224447e73e5cd8cd   # unchanged
BRANCH=main                                            # NOT switched
NEW_UNTRACKED_FILES=2
  - pivot_feasibility_matrix.py                        (repo root)
  - tests/test_p2_044a_pivot_feasibility_matrix.py
CODE_CHANGED=true (new files only; no existing file modified)
FILES_COMMITTED=false
SANDBOX_GIT=LOCKED (.git/index.lock unlinkable: "Operation not permitted") -> commit on Mac
TESTS=17 passed (pytest, pure stdlib; no pyarrow/duckdb needed)
RUNTIME_MUTATION=none
BROKER_CALLS=none
ARTIFACTS=written to /tmp only (not committed)
```

## ⚠️ GOVERNANCE FLAG — verify before anything else

`runtime/STOP_TRADING` (the bare kill-switch sentinel) is **ABSENT** in the current working tree.
It is **gitignored and not tracked**, so it is invisible to git and was not part of any commit.
Only zero-byte backups remain: `STOP_TRADING.backup.*`, `STOP_TRADING.manual_backup_2`, `STOP_TRADING.supervised_restart_*.bak`.

ACTIVE_HANDOFF states `runtime/STOP_TRADING` must be **present**. Claude did **not** create or remove it (out of remit: no runtime mutation). **Action for human/GPT on the Mac:** confirm intended governance state and, if the kill-switch should be active (it should, trading is NO-GO), restore it:

```bash
touch runtime/STOP_TRADING   # restores the 0-byte sentinel; reinforces NO-GO
```

Do not treat its absence as permission to trade. All live decisions remain NO-GO regardless of this file.

## What was built (P2-044A)

`pivot_feasibility_matrix.py` — an **offline cost-vs-expected-move screen** over candidate pivot lanes.
For each lane it computes: round-trip cost (bps), expected absolute move at the lane's horizon
(sqrt-time scaled from the verified 90-min/80-bps BTC/ETH anchor, or an explicit override for equities),
the **hurdle ratio** (expected move / cost), the **symmetric breakeven win-rate**
(`p* = 0.5 + cost/(2·move)`; ≥1.0 = structurally unwinnable), live-capital + PDT compliance for a $10
account, and a verdict. It is a screen, **not** a profit model.

Verdict bands: `INFEASIBLE` (hurdle <1, move < cost) · `MARGINAL` (1–2×) · `FEASIBLE_TO_TEST` (≥2×, earns an offline backtest only) · `BASELINE` (no-trade).

### Result matrix (assumptions — CONFIRM fee schedules before deciding)

| Lane | Cost bps RT | Exp move bps | Hurdle | Breakeven win% | Live OK | Prior edge | Verdict |
|---|---:|---:|---:|---:|:--:|---:|:--:|
| Coinbase taker 90-min (falsified) | 256 | 80 | 0.31× | 100% | yes | 3.5% | INFEASIBLE |
| Coinbase maker 90-min | 130 | 80 | 0.61× | 100% | yes | 8.5% | INFEASIBLE |
| Coinbase longer-horizon 4–24h | 256 | 185 | 0.72× | 100% | yes | 15% | INFEASIBLE |
| Cheaper-venue crypto ~4h (Alpaca) | 66 | 131 | 1.98× | 75.3% | yes | 13% | MARGINAL |
| **Alpaca equities/ETF swing (~3d)** | **6** | **150** | **25×** | **52%** | **yes** | **17.5%** | **FEASIBLE_TO_TEST** |
| Alpaca equities/ETF intraday | 6 | 40 | 6.67× | 57.5% | NO (PDT) | 6% | FEASIBLE_TO_TEST |
| No-trade / park | 0 | 0 | inf | — | yes | 0% | BASELINE |

Reading: every **Coinbase short-horizon** lane is INFEASIBLE — expected move is below round-trip cost even with maker fees or a longer horizon (taker cost dominates). The cost hurdle only clears decisively when fees go to ~0 (commission-free equities) and turnover drops (swing horizon avoids PDT). Cheaper-venue crypto is borderline (MARGINAL).

## Honesty caveats (do not overstate this)

- This screen does **not** prove edge. `FEASIBLE_TO_TEST` = "worth an offline backtest," nothing more.
- All fee/move numbers are **assumptions**. Confirm Alpaca crypto (~0.15/0.25%) and equities commission-free + real ETF spread/slippage, and re-confirm Coinbase tier, before any decision.
- The equities lanes assume liquid ETF vol; the swing move (150 bps/~3d) is a placeholder to confirm with real OHLCV.

## Next steps for GPT

1. **Verify the governance flag above** (restore `runtime/STOP_TRADING` on the Mac if intended).
2. **Review** `pivot_feasibility_matrix.py` + the matrix output (`/tmp/p2_044a_pivot_feasibility_matrix.md`).
3. If you accept the deliverable, **branch + commit on the Mac** (do NOT commit the `/tmp` artifacts):

```bash
cd <repo>
git checkout -b review/p2-044a-pivot-feasibility-matrix
git add pivot_feasibility_matrix.py tests/test_p2_044a_pivot_feasibility_matrix.py
python3 -m pytest tests/test_p2_044a_pivot_feasibility_matrix.py -q   # expect 17 passed
git commit -m "P2-044A: offline pivot feasibility matrix (no live, /tmp output)"
# review branch only — NO merge to main without MERGE_APPROVED
```

4. **Decide the single pivot lane** to carry forward. Claude's recommendation: `alpaca_equities_etf_swing`.
5. **Build the real-cost walk-forward gate for that lane** (reuse the P2-043D harness shape: real OHLCV, ≥100–200 trades, fees+spread+slippage+fill-prob, beats no-trade AND buy-and-hold, stable across folds). Only a PASS there unfreezes live.

## DO NOT

- Do not merge to `main` without `MERGE_APPROVED`.
- Do not enable live trading, restart, capital increase, symbol expansion, or P2-043E+ strategy patches.
- Do not commit `/tmp/p2_044a_*` artifacts.
- Do not read the swing-ETF recommendation as "turn it on." It needs its own offline gate first.
- Do not mine more Coinbase short-horizon filters — that lane is falsified on arithmetic.

## P2-044B — Equities/ETF swing backtest GATE (added 2026-06-16, same session)

The make-or-break gate for the recommended lane is now built: `equities_swing_backtest_gate.py`
+ `tests/test_p2_044b_equities_swing_backtest_gate.py`. **34 tests total pass (17 A + 17 B).**

What it does: long-only Donchian-breakout SWING strategy (PDT-safe: daily bars => hold >= 1 day),
real-cost accounting (commission-free + spread + slippage on both fills), walk-forward folds, and a
PASS/FAIL verdict vs **both** no-trade and buy-and-hold baselines. Thresholds mirror P2-043D:
`n_trades>=100 · net EV/trade>0 AND >=2x round-trip cost · PF>=1.3 · beats buy&hold · beats no-trade ·
fold stability>=0.6`.

**Critical:** it is DATA-AGNOSTIC. It needs REAL daily OHLCV to be decision-grade:
```bash
python3 equities_swing_backtest_gate.py --csv path/to/SPY_or_QQQ_daily.csv --print
# CSV columns: date,open,high,low,close,volume
```
With no `--csv` it runs a SYNTHETIC random-walk smoke test that is stamped `decision_grade=false`
and `authorizes_live=false` — it only proves the harness mechanics, never profitability. On synthetic
noise the gate correctly returns **FAIL** (it does not rubber-stamp). The verdict **never** authorizes
live directly; a PASS only unlocks the next step (paper reproduction), then bounded live A/B.

**GPT next action:** obtain real liquid-ETF daily OHLCV (e.g. SPY/QQQ, multi-year) on the Mac, run the
gate with `--csv`, and treat the resulting verdict as the M3 decision for the pivot. If FAIL, the
equities-swing lane is falsified too — do not go live; reconsider lanes or park. If PASS, proceed to
paper reproduction (M4), not live.

## P2-044C — Anti-overfitting robustness sweep (added 2026-06-16, same session)

`swing_param_robustness.py` + `tests/test_p2_044c_swing_param_robustness.py`. The project's history
is overfitting (~30 prior filters falsified). This sweep runs the P2-044B gate over a parameter grid
with anchored in-sample/out-of-sample splits and returns **ROBUST / FRAGILE / FALSIFIED**: an edge only
counts if it survives OOS across *many* combos, not one cherry-picked set. On synthetic noise it
correctly returns FALSIFIED (best combo looked great — 169 bps, PF 2.55 — but on only 5 trades, 11% of
combos passing OOS). Run order on real data: **C (robust?) → B decision-grade run → paper → live A/B.**
Even ROBUST never authorizes live directly.

## P2-044D + P2-044E — orchestrator + data fetcher (added 2026-06-16, same session)

- `run_pivot_gate.py` (D): one command that runs the robustness sweep (C) AND the gate (B)
  on a CSV and emits ONE verdict: **GO_TO_PAPER** (requires real data + robustness ROBUST +
  gate PASS) or **NO_GO**. GO_TO_PAPER is the strongest output and **never** means live.
- `fetch_etf_ohlcv.py` (E): Mac-side fetcher/normalizer (yfinance) that writes the exact CSV
  schema the gates need. Its pure `normalize_rows()` is unit-tested offline; the network fetch
  runs on the Mac. Read-only data, no orders.

- `fetch_alpaca_bars.py` (F): **preferred** Alpaca-native daily-bars fetcher — same vendor as
  execution (satisfies "Alpaca API only"), reads ALPACA keys from env/.env, read-only market data,
  never prints keys, free IEX feed by default. yfinance (E) remains as a no-keys convenience fallback.

**End-to-end on the Mac (the actual path to a profit decision):**
```bash
pip install 'alpaca-py>=0.26' pytest
# Preferred (Alpaca, uses your existing keys; nothing new to enable):
python3 fetch_alpaca_bars.py --symbol SPY --years 10 --out SPY_daily.csv
# (or, no keys: python3 fetch_etf_ohlcv.py --symbol SPY --period 10y --out SPY_daily.csv)
python3 run_pivot_gate.py --csv SPY_daily.csv --print      # GO_TO_PAPER or NO_GO
# (repeat for QQQ; try a couple liquid ETFs)
```
Data tiers: Alpaca free IEX daily bars are sufficient for this backtest. Paid SIP / Algo Trader Plus
is only for full real-time depth — not needed here.
If `GO_TO_PAPER`: proceed to paper reproduction (M4), not live. If `NO_GO`: the equities-swing
lane is falsified too — reconsider lane (cheaper-venue crypto was MARGINAL) or park. No-trade is valid.

## Getting REAL OHLCV so the gates are decision-grade (run on the Mac)

The gates are data-agnostic and need real daily ETF bars. Easiest options on the Mac:
- `pip install yfinance` then: `python3 -c "import yfinance,csv; df=yfinance.download('SPY',period='10y',interval='1d'); df.to_csv('SPY_daily.csv')"`
  then normalize headers to `date,open,high,low,close,volume`.
- Or Alpaca's own historical bars API (read-only) for SPY/QQQ daily, written to the same CSV schema.
- Or Stooq/Nasdaq CSV exports.
Then: `python3 swing_param_robustness.py --csv SPY_daily.csv --print` and
`python3 equities_swing_backtest_gate.py --csv SPY_daily.csv --print`.
(Claude could not fetch market data in-session — web fetch is restricted and inventing prices is barred.)

## P2-044G — venue cost comparison + a real fee-accounting FIX (added 2026-06-16)

`venue_compare.py` + tests run the SAME swing strategy through the gate under four cost models
(coinbase_taker, coinbase_maker, alpaca_crypto, alpaca_equities) side by side. Crypto venues use the
crypto CSV; the equities venue uses an ETF CSV (or is flagged `data_mismatch` if only crypto data is
supplied — fee-isolation mode).

**Fee-accounting fix (important):** building G exposed a bug in `equities_swing_backtest_gate.py` — the
per-trade net P&L only included spread+slippage (via fills); the **commission was never subtracted from
trade returns**, only used in the gate's cost-multiple threshold. Fixed: `net_bps` now subtracts
`2 * commission_bps_per_side`. This does not change the commission-free equities default (commission=0)
or any prior A/B/C/D synthetic verdict, but it materially lowers net EV for Coinbase/Alpaca-crypto cost
models. Regression test added (`test_commission_is_actually_subtracted_from_net`).

**Illustrative fee-isolation result (synthetic price path, commission effect only):** on an identical
series, net EV/trade was alpaca_equities +152 bps > alpaca_crypto +95 > coinbase_maker +26 >
coinbase_taker **-98** bps. i.e. Coinbase taker's ~240 bps round-trip commission alone flips a
gross-positive strategy to net-negative; cheaper venues retain most of the edge. Re-run on REAL crypto
+ ETF OHLCV for the decision-grade comparison: `python3 venue_compare.py --crypto-csv BTC.csv --equities-csv SPY.csv --print`.

## How to sync everything for GPT (run on the Mac)

```bash
cd /path/to/alpaca-autonomous-microbot
bash sync_p2_044_for_gpt.sh      # branches, restores STOP_TRADING, runs tests, commits
```
This creates `review/p2-044a-pivot-feasibility-matrix`, restores the kill-switch, runs the 34 tests,
and commits the 4 code files + this handoff. No merge to main, no push (uncomment to push).

## Structured readout

```text
P2_044A_BUILT=true
P2_044B_BUILT=true
P2_044C_BUILT=true
P2_044D_BUILT=true
P2_044E_BUILT=true
TESTS=53_passed (17A+17B+7C+5D+7E)
DELIVERABLES=pivot_feasibility_matrix.py,equities_swing_backtest_gate.py,swing_param_robustness.py,run_pivot_gate.py,fetch_etf_ohlcv.py (+ matching tests/test_p2_044*.py)
SYNC_SCRIPT=sync_p2_044_for_gpt.sh (run on Mac)
END_TO_END=fetch_etf_ohlcv.py->run_pivot_gate.py --csv -> GO_TO_PAPER|NO_GO
RUN_ORDER_ON_REAL_DATA=fetch->run_pivot_gate(C+B)->paper(M4)->live_AB(M5)
STRONGEST_OUTPUT=GO_TO_PAPER (never live)
DATA_NEEDED=real_daily_ETF_ohlcv_csv (SPY/QQQ); claude_could_not_fetch (web restricted); fetcher provided
COMMITTED=false
COMMIT_ON=mac (sandbox .git locked: index.lock unremovable)
BRANCH_TO_CREATE=review/p2-044a-pivot-feasibility-matrix
RECOMMENDED_LANE=alpaca_equities_etf_swing
COINBASE_SHORT_HORIZON=INFEASIBLE(taker,maker,longer-horizon)
CHEAPER_VENUE_CRYPTO=MARGINAL
NO_TRADE_BASELINE=included
P2_044B_GATE=ready_needs_real_ohlcv_csv_to_be_decision_grade
P2_044B_SYNTHETIC_VERDICT=FAIL(not_decision_grade)
LIVE_TRADING=NO-GO
RESTART=NO-GO
CAPITAL_INCREASE=NO-GO
GOVERNANCE_FLAG=runtime/STOP_TRADING_absent_restore_on_mac(sync_script_restores_it)
NEXT=run_p2_044b_gate_with_real_etf_ohlcv_then_paper_if_pass
```
```
