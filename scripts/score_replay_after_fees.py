import json
import os
import argparse
import sys

def score_replay(baseline_path: str, candidate_path: str, output_dir: str = "/tmp"):
    """
    Offline scoring layer that evaluates replay outputs against fees/slippage
    and the no-trade baseline. Fails closed (returns false) if data is missing,
    blocked, or malformed.
    """

    def fail_closed(reason: str):
        print(f"FAIL CLOSED: {reason}", file=sys.stderr)
        return generate_score(False, reason, None, None)

    if not os.path.exists(baseline_path):
        return fail_closed(f"Baseline report missing at {baseline_path}")

    if not os.path.exists(candidate_path):
        return fail_closed(f"Candidate report missing at {candidate_path}")

    try:
        with open(baseline_path, "r") as f:
            baseline = json.load(f)
        with open(candidate_path, "r") as f:
            candidate = json.load(f)
    except Exception as e:
        return fail_closed(f"Malformed JSON: {e}")

    # Check for STUBBED or BLOCKED string in notes to fail closed
    notes = candidate.get("notes", [])
    for note in notes:
        if "STUBBED" in note or "BLOCKED" in note:
            return fail_closed("Candidate replay is stubbed or blocked")

    # Ensure required metrics exist
    required = ["trades", "gross_pnl", "fees", "net_pnl"]
    for req in required:
        if req not in baseline:
            return fail_closed(f"Baseline missing {req}")
        if req not in candidate:
            return fail_closed(f"Candidate missing {req}")

    try:
        base_net = float(baseline["net_pnl"])
        cand_net = float(candidate["net_pnl"])
        cand_fees = float(candidate["fees"])
        cand_gross = float(candidate["gross_pnl"])
    except ValueError:
        return fail_closed("Metrics must be numeric")

    # Fails closed on missing fees/slippage (implied by 0 fees when trades > 0)
    if candidate["trades"] > 0 and cand_fees <= 0:
        return fail_closed("Missing fee/slippage assumptions for active trades")

    beats = cand_net > base_net

    return generate_score(beats, "Scoring complete", baseline, candidate, output_dir)

def generate_score(beats: bool, message: str, baseline: dict, candidate: dict, output_dir: str = "/tmp"):
    score = {
        "beats_no_trade_after_fees": beats,
        "message": message,
        "gross_pnl": candidate.get("gross_pnl", 0) if candidate else 0,
        "estimated_fees": candidate.get("fees", 0) if candidate else 0,
        "estimated_slippage": candidate.get("slippage", 0) if candidate else 0,
        "net_pnl": candidate.get("net_pnl", 0) if candidate else 0,
        "trade_count": candidate.get("trades", 0) if candidate else 0,
        "win_rate": candidate.get("win_rate", 0) if candidate else 0,
        "timeout_rate": candidate.get("timeout_rate", 0) if candidate else 0,
        "baseline_net_pnl": baseline.get("net_pnl", 0) if baseline else 0
    }

    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, "score_report.json")
    with open(report_path, "w") as f:
        json.dump(score, f, indent=2)

    print(json.dumps(score, indent=2))
    return score

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=str, required=True, help="Path to baseline JSON")
    parser.add_argument("--candidate", type=str, required=True, help="Path to candidate JSON")
    args = parser.parse_args()

    score_replay(args.baseline, args.candidate)

if __name__ == "__main__":
    main()
