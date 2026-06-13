import json
import os
import argparse
import sys

from resolve_replay_dataset import get_replay_datasets

def run_no_trade_baseline(dataset_id: str, check_local_files: bool = False, output_dir: str = "/tmp"):
    """
    Computes a strict 0-trade baseline for the given approved offline dataset.
    This baseline serves as the required benchmark that all actual strategies must beat after fees.
    """
    datasets = get_replay_datasets(check_local_files=check_local_files, strict=False)

    if dataset_id not in datasets:
        print(f"ERROR: Dataset {dataset_id} not found in offline registry.", file=sys.stderr)
        sys.exit(1)
        return None

    ds = datasets[dataset_id]

    # Assert offline guardrails
    if not ds.get("offline_replay_only"):
        print(f"ERROR: Dataset {dataset_id} is not approved for offline replay.", file=sys.stderr)
        sys.exit(1)
        return None

    # If strictly requesting check, but data is missing, we log it, but baseline calculation is still valid (it's 0)
    if check_local_files and not ds.get("local_data_found"):
        print(f"WARNING: Local data missing for {dataset_id}. Baseline can still be computed.", file=sys.stderr)

    baseline_report = {
        "dataset_id": dataset_id,
        "strategy_name": "no_trade_baseline",
        "trades": 0,
        "gross_pnl": 0.0,
        "fees": 0.0,
        "net_pnl": 0.0,
        "win_rate": 0.0,
        "notes": [
            "Strict 0-trade baseline.",
            "All candidate strategies must produce a net_pnl strictly greater than this after fees."
        ],
        "ml_training_started": False,
        "live_influence_enabled": False
    }

    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, f"baseline_report_{dataset_id}.json")
    with open(report_path, "w") as f:
        json.dump(baseline_report, f, indent=2)

    print(f"Baseline report generated at: {report_path}")
    print(json.dumps(baseline_report, indent=2))
    return baseline_report

def main():
    parser = argparse.ArgumentParser(description="Run No-Trade Baseline Replay")
    parser.add_argument("--dataset-id", type=str, default="btc_usd_1m_coinbase_public_7day_20260603_20260610", help="Registered offline dataset ID")
    parser.add_argument("--check-local-files", action="store_true", help="Check if the dataset exists locally")
    args = parser.parse_args()

    run_no_trade_baseline(args.dataset_id, check_local_files=args.check_local_files)

if __name__ == "__main__":
    main()
