#!/usr/bin/env python3
"""
app_main.py — P2-046F: desktop app entrypoint (pywebview) + headless CLI.

Runs the accumulator/allocator as a native macOS window (pywebview), or headless from
the terminal for verification. The window loads app_ui/index.html and hands it an
`AccumulatorAPI` instance as `js_api`, so the UI calls Python directly (no server).

  GUI  (on the Mac):   python3 app_main.py            # opens the dock-app window
  CLI  (headless):     python3 app_main.py --cli      # prints status + this week's plan
                       python3 app_main.py --cli --approve   # simulate-approve one period

Package into a dock app:  python3 setup_app.py py2app   (see DESKTOP_APP_ARCHITECTURE doc)

GOVERNANCE: proposals + simulated local state only. No broker, no live authorization.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import planner_service as ps
import app_config as cfg
from app_api import AccumulatorAPI

UI_INDEX = Path(__file__).parent / "app_ui" / "index.html"
CONFIG_PATH = Path("app_config.json")          # optional; falls back to Conservative default


def build_api() -> AccumulatorAPI:
    return AccumulatorAPI(config_path=CONFIG_PATH if CONFIG_PATH.exists() else None)


def run_cli(approve: bool) -> int:
    api = build_api()
    st = api.get_status()
    flag = "ARMED (no live)" if st["stop_trading_armed"] else "absent"
    print(f"STOP_TRADING: {flag} · live_enabled={st['live_enabled']}")
    print(f"Portfolio value: ${st['portfolio_value']:.2f}  cash ${st['cash']:.2f}\n")
    plan = api.get_plan()
    print(ps.render_plan_text(plan))
    if approve:
        res = api.approve_plan_paper()
        print(f"\n[approved · simulated] {res['n_fills']} fills · "
              f"new value ${res['portfolio_value']:.2f} (no broker contacted)")
    return 0


def run_gui() -> int:
    try:
        import webview  # pywebview
    except ImportError:
        print("pywebview not installed. Run: pip install pywebview\n"
              "(or use the headless CLI: python3 app_main.py --cli)", file=sys.stderr)
        return 1
    api = build_api()
    webview.create_window("Accumulator", url=str(UI_INDEX), js_api=api,
                          width=920, height=720, min_size=(720, 560))
    webview.start()
    return 0


def set_paper(enabled: bool) -> int:
    c = cfg.load_config(CONFIG_PATH) if CONFIG_PATH.exists() else cfg.default_config()
    c.live_paper = enabled
    cfg.save_config(c, CONFIG_PATH)
    print(f"paper mode {'ENABLED' if enabled else 'disabled'} in {CONFIG_PATH}.")
    if enabled:
        print("Add ALPACA_PAPER_API_KEY / ALPACA_PAPER_SECRET_KEY to .env "
              "(generate at app.alpaca.markets → Paper Trading → API Keys).")
        print("STOP_TRADING must be absent for paper to activate.")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Accumulator/Allocator desktop app")
    p.add_argument("--cli", action="store_true", help="Headless: print status + plan.")
    p.add_argument("--approve", action="store_true", help="(with --cli) approve one period.")
    p.add_argument("--enable-paper", action="store_true", help="Switch to Alpaca paper mode.")
    p.add_argument("--disable-paper", action="store_true", help="Switch back to simulate mode.")
    args = p.parse_args(argv)
    if args.enable_paper:
        return set_paper(True)
    if args.disable_paper:
        return set_paper(False)
    return run_cli(args.approve) if args.cli else run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
