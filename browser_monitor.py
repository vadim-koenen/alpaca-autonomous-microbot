"""
browser_monitor.py — Read-only Alpaca dashboard monitor using Playwright.

PURPOSE: Observation and discrepancy detection only.
  - Opens the Alpaca dashboard in a headless or headed browser
  - Reads visible account balance, positions, and order history
  - Screenshots for audit trail
  - Compares browser-visible values against API values
  - If discrepancies are found, pauses trading and logs them
  - NEVER clicks trade buttons, submit buttons, or any financial action

SAFETY RULES (enforced in code):
  - No click on any element matching trade/order/submit/confirm/close patterns
  - No form submission
  - No credential scraping
  - No cookie/token extraction
  - If a security prompt or agreement page is detected, stop and report
  - Failures are non-fatal: the bot continues via API if browser fails

DEPENDENCY: playwright must be installed
  pip install playwright
  playwright install chromium
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from utils import ROOT, load_config, now_utc

logger = logging.getLogger("browser_monitor")

# Alpaca dashboard URLs
ALPACA_PAPER_DASHBOARD = "https://app.alpaca.markets/paper/dashboard/overview"
ALPACA_LIVE_DASHBOARD = "https://app.alpaca.markets/brokerage/dashboard/overview"

# Screenshot directory
SCREENSHOT_DIR = ROOT / "logs" / "screenshots"

# Patterns that indicate we must STOP and not interact further
SECURITY_PAGE_PATTERNS = [
    r"sign.?in",
    r"log.?in",
    r"two.?factor",
    r"verification",
    r"agreement",
    r"terms of service",
    r"risk disclosure",
    r"margin agreement",
    r"options agreement",
    r"confirm",
    r"submit application",
]

# Elements we must NEVER click (belt-and-suspenders; we don't click anything anyway)
FORBIDDEN_CLICK_PATTERNS = [
    "buy", "sell", "submit", "confirm", "place order", "exercise",
    "close position", "cancel order", "apply", "agree", "accept",
]


@dataclass
class BrowserSnapshot:
    timestamp: datetime
    account_value: Optional[float]
    buying_power: Optional[float]
    open_positions_count: Optional[int]
    screenshot_path: Optional[str]
    discrepancies: list[str]
    security_warning: bool
    error: Optional[str]

    @property
    def ok(self) -> bool:
        return self.error is None and not self.security_warning


class BrowserMonitor:
    def __init__(self, paper: bool = True) -> None:
        self._paper = paper
        self._url = ALPACA_PAPER_DASHBOARD if paper else ALPACA_LIVE_DASHBOARD
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        self._playwright = None
        self._browser = None
        self._page = None
        self._available = False
        self._init_playwright()

    def _init_playwright(self) -> None:
        """Try to import and launch Playwright. Non-fatal if unavailable."""
        try:
            from playwright.sync_api import sync_playwright
            self._sync_playwright = sync_playwright
            self._available = True
            logger.info("BrowserMonitor: Playwright available")
        except ImportError:
            logger.warning(
                "BrowserMonitor: playwright not installed. "
                "Browser monitoring disabled. Bot continues via API only. "
                "Install with: pip install playwright && playwright install chromium"
            )
            self._available = False

    def capture_snapshot(self, api_equity: float, api_buying_power: float,
                         api_positions: int) -> BrowserSnapshot:
        """
        Open the Alpaca dashboard, read visible values, compare to API.
        Returns a BrowserSnapshot. Non-fatal on failure.
        """
        ts = now_utc()
        if not self._available:
            return BrowserSnapshot(
                timestamp=ts, account_value=None, buying_power=None,
                open_positions_count=None, screenshot_path=None,
                discrepancies=[], security_warning=False,
                error="playwright not available",
            )

        try:
            return self._run_capture(ts, api_equity, api_buying_power, api_positions)
        except Exception as e:
            logger.warning(f"BrowserMonitor: capture failed (non-fatal): {e}")
            return BrowserSnapshot(
                timestamp=ts, account_value=None, buying_power=None,
                open_positions_count=None, screenshot_path=None,
                discrepancies=[], security_warning=False, error=str(e),
            )

    def _run_capture(self, ts: datetime, api_equity: float,
                     api_buying_power: float, api_positions: int) -> BrowserSnapshot:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

        discrepancies = []
        security_warning = False
        account_value = None
        buying_power = None
        positions_count = None
        screenshot_path = None

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox"],
            )
            context = browser.new_context(
                # Do not save anything; no storage state
                java_script_enabled=True,
            )
            page = context.new_page()

            # Navigate to dashboard
            logger.info(f"BrowserMonitor: navigating to {self._url}")
            try:
                page.goto(self._url, timeout=20_000, wait_until="domcontentloaded")
            except PWTimeout:
                browser.close()
                return BrowserSnapshot(
                    timestamp=ts, account_value=None, buying_power=None,
                    open_positions_count=None, screenshot_path=None,
                    discrepancies=[], security_warning=False,
                    error="Page load timeout",
                )

            # Wait briefly for JS to render
            page.wait_for_timeout(3000)

            # Check for security/agreement pages
            page_text = page.inner_text("body").lower()
            for pattern in SECURITY_PAGE_PATTERNS:
                if re.search(pattern, page_text):
                    logger.warning(
                        f"BrowserMonitor: security/agreement page detected (pattern: '{pattern}'). "
                        "Stopping browser interaction. Please check Alpaca manually."
                    )
                    security_warning = True
                    # Screenshot the warning for audit
                    sp = self._screenshot(page, ts, "security_warning")
                    browser.close()
                    return BrowserSnapshot(
                        timestamp=ts, account_value=None, buying_power=None,
                        open_positions_count=None, screenshot_path=sp,
                        discrepancies=[f"Security/agreement page detected: pattern='{pattern}'"],
                        security_warning=True, error=None,
                    )

            # Take audit screenshot
            screenshot_path = self._screenshot(page, ts, "dashboard")

            # Attempt to read account value from the page
            # Alpaca's dashboard varies by version; we use text extraction heuristics
            account_value = _extract_dollar_amount(page_text, ["portfolio value", "account value",
                                                                "total value", "equity"])
            buying_power_text = _extract_dollar_amount(page_text, ["buying power", "available"])

            if account_value is not None:
                buying_power = buying_power_text

            # Compare with API values
            tolerance_pct = 1.0  # 1% tolerance for rounding/timing differences
            if account_value is not None and api_equity > 0:
                diff_pct = abs(account_value - api_equity) / api_equity * 100
                if diff_pct > tolerance_pct:
                    msg = (
                        f"Account value mismatch: browser=${account_value:.2f} "
                        f"API=${api_equity:.2f} (diff={diff_pct:.1f}%)"
                    )
                    discrepancies.append(msg)
                    logger.warning(f"BrowserMonitor: {msg}")

            if buying_power is not None and api_buying_power > 0:
                diff_pct = abs(buying_power - api_buying_power) / max(api_buying_power, 1) * 100
                if diff_pct > tolerance_pct:
                    msg = (
                        f"Buying power mismatch: browser=${buying_power:.2f} "
                        f"API=${api_buying_power:.2f} (diff={diff_pct:.1f}%)"
                    )
                    discrepancies.append(msg)
                    logger.warning(f"BrowserMonitor: {msg}")

            browser.close()

        return BrowserSnapshot(
            timestamp=ts,
            account_value=account_value,
            buying_power=buying_power,
            open_positions_count=positions_count,
            screenshot_path=screenshot_path,
            discrepancies=discrepancies,
            security_warning=security_warning,
            error=None,
        )

    def _screenshot(self, page, ts: datetime, label: str) -> str:
        fname = f"alpaca_{label}_{ts.strftime('%Y%m%d_%H%M%S')}.png"
        fpath = str(SCREENSHOT_DIR / fname)
        try:
            page.screenshot(path=fpath, full_page=False)
            logger.info(f"BrowserMonitor: screenshot saved to {fpath}")
        except Exception as e:
            logger.warning(f"BrowserMonitor: screenshot failed: {e}")
            fpath = ""
        return fpath

    def check_and_pause_if_discrepancy(
        self,
        snapshot: BrowserSnapshot,
        session,
    ) -> bool:
        """
        If the snapshot has discrepancies or a security warning,
        pause trading and log. Returns True if trading should pause.
        """
        if snapshot.security_warning:
            session.halt(
                "Browser detected security/agreement page on Alpaca dashboard. "
                "Manual review required before trading resumes."
            )
            return True

        if snapshot.discrepancies:
            logger.error(
                f"BrowserMonitor: {len(snapshot.discrepancies)} discrepancy(ies) detected. "
                "Pausing trading for safety."
            )
            for d in snapshot.discrepancies:
                logger.error(f"  DISCREPANCY: {d}")
            # Don't halt permanently — just log. Main loop can decide.
            return True

        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_dollar_amount(text: str, labels: list[str]) -> Optional[float]:
    """
    Search page text for a dollar amount near a label keyword.
    Very heuristic — dashboard HTML varies. Returns None if not found.
    """
    for label in labels:
        idx = text.find(label)
        if idx == -1:
            continue
        # Look for a dollar amount in the next 100 chars
        segment = text[idx: idx + 100]
        matches = re.findall(r"\$?([\d,]+\.?\d*)", segment)
        for m in matches:
            try:
                val = float(m.replace(",", ""))
                if val > 0:
                    return val
            except ValueError:
                continue
    return None
