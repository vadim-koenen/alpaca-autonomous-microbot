#!/usr/bin/env python3
"""
P2-025U offline signal/cycle generation scaffold.

Offline-only. Evaluates repository readiness for larger-history backtesting
by identifying required strategy inputs, missing components, and 
proposing an offline reconstruction architecture.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coinbase_offline_backtest import (  # noqa: E402
    load_bars_from_fixture,
    _normalize_symbol,
)

SCHEMA_VERSION = "p2-025u.coinbase_offline_signal_cycle_generation_scaffold.v1"
DATA_DIR = ROOT / "data" / "offline_ohlcv" / "coinbase"

def _inventory_ohlcv(data_dir: Path) -> List[Dict[str, Any]]:
    inventory = []
    if not data_dir.exists():
        return inventory
    
    for f in sorted(data_dir.glob("*.csv")) + sorted(data_dir.glob("*.json")):
        try:
            bars = load_bars_from_fixture(f)
            if not bars:
                continue
            
            # Heuristic for symbol from filename if not in bars
            fname = f.name.upper()
            symbol = bars[0].symbol if bars[0].symbol else fname.split("_")[0].replace("-", "/")
            
            inventory.append({
                "file": f.name,
                "symbol": symbol,
                "candle_count": len(bars),
                "start": bars[0].t.isoformat(),
                "end": bars[-1].t.isoformat(),
            })
        except Exception:
            continue
    return inventory

def build_offline_signal_scaffold(
    *,
    data_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    dpath = Path(data_dir) if data_dir else DATA_DIR
    inventory = _inventory_ohlcv(dpath)
    
    # Required Signal Inputs Analysis
    required_inputs = {
        "candles": {"status": "available", "source": "OHLCV files"},
        "indicators": {"status": "partial", "source": "market_data.add_indicators (needs integration)"},
        "regime_detection": {"status": "partial", "source": "strategy_crypto.classify_regime (needs integration)"},
        "bid_ask_spread": {"status": "missing", "source": "Not in OHLCV; needs modelling (e.g. close + modeled spread)"},
        "confidence_scoring": {"status": "partial", "source": "Reconstruction from indicators needed"},
        "position_constraints": {"status": "missing", "source": "Offline state manager needed (max_open_positions, cooldowns)"},
        "daily_trade_caps": {"status": "missing", "source": "Offline state tracker needed"},
    }

    # Readiness Gates
    # Currently false because we haven't integrated indicators/signals into a replay loop yet.
    signal_generation_ready = False
    cycle_generation_ready = False
    historical_backtest_ready = False

    # Gap Report
    missing_components = [
        "Offline Strategy Runner (adapter for strategy_crypto.py logic)",
        "Mock MarketData provider for offline dataframes",
        "Bid/Ask/Spread model for OHLCV bars",
        "Offline state manager for position/cooldown simulation",
        "Historical Signal Generator (scans bars and emits candidate entries)"
    ]

    payload = {
        "schema_version": SCHEMA_VERSION,
        "report_class": "offline_signal_cycle_generation_scaffold",
        "data_directory": str(dpath),
        "ohlcv_inventory": inventory,
        "required_signal_inputs": required_inputs,
        "missing_components": missing_components,
        "readiness": {
            "signal_generation_ready": signal_generation_ready,
            "cycle_generation_ready": cycle_generation_ready,
            "historical_backtest_ready": historical_backtest_ready,
        },
        "proposed_architecture": [
            "1. OHLCV Loader (detects files, loads bars)",
            "2. Indicator Reconstruction (applies add_indicators to bars)",
            "3. Signal Generator (runs strategy logic over bars, emits entries)",
            "4. Entry Simulator (applies bid/ask modeling and slippage)",
            "5. predictive_live_exit_policy Simulator (replays from entry to exit)",
            "6. Cycle Journal Generator (emits schema-compliant cycles for reports)",
            "7. Filter Validation (runs P2-025T logic on the generated cycles)"
        ],
        "verdict": {
            "implementation_authorized": False,
            "paper_probe_authorized": False,
            "live_probe_authorized": False,
            "scaling_authorized": False,
        },
        "notes": [
            "Scaffold and gap analysis only. Does not implement strategy logic.",
            "Older OHLCV alone is insufficient for backtest expansion without signal generation.",
            "Bid/Ask data is the primary high-fidelity gap in OHLCV-only datasets.",
            "Next implementation should focus on the Offline Strategy Runner adapter."
        ]
    }
    return payload

def _human_summary(payload: Dict[str, Any]) -> str:
    lines = [
        "=== OFFLINE SIGNAL/CYCLE GENERATION SCAFFOLD ===",
        f"data_dir: {payload['data_directory']}",
        f"symbols_detected: {len(payload['ohlcv_inventory'])}",
        "",
        "Readiness Gates:",
        f"  signal_generation_ready:   {payload['readiness']['signal_generation_ready']}",
        f"  cycle_generation_ready:    {payload['readiness']['cycle_generation_ready']}",
        f"  historical_backtest_ready: {payload['readiness']['historical_backtest_ready']}",
        "",
        "Required Input Gaps:",
    ]
    for k, v in payload["required_signal_inputs"].items():
        lines.append(f"  {k:<20} | status: {v['status']:<10} | source: {v['source']}")
    
    lines.extend(["", "Missing Components:"])
    for mc in payload["missing_components"]:
        lines.append(f"  - {mc}")

    lines.extend(["", "Proposed Architecture:"])
    for step in payload["proposed_architecture"]:
        lines.append(f"  {step}")

    lines.extend([
        "",
        "Authorization: implementation=false paper=false live=false scaling=false",
        "=== END REPORT ===",
    ])
    return "\n".join(lines)

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Offline signal/cycle generation scaffold")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--data-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    payload = build_offline_signal_scaffold(
        data_dir=args.data_dir,
    )
    if args.json:
        json.dump(payload, sys.stdout, indent=2)
        print()
    else:
        print(_human_summary(payload))
    return 0

if __name__ == "__main__":
    sys.exit(main())
