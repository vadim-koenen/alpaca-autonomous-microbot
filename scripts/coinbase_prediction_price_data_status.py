#!/usr/bin/env python3
"""
P2-013C — Read-only Local Price Data Status for Prediction Outcome Horizons.

Thin wrapper around the logic in prediction_telemetry.

Usage:
    python3 scripts/coinbase_prediction_price_data_status.py
    python3 scripts/coinbase_prediction_price_data_status.py --json
    python3 scripts/coinbase_prediction_price_data_status.py --telemetry logs/prediction_telemetry.jsonl

Always read-only. No network by default. Explains coverage and missing data.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.coinbase_prediction_outcomes import price_data_status_main

if __name__ == "__main__":
    price_data_status_main()
