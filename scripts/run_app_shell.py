#!/usr/bin/env python3
"""
Launcher for the Investing Bot App Shell.
"""

import sys
from pathlib import Path

# Add repo root to sys.path for potential imports
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

from app_shell.server import run_server

if __name__ == "__main__":
    try:
        run_server()
    except Exception as e:
        print(f"Error starting app shell: {e}")
        sys.exit(1)
