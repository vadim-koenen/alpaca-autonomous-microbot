# Strategy Rule Port Notes

## Current Strategy Rules
- **RSI Mean-Reversion**: RSI(14) < 35.
- **Bollinger Lower Band**: Price < BB(20, 2) lower band.
- **Bollinger Threshold**: `bb_lower_band_pct=0.15` (Price must be at or below 15% of the band width from the bottom).
- **Max Hold**: 90 minutes.
- **Stop Loss**: 1.5%.
- **Take Profit**: 3.0%.
- **Asset Class**: Crypto (Long-only).
- **Venue**: Coinbase.

## Jesse Port Notes
- Jesse uses a class-based strategy structure.
- Entry logic mapped to `should_long`.
- Exit logic mapped to `update_position` or fixed SL/TP.
- Fees must be configured in `config.py` for Jesse.

## Freqtrade Port Notes
- Freqtrade uses a class-based strategy structure.
- Entry logic mapped to `populate_entry_trend`.
- SL/TP handled by `stoploss` and `minimal_roi` attributes.
- Fees handled by exchange-specific configuration.

## Implementation Fidelity
- Standard indicators (RSI, BB) are consistent across all engines.
- The "15% of band width" logic needs careful mapping to Jesse/Freqtrade custom indicators.
