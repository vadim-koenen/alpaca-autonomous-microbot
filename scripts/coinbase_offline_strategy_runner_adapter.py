#!/usr/bin/env python3
"""
P2-025V offline strategy runner adapter.

Offline-only. Provides an adapter for strategy_crypto.py logic to run against
historical OHLCV data without live broker components.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from unittest.mock import MagicMock, patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Import strategy logic
try:
    from strategy_crypto import CryptoStrategy, classify_regime, REGIME_STRATEGIES
    from market_data import Quote, add_indicators
    from risk_manager import TradeProposal
    STRATEGY_LOGIC_IMPORTABLE = True
except ImportError:
    STRATEGY_LOGIC_IMPORTABLE = False

from coinbase_offline_backtest import load_bars_from_fixture

SCHEMA_VERSION = "p2-025v.coinbase_offline_strategy_runner_adapter.v1"
DATA_DIR = ROOT / "data" / "offline_ohlcv" / "coinbase"

class OfflineMarketDataAdapter:
    """
    Mocks MarketData for CryptoStrategy.
    Returns provided dataframe and quote.
    """
    def __init__(self, df: pd.DataFrame, quote: Quote):
        self.df = df
        self.quote = quote
    
    def get_crypto_quote(self, symbol: str) -> Quote:
        return self.quote
    
    def get_crypto_bars_df(self, symbol: str, limit: int = 100) -> pd.DataFrame:
        return self.df.iloc[-limit:]

def _model_quote_from_bar(bar: Any, spread_pct: float = 0.10) -> Quote:
    """
    Create a mock Quote from an OHLCV bar.
    Mid = Close. Bid/Ask modeled around close with fixed spread.
    """
    close = float(getattr(bar, "c", bar.get("c") if hasattr(bar, "get") else 0))
    ts = getattr(bar, "t", bar.get("t") if hasattr(bar, "get") else None)
    
    mid = close
    # spread_pct 0.10 means bid = mid * (1 - 0.0005), ask = mid * (1 + 0.0005)
    half_spread = (spread_pct / 100.0) / 2.0
    bid = mid * (1.0 - half_spread)
    ask = mid * (1.0 + half_spread)
    
    return Quote(
        symbol="", # filled by caller
        bid=bid,
        ask=ask,
        mid=mid,
        spread_pct=spread_pct,
        timestamp=ts,
        is_stale=False
    )

def build_strategy_runner_report(
    *,
    data_dir: Optional[Path] = None,
    symbol: str = "BTC/USD",
    max_bars: int = 100,
) -> Dict[str, Any]:
    dpath = Path(data_dir) if data_dir else DATA_DIR
    
    # Discovery
    available_reusable = []
    if STRATEGY_LOGIC_IMPORTABLE:
        available_reusable.extend(["classify_regime", "CryptoStrategy", "add_indicators"])
    
    live_deps = ["MarketData", "load_saved_positions", "get_cfg", "now_utc"]
    
    # Readiness checks
    pure_indicator_logic_available = STRATEGY_LOGIC_IMPORTABLE
    pure_regime_logic_available = STRATEGY_LOGIC_IMPORTABLE
    pure_signal_logic_available = STRATEGY_LOGIC_IMPORTABLE
    
    offline_marketdata_adapter_ready = True
    offline_strategy_runner_ready = STRATEGY_LOGIC_IMPORTABLE
    
    # Smoke run
    bars_loaded = 0
    candidate_signals_count = None
    last_regime = None
    
    if STRATEGY_LOGIC_IMPORTABLE:
        # Find a file for the symbol
        norm_sym = symbol.replace("/", "-")
        files = list(dpath.glob(f"{norm_sym}_*.csv")) + list(dpath.glob(f"{norm_sym}_*.json"))
        if files:
            bars = load_bars_from_fixture(files[0])
            if bars:
                bars = bars[:max_bars]
                bars_loaded = len(bars)
                
                # Convert bars to DF for indicators
                rows = []
                for b in bars:
                    rows.append({
                        "t": b.t,
                        "o": float(b.o),
                        "h": float(b.h),
                        "l": float(b.l),
                        "c": float(b.c),
                        "v": float(b.v),
                    })
                df = pd.DataFrame(rows).set_index("t")
                df = add_indicators(df)
                
                # Try run strategy logic on last bar
                try:
                    latest_bar = df.iloc[-1]
                    last_regime = classify_regime(df)
                    
                    # Mock config for pure signal generation
                    mock_cfg = {
                        "strategy": {"prefer_no_trade_when_unclear": True, "lookback_bars": 20},
                        "crypto": {
                            "bars_limit": 100, 
                            "min_bars_required": 10,
                            "use_atr_exits": True,
                            "stop_loss_pct": 1.5,
                            "take_profit_pct": 2.5,
                            "slippage_estimate_pct": 0.05,
                            "coinbase_probe_enabled": False,
                            "controlled_exploration": {"enabled": False}
                        },
                        "fees": {
                            "maker_fee_pct": 0.0015,
                            "taker_fee_pct": 0.0025,
                            "require_expected_edge_pct": 0.006
                        }
                    }
                    
                    with patch("strategy_crypto.get_cfg", side_effect=lambda *keys, **kwargs: mock_cfg.get(keys[0], {}).get(keys[1], kwargs.get("default")) if len(keys) > 1 else mock_cfg.get(keys[0], kwargs.get("default"))):
                        quote = _model_quote_from_bar(latest_bar)
                        adapter = OfflineMarketDataAdapter(df, quote)
                        strat = CryptoStrategy(adapter)
                        
                        # We bypass generate_proposals to avoid the _last_bar_ts guard and explore specific methods
                        candidate_signals_count = 0
                        regime_strats = REGIME_STRATEGIES.get(last_regime, [])
                        for s_name in regime_strats:
                            method_name = f"_{s_name}"
                            if hasattr(strat, method_name):
                                method = getattr(strat, method_name)
                                # These methods have varying signatures, but momentum/mean_rev/ema share some
                                try:
                                    if s_name == "momentum_breakout":
                                        p = method(symbol, quote, df, True, 100.0, 20, last_regime)
                                    else:
                                        p = method(symbol, quote, df, True, 100.0, last_regime)
                                    
                                    if p:
                                        candidate_signals_count += 1
                                except Exception:
                                    continue

                except Exception as e:
                    # Logic importable but execution failed due to remaining dependencies
                    offline_strategy_runner_ready = False
    
    historical_signal_generation_ready = offline_strategy_runner_ready and bars_loaded > 0

    payload = {
        "schema_version": SCHEMA_VERSION,
        "report_class": "offline_strategy_runner_adapter",
        "strategy_logic_importable": STRATEGY_LOGIC_IMPORTABLE,
        "pure_indicator_logic_available": pure_indicator_logic_available,
        "pure_regime_logic_available": pure_regime_logic_available,
        "pure_signal_logic_available": pure_signal_logic_available,
        "offline_marketdata_adapter_ready": offline_marketdata_adapter_ready,
        "offline_strategy_runner_ready": offline_strategy_runner_ready,
        "historical_signal_generation_ready": historical_signal_generation_ready,
        "live_dependencies_detected": live_deps,
        "unsafe_dependencies_blocking": ["CryptoStrategy._coinbase_exploration (reads journal/positions)"] if STRATEGY_LOGIC_IMPORTABLE else ["ImportError"],
        "available_reusable_functions": available_reusable,
        "smoke_run": {
            "symbol": symbol,
            "bars_loaded": bars_loaded,
            "last_regime": last_regime,
            "candidate_signals_count": candidate_signals_count,
        },
        "verdict": {
            "implementation_authorized": False,
            "paper_probe_authorized": False,
            "live_probe_authorized": False,
            "scaling_authorized": False,
        },
        "next_step_recommendation": "Build the Historical Signal Generator that iterates over bars and applies this adapter."
    }
    return payload

def _human_summary(payload: Dict[str, Any]) -> str:
    lines = [
        "=== OFFLINE STRATEGY RUNNER ADAPTER ===",
        f"strategy_logic_importable:         {payload['strategy_logic_importable']}",
        f"offline_strategy_runner_ready:     {payload['offline_strategy_runner_ready']}",
        f"historical_signal_generation_ready: {payload['historical_signal_generation_ready']}",
        "",
        "Reusable Functions Detected:",
    ]
    for fn in payload["available_reusable_functions"]:
        lines.append(f"  - {fn}")
    
    lines.extend(["", "Live Dependencies (to be mocked/bypassed):"])
    for dep in payload["live_dependencies_detected"]:
        lines.append(f"  - {dep}")

    lines.extend(["", "Smoke Run Result:"])
    s = payload["smoke_run"]
    lines.append(f"  symbol:         {s['symbol']}")
    lines.append(f"  bars_loaded:    {s['bars_loaded']}")
    lines.append(f"  last_regime:    {s['last_regime']}")
    lines.append(f"  signals_found:  {s['candidate_signals_count']}")

    lines.extend([
        "",
        f"Next Step: {payload['next_step_recommendation']}",
        "",
        "Authorization: implementation=false paper=false live=false scaling=false",
        "=== END REPORT ===",
    ])
    return "\n".join(lines)

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Offline strategy runner adapter")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--symbol", type=str, default="BTC/USD")
    parser.add_argument("--max-bars", type=int, default=100)
    args = parser.parse_args(argv)

    payload = build_strategy_runner_report(
        data_dir=args.data_dir,
        symbol=args.symbol,
        max_bars=args.max_bars,
    )
    if args.json:
        json.dump(payload, sys.stdout, indent=2)
        print()
    else:
        print(_human_summary(payload))
    return 0

if __name__ == "__main__":
    sys.exit(main())
