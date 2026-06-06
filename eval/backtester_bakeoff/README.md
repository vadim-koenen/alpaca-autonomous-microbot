# Backtester Fidelity Bake-off (P2-030-EVAL)

Purpose:
Offline evaluation of backtesting engines (Jesse, Freqtrade) against the current home-grown replay engine.
This evaluates fidelity against 50 actual Coinbase live cycles.

Structure:
- `adapters/`: Logic to run the engines and extract normalized metrics.
- `strategies/`: Ports of the bot's crypto rules into engine-specific formats.
- `fixtures/`: Known tiny OHLCV data for unit testing the harness.
- `outputs/`: JSON/text results from bake-off runs.
- `docs/`: Fidelity and implementation notes.

Constraints:
- Offline only. No broker calls. No secrets.
- Isolated from production bot runtime.
