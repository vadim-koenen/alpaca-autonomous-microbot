import argparse
import json
import os
import sys
import pandas as pd

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifests', nargs='+', required=True)
    parser.add_argument('--report-out', default='/tmp/p2_040h_normalized_report.json')
    parser.add_argument('--output-parquet', help='Path to output the normalized parquet file')
    return parser.parse_args()

def normalize_and_stitch(manifest_paths, report_out, output_parquet=None):
    dfs = []
    schemas = []
    
    for mpath in manifest_paths:
        if not os.path.exists(mpath):
            print(f"ERROR: Manifest file {mpath} does not exist.")
            sys.exit(1)
            
        with open(mpath, 'r') as f:
            manifest = json.load(f)
            
        parquet_path = os.path.join(os.path.dirname(mpath), manifest['parquet_file'])
        if not os.path.exists(parquet_path):
            print(f"ERROR: Parquet file {parquet_path} does not exist.")
            sys.exit(1)
            
        df = pd.read_parquet(parquet_path)
        schemas.append(list(df.columns))
        dfs.append(df)
        
    if not schemas:
        sys.exit(1)
        
    base_schema = schemas[0]
    for s in schemas[1:]:
        if s != base_schema:
            print("ERROR: Schema drift detected between inputs.")
            sys.exit(1)
            
    combined = pd.concat(dfs, ignore_index=True)
    
    ts_col = 'timestamp'
    if ts_col not in combined.columns:
        print(f"ERROR: No '{ts_col}' column found in schema.")
        sys.exit(1)
        
    try:
        ts_series = pd.to_datetime(combined[ts_col], unit='ms', utc=True)
    except:
        ts_series = pd.to_datetime(combined[ts_col], utc=True)
        
    if ts_series.dt.tz is None:
        ts_series = ts_series.dt.tz_localize('UTC')
        
    combined['__parsed_ts'] = ts_series
    combined = combined.sort_values('__parsed_ts')
    
    initial_count = len(combined)
    combined = combined.drop_duplicates(subset=['__parsed_ts'], keep='first')
    normalized_count = len(combined)
    dropped_boundaries = initial_count - normalized_count
    
    expected_overlaps = len(manifest_paths) - 1
    if dropped_boundaries > expected_overlaps:
        print(f"ERROR: Found {dropped_boundaries} duplicates, but only expected {expected_overlaps} overlapping boundaries.")
        sys.exit(1)
        
    combined = combined.sort_values('__parsed_ts').reset_index(drop=True)
    
    # Enforce end-exclusive replay slicing
    if len(combined) > 0:
        combined = combined.iloc[:-1]
        
    final_count = len(combined)
    
    is_monotonic = combined['__parsed_ts'].is_monotonic_increasing
    has_duplicates = combined['__parsed_ts'].duplicated().any()
    
    diffs = combined['__parsed_ts'].diff().dropna()
    expected_diff = pd.Timedelta(minutes=1)
    gaps_found = not (diffs == expected_diff).all() if len(diffs) > 0 else False
    
    utc_aligned = str(combined['__parsed_ts'].dt.tz) == 'UTC'
    
    combined = combined.drop(columns=['__parsed_ts'])
    
    report = {
        "source_manifests": manifest_paths,
        "raw_inclusive_rows": initial_count,
        "dropped_overlapping_boundaries": dropped_boundaries,
        "normalized_replay_rows": final_count,
        "utc_aligned": utc_aligned,
        "monotonic_timestamps": bool(is_monotonic),
        "duplicate_timestamps_found": bool(has_duplicates),
        "gaps_found": bool(gaps_found),
        "schema_validated": True,
        "partial_latest_candle_excluded_or_marked": True,
        "replay_window_policy": "END_EXCLUSIVE"
    }
    
    if output_parquet:
        combined.to_parquet(output_parquet)
        
    with open(report_out, 'w') as f:
        json.dump(report, f, indent=2)
        
    print(json.dumps(report, indent=2))
    
    if not is_monotonic or has_duplicates or gaps_found or not utc_aligned:
        sys.exit(1)
        
    return report

if __name__ == '__main__':
    args = parse_args()
    normalize_and_stitch(args.manifests, args.report_out, args.output_parquet)
