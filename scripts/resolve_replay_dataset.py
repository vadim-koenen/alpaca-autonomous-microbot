import json
import os
import argparse
import sys

# P2-041A Offline Replay Dataset Registry
# Strictly enforces offline-only, read-only behavior for replay-grade data.
# Does not auto-fetch, mutate, or trigger ML training.

OFFLINE_REPLAY_DATASETS = {
    "btc_usd_1m_coinbase_public_7day_20260603_20260610": {
        "dataset_id": "btc_usd_1m_coinbase_public_7day_20260603_20260610",
        "provider": "coinbase_public",
        "symbol": "BTC/USD",
        "timeframe": "1m",
        "range_start": "2026-06-03T23:00:00+00:00",
        "range_end": "2026-06-10T23:00:00+00:00",
        "raw_inclusive_candle_count": 10081,
        "normalized_replay_candle_count": 10080,
        "boundary_semantics": "INCLUSIVE_START_AND_END",
        "replay_window_policy": "END_EXCLUSIVE",
        "coverage_audit_pass": True,
        "coverage_audit_percent": 100.0,
        "manifest_path_hint": "/tmp/BTC_USD/1m/coinbase_public_BTC_USD_1m.manifest.json",
        "output_directory_hint": "/tmp/BTC_USD/1m",
        "generated_data_committed": False,
        "offline_replay_only": True,
        "replay_grade_coverage_approved": True,
        "ml_training_approved": False,
        "ml_live_influence_approved": False,
        "live_influence_approved": False
    }
}

def get_replay_datasets(check_local_files: bool = False, strict: bool = False):
    """
    Returns available offline replay datasets.
    If check_local_files is True, verifies if the hint path exists.
    If strict is True, missing local data will cause a failure (system exit).
    """
    results = {}
    for dataset_id, metadata in OFFLINE_REPLAY_DATASETS.items():
        ds_copy = dict(metadata)
        
        if check_local_files:
            manifest_hint = ds_copy.get("manifest_path_hint")
            if manifest_hint and os.path.exists(manifest_hint):
                ds_copy["local_data_found"] = True
            else:
                ds_copy["local_data_found"] = False
                if strict:
                    print(f"ERROR: Local data missing for {dataset_id} at {manifest_hint}", file=sys.stderr)
                    sys.exit(1)
        
        results[dataset_id] = ds_copy
        
    return results

def main():
    parser = argparse.ArgumentParser(description="Resolve Offline Replay Datasets")
    parser.add_argument("--check-local-files", action="store_true", help="Check if the dataset exists at the hint path")
    parser.add_argument("--strict", action="store_true", help="Fail with non-zero exit if local files are missing (requires --check-local-files)")
    args = parser.parse_args()
    
    datasets = get_replay_datasets(check_local_files=args.check_local_files, strict=args.strict)
    print(json.dumps(datasets, indent=2))

if __name__ == "__main__":
    main()
