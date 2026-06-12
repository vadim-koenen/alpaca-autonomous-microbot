import os
import pathlib
import sys
import tempfile
import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

from scripts import p2_040i_smoke_test as smoke_test

def test_p2_040i_smoke_runs_successfully():
    # It should run successfully without raising SystemExit and produce a report in /tmp
    # But to avoid polluting /tmp in tests, we could just monkeypatch the output or let it write.
    # The script uses a temp directory internally for synthetic data, and outputs to /tmp/p2_040i_smoke_report.json
    try:
        smoke_test.main()
    except SystemExit:
        pytest.fail("Smoke test exited with error")
    
    assert os.path.exists('/tmp/p2_040i_smoke_report.json')
