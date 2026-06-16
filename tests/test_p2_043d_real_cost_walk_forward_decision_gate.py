import json
import os
import sys
import subprocess
from pathlib import Path

def test_p2_043d_decision_gate_runs_and_outputs_verdict():
    root = Path(__file__).resolve().parents[1]
    out_path = root / "tests" / "fixtures" / "offline_backtest" / "p2_043d_verdict.json"
    
    # Remove existing verdict file if present
    if out_path.exists():
        out_path.unlink()
        
    script_path = root / "real_cost_walk_forward_decision_gate.py"
    
    # Run the script
    result = subprocess.run([sys.executable, str(script_path), "--output-path", str(out_path)], capture_output=True, text=True)
    
    # Check that it executed successfully
    assert result.returncode == 0, f"Script failed with output: {result.stderr}"
    
    # Verify the output file exists
    assert out_path.exists(), f"Verdict JSON not found at {out_path}"
    
    # Verify the output schema
    data = json.loads(out_path.read_text())
    assert data["schema_version"] == "p2-043d.verdict.v1"
    assert "any_scenario_passed" in data
    assert "recommendation" in data
    assert len(data["scenarios"]) == 4
    
    scenarios = {s["scenario"] for s in data["scenarios"]}
    assert scenarios == {"taker_90m", "maker_post_only", "longer_horizon_4_24h", "cheaper_venue_fee_schedule"}
    
    for s in data["scenarios"]:
        assert "passed_all" in s
        assert "metrics" in s
        assert "pass_criteria" in s
        
    # Clean up after test
    out_path.unlink(missing_ok=True)
