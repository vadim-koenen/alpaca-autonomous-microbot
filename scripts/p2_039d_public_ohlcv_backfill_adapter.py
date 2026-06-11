#!/usr/bin/env python3
"""P2-039D Public OHLCV Backfill Adapter / Dry-Run First.

Governed public market-data backfill adapter. Safely prepares historical 
OHLCV fetches into the P2-039C substrate. Requires explicit network flags.
"""

import argparse
import datetime
import logging
import pathlib
import sys
from typing import Dict, Any, Optional

import pandas as pd
import pyarrow as pa

# Import existing substrate definitions from P2-039C
try:
    from scripts import p2_039c_local_ohlcv_backfill as backfill
except ImportError:
    import p2_039c_local_ohlcv_backfill as backfill

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


class MockPublicProvider:
    """Mock public provider for fixture-based tests without network calls."""
    
    def fetch_ohlcv(self, symbol: str, timeframe: str, start_dt: datetime.datetime, end_dt: datetime.datetime) -> pd.DataFrame:
        """Returns synthetic OHLCV data spanning the requested period."""
        logging.info(f"MockProvider: Simulating public fetch for {symbol} {timeframe} from {start_dt} to {end_dt}")
        
        # Determine frequency
        freq = "1min" if timeframe == "1m" else "1D"
        
        # Generate date range
        dates = pd.date_range(start=start_dt, end=end_dt, freq=freq, tz='UTC')
        
        # Return empty if requested range is somehow invalid
        if len(dates) == 0:
            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
        df = pd.DataFrame({
            "timestamp": dates,
            "open": [100.0] * len(dates),
            "high": [105.0] * len(dates),
            "low": [95.0] * len(dates),
            "close": [102.0] * len(dates),
            "volume": [10.5] * len(dates)
        })
        
        # Convert timestamp to epoch ms as per P2-039C requirements
        epoch = pd.Timestamp("1970-01-01", tz="UTC")
        df['timestamp'] = ((df['timestamp'] - epoch) // pd.Timedelta(milliseconds=1)).astype(int)
        
        return df


def calculate_coverage(df: pd.DataFrame, timeframe: str, expected_start: datetime.datetime, expected_end: datetime.datetime) -> Dict[str, Any]:
    """Report-only coverage summary for requested vs available bars."""
    if len(df) == 0:
        return {
            "requested_bars": 0,
            "bars_written": 0,
            "missing_bars": 0,
            "start_discovered": None,
            "end_discovered": None,
            "coverage_percentage": 0.0
        }
        
    # Estimate requested bars based on timeframe
    delta = expected_end - expected_start
    if timeframe == "1m":
        requested_bars = int(delta.total_seconds() // 60) + 1
    else:
        requested_bars = int(delta.total_seconds() // 86400) + 1 # fallback roughly 1d

    bars_written = len(df)
    
    # Calculate actual boundaries discovered
    min_ms = df['timestamp'].min()
    max_ms = df['timestamp'].max()
    start_disc = datetime.datetime.fromtimestamp(min_ms / 1000.0, tz=datetime.timezone.utc).isoformat()
    end_disc = datetime.datetime.fromtimestamp(max_ms / 1000.0, tz=datetime.timezone.utc).isoformat()
    
    missing_bars = max(0, requested_bars - bars_written)
    coverage = (bars_written / requested_bars) * 100.0 if requested_bars > 0 else 0.0
    
    return {
        "requested_bars": requested_bars,
        "bars_written": bars_written,
        "missing_bars": missing_bars,
        "start_discovered": start_disc,
        "end_discovered": end_disc,
        "coverage_percentage": round(coverage, 2)
    }


def prepare_and_fetch(
    provider_name: str,
    symbol: str,
    timeframe: str,
    start_dt: datetime.datetime,
    end_dt: datetime.datetime,
    allow_public_fetch: bool,
    output_root: pathlib.Path,
    use_mock: bool = False
) -> Dict[str, Any]:
    """Execute dry-run or actual backfill pipeline."""
    
    sym_norm = backfill.normalize_symbol(symbol)
    expected_dest = output_root / sym_norm / timeframe
    
    logging.info(f"=== OHLCV BACKFILL PREFLIGHT ===")
    logging.info(f"Provider: {provider_name}")
    logging.info(f"Symbol: {symbol} ({sym_norm})")
    logging.info(f"Timeframe: {timeframe}")
    logging.info(f"Start: {start_dt.isoformat()}")
    logging.info(f"End: {end_dt.isoformat()}")
    logging.info(f"Expected Destination: {expected_dest}")
    
    local_exists = expected_dest.exists() and any(expected_dest.glob("*.parquet"))
    logging.info(f"Local Coverage Exists: {local_exists}")
    
    # Default dry-run behavior
    if not allow_public_fetch:
        logging.info("DRY-RUN DEFAULT: public_fetch_performed=false")
        logging.info("Manifest Intent: WOULD WRITE to substrate if flag provided.")
        return {"status": "dry_run_complete", "public_fetch_performed": False}
        
    # Execute fetch
    logging.info("PUBLIC FETCH: public_fetch_performed=true")
    
    if use_mock:
        provider = MockPublicProvider()
    else:
        # Prevent actual unchecked internet calls for now unless fully implemented
        raise NotImplementedError("Real public fetch provider not yet implemented. Use --mock for testing.")
        
    df = provider.fetch_ohlcv(symbol, timeframe, start_dt, end_dt)
    
    # Validate and Write
    if len(df) > 0:
        table = pa.Table.from_pandas(df, schema=backfill.OHLCV_SCHEMA, preserve_index=False)
        backfill.validate_ohlcv_schema(table)
        out_path, manifest = backfill.write_ohlcv_parquet(table, output_root, symbol, timeframe, provider_name)
    else:
        logging.warning("No data returned by provider.")
        out_path = None
        manifest = {}
        
    coverage = calculate_coverage(df, timeframe, start_dt, end_dt)
    logging.info(f"=== COVERAGE AUDIT ===")
    for k, v in coverage.items():
        logging.info(f"{k}: {v}")
        
    return {
        "status": "success",
        "public_fetch_performed": True,
        "coverage": coverage,
        "manifest": manifest,
        "out_path": str(out_path) if out_path else None
    }


def main():
    parser = argparse.ArgumentParser(
        description="P2-039D Public OHLCV Backfill Adapter\n\n"
                    "SAFETY DEFAULTS:\n"
                    "- Dry-run by default.\n"
                    "- Public fetch requires explicit flag.\n"
                    "- NO authenticated broker access allowed.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    parser.add_argument("--symbol", required=True, help="Symbol to fetch (e.g. BTC/USD)")
    parser.add_argument("--provider", default="yahoo", help="Public provider name (default: yahoo)")
    parser.add_argument("--start", required=True, help="Start date ISO8601 (e.g. 2026-05-01)")
    parser.add_argument("--end", required=True, help="End date ISO8601 (e.g. 2026-06-01)")
    parser.add_argument("--timeframe", default="1m", help="Timeframe (default: 1m)")
    parser.add_argument("--output-root", type=str, default=None, help="Root for output substrate")
    
    # Explicit Security Gates
    parser.add_argument("--allow-public-fetch", action="store_true", help="Explicitly enable network fetching")
    parser.add_argument("--mock", action="store_true", help="Use local mock provider for tests")
    
    args = parser.parse_args()
    
    # Parse dates safely
    try:
        start_dt = pd.to_datetime(args.start, utc=True).to_pydatetime()
        end_dt = pd.to_datetime(args.end, utc=True).to_pydatetime()
    except Exception as e:
        logging.error(f"Failed to parse dates: {e}")
        sys.exit(1)
        
    # Resolve roots
    if args.output_root:
        out_root = pathlib.Path(args.output_root)
    else:
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        out_root = repo_root / "data" / "market_data" / "ohlcv"
        
    result = prepare_and_fetch(
        provider_name=args.provider,
        symbol=args.symbol,
        timeframe=args.timeframe,
        start_dt=start_dt,
        end_dt=end_dt,
        allow_public_fetch=args.allow_public_fetch,
        output_root=out_root,
        use_mock=args.mock
    )
    
    if not result["public_fetch_performed"]:
        sys.exit(0) # Successful dry-run

if __name__ == "__main__":
    main()
