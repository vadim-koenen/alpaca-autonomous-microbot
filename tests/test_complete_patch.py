# ADVISORY ONLY — tooling automation, no live trading calls.
# Do not import from: broker, order_manager, risk_manager, main.

"""
Unit tests for complete_patch.py — P2-001G
"""

import pytest
import sys
import tempfile
import os
import re
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from complete_patch import update_handoff

@pytest.fixture
def mock_handoff_file():
    content = """# ACTIVE HANDOFF
**Last updated:** 2026-05-30 03:35 UTC — P2-001E complete  
**Updated by:** Claude  

## 5. Completed Milestones

| ID | Name | Status |
|---|---|---|
| P2-001E | Coinbase exit quality report | DONE / committed `535298c` |

## 6. Git State

```
HEAD: 535298c P2-001E complete
Clean: no dirty tracked files
Recent commits:
  535298c P2-001E complete
```

## 8. Active Patch Queue

### IN PROGRESS
**P2-001F — Maker Order Audit**
Risk class: Class 1 advisory
Status: Next patch.
Executor: Gemini CLI

Files to create:
```
scripts/coinbase_maker_order_audit.py
```

### QUEUED
- **P2-001F — Maker Order Audit**
- **P2-002 commit** — review prediction features

## 11. Automated Status Log
- 2026-05-30 03:35 UTC | head=535298c | P2-001E complete
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / "docs"
        tmp_path.mkdir(parents=True)
        handoff_file = tmp_path / "ACTIVE_HANDOFF.md"
        handoff_file.write_text(content)
        
        # Change working directory for the test
        old_cwd = os.getcwd()
        os.chdir(tmpdir)
        yield handoff_file
        os.chdir(old_cwd)

def test_update_handoff_logic(mock_handoff_file):
    args = MagicMock()
    args.patch = "P2-001F"
    args.title = "Maker Order Audit"
    args.patch_commit = "abcdef123456"
    args.summary = "6/6 entries likely passive-priced"
    args.next = "None — awaiting review"
    args.dry_run = False

    update_handoff(args)
    
    updated_content = mock_handoff_file.read_text()
    
    # Check Milestone row
    assert "| P2-001F | Maker Order Audit | DONE / committed `abcdef1` |" in updated_content
    
    # Check Section 6
    assert "Latest functional patch commit: abcdef1" in updated_content
    assert "Latest handoff commit: PENDING" in updated_content
    assert "abcdef1 P2-001F: Maker Order Audit" in updated_content
    
    # Check Section 8
    assert "### IN PROGRESS\n**None — awaiting review**" in updated_content
    assert "- **P2-001F — Maker Order Audit**" not in updated_content
    
    # Check Status Log
    assert "| head=abcdef1 | P2-001F complete; 6/6 entries likely passive-priced" in updated_content

def test_update_handoff_update_existing_milestone(mock_handoff_file):
    # First add it
    args = MagicMock()
    args.patch = "P2-001F"
    args.title = "Maker Order Audit"
    args.patch_commit = "abcdef123456"
    args.summary = "Initial"
    args.next = "None"
    args.dry_run = False
    update_handoff(args)
    
    # Now update it with different commit
    args.patch_commit = "fedcba987654"
    args.summary = "Updated summary"
    update_handoff(args)
    
    updated_content = mock_handoff_file.read_text()
    assert "| P2-001F | Maker Order Audit | DONE / committed `fedcba9` |" in updated_content
    # Ensure it didn't duplicate the row
    assert updated_content.count("| P2-001F |") == 1

def test_dry_run_no_write(mock_handoff_file):
    original_content = mock_handoff_file.read_text()
    args = MagicMock()
    args.patch = "P2-001F"
    args.title = "Maker Order Audit"
    args.patch_commit = "abcdef123456"
    args.summary = "Dry run test"
    args.next = "None"
    args.dry_run = True

    update_handoff(args)
    
    assert mock_handoff_file.read_text() == original_content

def test_placeholder_cleanup(mock_handoff_file):
    # Add a placeholder to the mock file
    content = mock_handoff_file.read_text()
    content += "\nSome text with REPLACE_WITH_HEAD placeholder."
    mock_handoff_file.write_text(content)
    
    args = MagicMock()
    args.patch = "P2-001F"
    args.title = "Maker Order Audit"
    args.patch_commit = "abcdef123456"
    args.summary = "Placeholder test"
    args.next = "None"
    args.dry_run = False
    
    update_handoff(args)
    
    updated_content = mock_handoff_file.read_text()
    assert "REPLACE_WITH_HEAD" not in updated_content
    assert "abcdef1" in updated_content

def test_no_forbidden_imports():
    import complete_patch as module
    forbidden = ['broker', 'broker_alpaca', 'broker_coinbase', 'order_manager',
                 'risk_manager', 'main']
    source = (Path(__file__).parent.parent / 'scripts' / 'complete_patch.py').read_text(encoding='utf-8')
    for forbidden_module in forbidden:
        assert f"import {forbidden_module}" not in source
        assert f"from {forbidden_module}" not in source
    
    for name in dir(module):
        if name == 'cli_main': continue
        assert name not in forbidden

if __name__ == "__main__":
    pytest.main([__file__, '-v'])
