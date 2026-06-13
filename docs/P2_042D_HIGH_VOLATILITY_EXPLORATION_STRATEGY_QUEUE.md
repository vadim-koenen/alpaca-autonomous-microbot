# P2-042D: High-Volatility Exploration Strategy Queue

## Overview
This document outlines the high-volatility exploration strategy queue, which serves as a purely deterministic proposal-generation and ranking layer for future live research.

**Important:** This patch *does not* enable live research. It does not approve live trading for profit. It does not interact with any active order submission pipelines.

## Purpose
The exploration queue evaluates signals based on four specific profiles:
1. `volatility_breakout`
2. `trend_continuation`
3. `reversal_snapback`
4. `spread_dislocation_skip`

Its core responsibility is to determine: "What high-volatility setup would be worth spending a small amount of research budget on, and why?"

## Core Mechanics
1. **Net Expected Edge Calculation**: All candidates are scored based on `gross_expected_edge_bps` minus explicitly estimated drags (`expected_fee_bps`, `spread_bps`, `expected_slippage_bps`).
2. **Strict Rejection Criteria**: Candidates are rejected if:
   - `net_expected_edge_bps <= 0` (zero or negative edge)
   - Spread exceeds max configured spread
   - Proposed notional exceeds max allowed notional
   - Symbol is not on the allowed list
   - Live trading for profit flag is `true` (fail closed)
3. **Journal Mapping**: The queue maps valid selections and rejected skips directly into `P2-042B`-compliant journal event dictionaries, distinguishing properly between dry-run and executable states.

## Next Steps
The next patch should be `P2-042E Live Research Readiness / Dry-Run Wiring`.
