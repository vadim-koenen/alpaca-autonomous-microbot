# Candidate Filter Backtest Validation

## Why This Exists

P2-025S identified several candidate "no-trade" or selectivity filters that could potentially improve the strategy's negative predictive gross edge. However, these were identified through "after-the-fact" decomposition of a small 50-cycle window.

`scripts/coinbase_candidate_filter_backtest_validation.py` provides a formal offline report to validate whether these filters actually hold up under backtest conditions, applying strict validation gates to prevent overfitting and false confidence.

## Current Findings (50-Cycle Window)

As of `2026-06-04`, the validation report analyzed 50 cycles between `2026-05-25` and `2026-06-04`.

| Scenario | Sample Size | Gross P/L | Win Rate | Status |
| :--- | :--- | :--- | :--- | :--- |
| `baseline_all_cycles` | 50 | `-0.26885977` | 0.40 | provisional |
| `exclude_stop_loss` | 49 | `-0.16357491` | 0.4082 | provisional |
| `exclude_symbol_ETH/USD` | 35 | `-0.10541099` | 0.40 | provisional |
| `exclude_strategy_mean_reversion` | 48 | `-0.25046993` | 0.4167 | provisional |
| `combo_exclude_ETH_and_ADA` | 34 | `-0.04105684` | 0.4118 | provisional |

### Verdict: **NOT VALIDATED**

None of the candidate filters resulted in a positive predictive gross edge over the current window. While some filters reduced the total loss, the strategy remains fundamentally unprofitable before fees in this sample.

## Validation Gates

To graduate from "provisional" to "validated", a candidate filter must pass all of the following:

1.  **Sample Size:** Minimum 30 cycles (Weak), Preferred 50+ cycles.
2.  **Directional Edge:** `predictive_gross_total > 0`.
3.  **Stability:** `avg_gross > 0`.
4.  **Efficiency:** `win_rate >= 0.45`.
5.  **Concentration:** Total gains must not be entirely driven by the top 10 winners (preventing outlier-dependency).

## Data Limitations & Acquisition Plan

The current findings are **provisional** due to the small sample size (50 cycles) and limited time window (10 days).

To increase confidence, a larger historical dataset is required. The report provides a safe acquisition plan using public, unauthenticated market data:

- **Next Data Needed:** OHLCV data for period **BEFORE 2026-05-25**.
- **Safe Command:** `python3 scripts/coinbase_public_ohlcv_fetch.py --symbol ETH/USD --start 2026-05-01 --end 2026-05-25 --granularity 5m --fetch --write`

## Interpretation & Safety

- **No Live Implementation:** None of these filters are authorized for live use.
- **Hypothesis Testing Only:** These results are exploratory and intended to inform future offline strategy development.
- **Preserved Invariants:** implementation_authorized=false, paper_probe_authorized=false, live_probe_authorized=false, scaling_authorized=false.
