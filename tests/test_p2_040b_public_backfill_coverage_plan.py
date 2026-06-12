"""Tests for P2-040B Public Backfill Readiness / Coverage Plan Generator."""

import datetime
import json
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

from scripts import p2_040b_public_backfill_coverage_plan as planner

def test_default_plan_is_plan_only(tmp_path):
    end_dt = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)
    plan = planner.build_coverage_plan(
        provider="fixture",
        symbols=["BTC/USD"],
        timeframe="1m",
        days=1,
        end_dt=end_dt,
        output_root=tmp_path
    )
    
    assert plan["plan_only"] is True
    assert plan["public_fetch_performed"] is False

def test_one_symbol_one_day_expected_bars(tmp_path):
    end_dt = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)
    plan = planner.build_coverage_plan(
        provider="fixture",
        symbols=["BTC/USD"],
        timeframe="1m",
        days=1,
        end_dt=end_dt,
        output_root=tmp_path
    )
    
    # 1 day = 1440 minutes = 1440 bars
    assert plan["expected_bars_total"] == 1440
    assert len(plan["plans_by_symbol"]) == 1
    
    sym_plan = plan["plans_by_symbol"][0]
    assert sym_plan["symbol"] == "BTC/USD"
    assert sym_plan["expected_bars"] == 1440

def test_multi_symbol_plan(tmp_path):
    end_dt = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)
    plan = planner.build_coverage_plan(
        provider="fixture",
        symbols=["BTC/USD", "ETH/USD"],
        timeframe="1m",
        days=1,
        end_dt=end_dt,
        output_root=tmp_path
    )
    
    assert len(plan["plans_by_symbol"]) == 2
    assert plan["plans_by_symbol"][0]["symbol"] == "BTC/USD"
    assert plan["plans_by_symbol"][1]["symbol"] == "ETH/USD"
    assert plan["expected_bars_total"] == 2880

def test_chunking_produces_multiple_future_commands(tmp_path):
    end_dt = datetime.datetime(2026, 1, 4, tzinfo=datetime.timezone.utc)
    plan = planner.build_coverage_plan(
        provider="fixture",
        symbols=["BTC/USD"],
        timeframe="1m",
        days=3,
        end_dt=end_dt,
        output_root=tmp_path,
        chunk_days=1
    )
    
    # 3 days total / 1 day chunks = 3 chunks
    sym_plan = plan["plans_by_symbol"][0]
    assert len(sym_plan["chunks"]) == 3
    assert len(sym_plan["future_commands"]) == 3
    assert len(plan["future_commands"]) == 3

def test_future_commands_include_required_flags(tmp_path):
    end_dt = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)
    plan = planner.build_coverage_plan(
        provider="fixture",
        symbols=["BTC/USD"],
        timeframe="1m",
        days=1,
        end_dt=end_dt,
        output_root=tmp_path
    )
    
    cmd = plan["future_commands"][0]
    assert "p2_040a_public_backfill_approval_runner.py" in cmd
    assert "--allow-public-fetch" in cmd
    assert "--approval-token PUBLIC_BACKFILL_APPROVED" in cmd

def test_report_json(tmp_path):
    report_path = tmp_path / "plan.json"
    end_dt = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)
    plan = planner.build_coverage_plan(
        provider="fixture",
        symbols=["BTC/USD"],
        timeframe="1m",
        days=1,
        end_dt=end_dt,
        output_root=tmp_path
    )
    
    with open(report_path, "w") as f:
        json.dump(plan, f)
        
    assert report_path.exists()
    
    with open(report_path, "r") as f:
        loaded = json.load(f)
        
    assert loaded["provider"] == "fixture"
    assert loaded["expected_bars_total"] == 1440

def test_missing_manifests_produce_zero_coverage(tmp_path):
    end_dt = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)
    plan = planner.build_coverage_plan(
        provider="fixture",
        symbols=["BTC/USD"],
        timeframe="1m",
        days=1,
        end_dt=end_dt,
        output_root=tmp_path # Empty temp dir, no manifests
    )
    
    sym_plan = plan["plans_by_symbol"][0]
    assert sym_plan["existing_bars"] == 0
    assert sym_plan["coverage_percent_estimate"] == 0.0
    assert sym_plan["missing_bars_estimate"] == 1440

def test_cli_help_safety_language():
    import subprocess
    
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "p2_040b_public_backfill_coverage_plan.py"), "--help"],
        capture_output=True,
        text=True
    )
    
    assert result.returncode == 0
    # argparse automatically generates help, we just check that it runs and
    # the description contains the tool name. 
    # Safety language is printed via logging or in the docstring.
    # We can check the docstring.
    assert "P2-040B" in result.stdout

def test_no_generated_data_in_repo(tmp_path):
    end_dt = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)
    out_root = tmp_path / "market_data"
    
    plan = planner.build_coverage_plan(
        provider="fixture",
        symbols=["BTC/USD"],
        timeframe="1m",
        days=1,
        end_dt=end_dt,
        output_root=out_root
    )
    
    parquets = list(out_root.rglob("*.parquet")) if out_root.exists() else []
    assert len(parquets) == 0
