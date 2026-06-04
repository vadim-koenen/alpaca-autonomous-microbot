# Gross-Edge Failure Decomposition

## Why This Exists

P2-025R proved that maker/post-only execution is not feasible for the current strategy because the **predictive gross edge is negative before fees**.

`scripts/coinbase_gross_edge_decomposition_report.py` provides an offline-only diagnostic to isolate why the strategy loses money before any fee considerations. It uses the `predictive_live_exit_policy` replay basis established in P2-025P.

## Key Findings

Based on the 50-cycle analysis:

- **Predictive Gross Total:** `-0.26885977`
- **Win Rate:** `0.40`
- **Dominant Loss Driver:** `exit_reason_timeout` (49/50 cycles were timeouts, contributing `-0.16357491` in gross loss).
- **Concentration:** The worst 10 cycles (20% of trades) account for `-0.30111453` in loss, exceeding the total net loss.
- **Symbol Concentration:** ETH/USD is the worst-performing symbol, contributing `-0.16344878` in gross loss.

## Decomposition Dimensions

The report analyzes losses across:
- **Symbol:** ETH/USD and ADA/USD are significant negative contributors.
- **Strategy:** `coinbase_exploration` accounts for the majority of the negative edge.
- **Exit Reason:** Timeout (90min) is the primary exit mode, showing a persistent negative drift.
- **Hold Duration:** Most losses occur in the 0-15min bucket, suggesting immediate adverse move after entry or poor entry timing.
- **Spread & Confidence:** Currently limited by available journal data in the baseline sample, but structured for future high-resolution analysis.

## Counterfactual Hypotheses

These filters represent hypothetical "no-trade" or selectivity improvements. They are **not** recommendations for live implementation but candidates for future backtest validation:

| Filter | Gross Delta | Sample Size | Risk |
| :--- | :--- | :--- | :--- |
| `exclude_stop_loss` | `+0.10528486` | 49 | Low (Single event) |
| `exclude_symbol_ETH/USD` | `+0.16344878` | 35 | Medium |
| `exclude_strategy_mean_reversion`| `+0.01838984` | 48 | Low |

**Note:** Filters like `exclude_low_confidence` or `exclude_timeout` result in very small sample sizes (< 20 cycles) and are considered high-risk for overfitting.

## Interpretation Rules

- **No Live Changes:** This report does not authorize changes to strategy thresholds, exit logic, or risk caps.
- **Hypothesis Only:** All improvements identified are exploratory only.
- **Gross Focus:** Fees are intentionally excluded to isolate the fundamental directional/timing failure.

## Next Steps

1.  **Do not implement maker/post-only.**
2.  **Do not tune exits yet.**
3.  **Perform offline backtest validation** of the candidate filters (ETH exclusion, specific strategy selectivity) on a larger historical dataset before any live proposal.
4.  **Investigate entry timing** for `coinbase_exploration` and `mean_reversion` to address the immediate negative drift seen in early durations.

## Preserved Invariants

- `implementation_authorized=false`
- `paper_probe_authorized=false`
- `live_probe_authorized=false`
- `scaling_authorized=false`
- No live broker/trading endpoint access.
- No config/risk changes.
