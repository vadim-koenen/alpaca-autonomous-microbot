#!/usr/bin/env python3
"""
notifier.py — P2-046K: Level-2 notifications (native macOS, no deps).

Composes and sends the weekly accumulator notification: a contribution reminder + any news
RISK alert. This is the "advisory backbone" — the app reminds you to review & approve; it does
NOT auto-trade. Run by a launchd job on a weekly schedule (see com.vadim.accumulator-weekly.plist).

GOVERNANCE: notifications only. No broker, no orders. The `runner` is injected so it's testable
without firing real notifications.
"""

from __future__ import annotations

import subprocess
from typing import Any, Callable, Dict, List


def macos_notify(title: str, message: str, *, subtitle: str = "",
                 runner: Callable[..., Any] = subprocess.run) -> bool:
    """Show a native macOS notification via osascript. Returns True on success."""
    # osascript string literals: escape backslashes and double quotes.
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')
    script = f'display notification "{esc(message)}" with title "{esc(title)}"'
    if subtitle:
        script += f' subtitle "{esc(subtitle)}"'
    try:
        runner(["osascript", "-e", script], check=True,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def compose_weekly_message(plan: Dict[str, Any], news: Dict[str, Any]) -> Dict[str, str]:
    """Build the weekly notification text from a period plan + a news risk scan. Pure."""
    contrib = plan.get("contribution", 0.0)
    n_orders = len(plan.get("orders", []))
    alerts = int(news.get("n_risk_alerts", 0))
    title = "Accumulator — weekly contribution ready"
    body = f"${contrib:.0f} across {n_orders} assets. Open the app to review & approve."
    if alerts > 0:
        syms = ", ".join(sorted(news.get("alerts_by_symbol", {}).keys())) or "your basket"
        subtitle = f"⚠ {alerts} risk alert(s): {syms} — consider pausing"
    else:
        subtitle = "No risk alerts."
    return {"title": title, "subtitle": subtitle, "message": body}
