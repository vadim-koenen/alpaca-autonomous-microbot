#!/usr/bin/env python3
"""
setup_app.py — py2app packaging for the Accumulator desktop app (macOS dock app).

Build the .app:
    pip install -r requirements-app.txt py2app
    python3 setup_app.py py2app
    open dist/Accumulator.app        # appears in the dock; drag to /Applications to keep it

This bundles app_main.py + the UI into a native macOS .app with a dock icon. No live
trading: the bundled app proposes plans and simulates fills to local state only.
"""

from setuptools import setup

APP = ["app_main.py"]
DATA_FILES = [("app_ui", ["app_ui/index.html"])]
OPTIONS = {
    "argv_emulation": False,
    "packages": ["allocator_engine", "planner_service", "portfolio_store",
                 "app_api", "app_config", "paper_executor"],
    "includes": ["webview"],
    "plist": {
        "CFBundleName": "Accumulator",
        "CFBundleDisplayName": "Accumulator",
        "CFBundleIdentifier": "com.vadim.accumulator",
        "CFBundleVersion": "0.1.0",
        "NSHighResolutionCapable": True,
        # LSUIElement False => normal app with a dock icon
        "LSUIElement": False,
    },
}

setup(
    app=APP,
    name="Accumulator",
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
