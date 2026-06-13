import json
import os
import argparse
import sys

from resolve_replay_dataset import get_replay_datasets

def run_current_strategy_replay(dataset_id: str, output_dir: str = "/tmp"):
    """
    Offline wrapper for current live strategy.

    STATUS: STUBBED / BLOCKED
    Reason: The current `strategy_crypto.py` logic cannot be fully decoupled from live event loops
    without invasive rewrites that risk mutating or breaking production behavior.

    To maintain strict offline safety and avoid overbuilding, this harness outputs a safe, zeroed
    placeholder report. This allows the P2-041D scoring layer to be built and tested.
    """
    datasets = get_replay_datasets(check_local_files=False, strict=False)

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

    if ds.get("ml_training_approved") or ds.get("live_influence_approved"):
        print(f"ERROR: Dataset {dataset_id} violates offline safety blocks.", file=sys.stderr)
        sys.exit(1)
        return None

    report = {
        "dataset_id": dataset_id,
        "strategy_name": "current_live_strategy",
        "trades": 0,
        "gross_pnl": 0.0,
        "fees": 0.0,
        "net_pnl": 0.0,
        "win_rate": 0.0,
        "notes": [
            "STUBBED: Replay could not be fully decoupled from live event loop without invasive rewrites.",
            "Placeholder report generated to unblock P2-041D scoring layer development."
        ],
        "ml_training_started": False,
        "live_influence_enabled": False,
        "risk_caps_changed": False
    }

    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, f"replay_report_{dataset_id}.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Offline strategy replay report generated at: {report_path}")
    print(json.dumps(report, indent=2))
    return report

def main():
    parser = argparse.ArgumentParser(description="Run Offline Strategy Replay (Stubbed)")
    parser.add_argument("--dataset-id", type=str, default="btc_usd_1m_coinbase_public_7day_20260603_20260610")
    args = parser.parse_args()

    run_current_strategy_replay(args.dataset_id)

if __name__ == "__main__":
    main()
