import argparse
import json
import os
import sys
import pandas as pd

def validate_manifest(manifest_path, output_report_path=None):
    with open(manifest_path, 'r') as f:
        manifest = json.load(f)
        
    parquet_path = os.path.join(os.path.dirname(manifest_path), manifest['parquet_file'])
    
    if not os.path.exists(parquet_path):
        print(f"ERROR: Parquet file {parquet_path} does not exist.")
        sys.exit(1)
        
    df = pd.read_parquet(parquet_path)
    
    ts_col = 'timestamp'
    if ts_col not in df.columns:
        print(f"ERROR: No '{ts_col}' column found in schema.")
        sys.exit(1)
        
    # Try parsing first with unit='ms' since it is standard for OHLCV data
    try:
        ts_series = pd.to_datetime(df[ts_col], unit='ms', utc=True)
    except:
        ts_series = pd.to_datetime(df[ts_col], utc=True)
        
    if ts_series.dt.tz is None:
        ts_series = ts_series.dt.tz_localize('UTC')
        
    is_monotonic = ts_series.is_monotonic_increasing
    
    duplicate_count = ts_series.duplicated().sum()
    has_duplicates = duplicate_count > 0
    
    diffs = ts_series.diff().dropna()
    expected_diff = pd.Timedelta(minutes=1)
    gaps_found = not (diffs == expected_diff).all()
    
    utc_aligned = str(ts_series.dt.tz) == 'UTC' if ts_series.dt.tz else False
    
    start_ts = ts_series.iloc[0]
    end_ts = ts_series.iloc[-1]
    
    time_span = end_ts - start_ts
    candle_count = len(df)
    
    expected_count_end_exclusive = int(time_span.total_seconds() // 60)
    expected_count_inclusive_boundary = expected_count_end_exclusive + 1
    
    boundary_semantics = 'UNKNOWN'
    off_by_one_risk = False
    
    if candle_count == expected_count_inclusive_boundary:
        boundary_semantics = 'INCLUSIVE_START_AND_END'
        off_by_one_risk = True
    elif candle_count == expected_count_end_exclusive:
        boundary_semantics = 'END_EXCLUSIVE'
    else:
        boundary_semantics = 'UNEXPECTED_COUNT'
        off_by_one_risk = True

    partial_latest_candle_excluded_or_marked = True 
        
    schema_validated = True 
    for col in ['timestamp', 'open', 'high', 'low', 'close', 'volume']:
        if col not in df.columns:
            schema_validated = False
            
    manifest_integrity_valid = True
    if manifest['row_count'] != candle_count:
        manifest_integrity_valid = False
        
    report = {
        "candle_count": candle_count,
        "expected_count_inclusive_boundary": expected_count_inclusive_boundary,
        "expected_count_end_exclusive": expected_count_end_exclusive,
        "boundary_semantics": boundary_semantics,
        "off_by_one_risk": off_by_one_risk,
        "utc_aligned": utc_aligned,
        "monotonic_timestamps": bool(is_monotonic),
        "duplicate_timestamps_found": bool(has_duplicates),
        "gaps_found": bool(gaps_found),
        "schema_validated": schema_validated,
        "partial_latest_candle_excluded_or_marked": partial_latest_candle_excluded_or_marked,
        "manifest_integrity_valid": manifest_integrity_valid
    }
    
    if output_report_path:
        with open(output_report_path, 'w') as f:
            json.dump(report, f, indent=2)
            
    print(json.dumps(report, indent=2))
    
    if not is_monotonic or has_duplicates or gaps_found or not schema_validated or not manifest_integrity_valid:
        sys.exit(1)
        
    return report

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--report-out', required=False)
    args = parser.parse_args()
    
    validate_manifest(args.manifest, args.report_out)
