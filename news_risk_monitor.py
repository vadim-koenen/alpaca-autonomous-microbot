#!/usr/bin/env python3
"""
news_risk_monitor.py — P2-046C: news as ADVISORY + RISK circuit-breaker (NEVER an entry signal).

P2-045 falsified news as a return predictor: it does NOT tell you when to buy. So this module
gives news the only two honest jobs left:
  1. ADVISORY  — surface recent headlines for the human, for awareness only.
  2. RISK ALERT — flag named catastrophic events (hack, depeg, insolvency, ban, fraud, ...) for a
     held/watched asset, and RECOMMEND pausing auto-contributions until the human reviews.

It produces NO buy/sell signal, never auto-trades, and never auto-sells. `should_pause` is a
recommendation to a human, who decides. The scan is pure and unit-tested; fetching is separate.

GOVERNANCE: advisory only. authorizes_live=False. No broker, no orders, no runtime mutation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Named catastrophic-event terms. Matching one for a held/watched asset => RISK_ALERT + pause rec.
CRITICAL_TERMS = (
    "hack", "hacked", "exploit", "breach", "stolen", "drained", "depeg", "de-peg",
    "insolven", "bankrupt", "halt withdrawal", "freeze withdrawal", "frozen", "fraud",
    "ponzi", "rug pull", "rugpull", "delist", "delisting", "collapse", "sec charges",
    "sec sues", "indict", "seized", "shut down", "shutdown", "liquidation cascade",
)
# Elevated-but-not-critical terms => WATCH (informational, no pause).
ELEVATED_TERMS = (
    "investigation", "probe", "subpoena", "lawsuit", "sued", "downgrade", "outage",
    "glitch", "warning", "scrutiny", "ban ", "banned", "restrict",
)

ADVISORY = "ADVISORY"
WATCH = "WATCH"
RISK_ALERT = "RISK_ALERT"


def _matched(text: str, terms) -> Optional[str]:
    t = (text or "").lower()
    for term in terms:
        if term in t:
            return term.strip()
    return None


def classify_headline(headline: str, summary: str = "") -> Dict[str, Any]:
    """Return {severity, matched}. Pure."""
    text = f"{headline} {summary}"
    m = _matched(text, CRITICAL_TERMS)
    if m:
        return {"severity": RISK_ALERT, "matched": m}
    m = _matched(text, ELEVATED_TERMS)
    if m:
        return {"severity": WATCH, "matched": m}
    return {"severity": ADVISORY, "matched": None}


def _symbol_root(sym: str) -> str:
    return (sym or "").split("/")[0].upper()


def scan_news(
    items: List[Dict[str, Any]],
    watch_symbols: Optional[List[str]] = None,
    *,
    max_advisory: int = 20,
) -> Dict[str, Any]:
    """Classify a list of news items. `items`: {date, symbol, headline, summary}.
    `watch_symbols`: only RISK_ALERT on these (the held basket); None = all. Pure, no I/O."""
    watch = {_symbol_root(s) for s in watch_symbols} if watch_symbols else None
    alerts: List[Dict[str, Any]] = []
    watches: List[Dict[str, Any]] = []
    advisory: List[Dict[str, Any]] = []

    for it in items:
        sym = it.get("symbol", "")
        root = _symbol_root(sym)
        relevant = (watch is None) or (root in watch) or (root == "")
        c = classify_headline(it.get("headline", ""), it.get("summary", ""))
        row = {"date": it.get("date", ""), "symbol": sym,
               "headline": it.get("headline", ""), "matched": c["matched"],
               "severity": c["severity"]}
        if c["severity"] == RISK_ALERT and relevant:
            alerts.append(row)
        elif c["severity"] == WATCH and relevant:
            watches.append(row)
        else:
            advisory.append(row)

    by_symbol: Dict[str, int] = {}
    for r in alerts:
        by_symbol[_symbol_root(r["symbol"])] = by_symbol.get(_symbol_root(r["symbol"]), 0) + 1

    return {
        "schema": "p2_046c_news_risk/v1",
        "n_scanned": len(items),
        "risk_alerts": alerts,
        "watches": watches[:max_advisory],
        "advisory": advisory[:max_advisory],
        "n_risk_alerts": len(alerts),
        "n_watches": len(watches),
        "alerts_by_symbol": by_symbol,
        # RECOMMENDATION to a human only — never an automatic action.
        "should_pause_recommended": len(alerts) > 0,
        "authorizes_live": False,
        "note": "Advisory + risk only. News is NOT a buy/sell signal (P2-045). Pause is a "
                "recommendation; the human decides. Never auto-trades, never auto-sells.",
    }


def render_text(scan: Dict[str, Any]) -> str:
    lines = [f"News risk scan · {scan['n_scanned']} items · "
             f"{scan['n_risk_alerts']} alerts · {scan['n_watches']} watches"]
    if scan["should_pause_recommended"]:
        lines.append("⚠ RISK_ALERT — review before next contribution (pause recommended):")
        for a in scan["risk_alerts"][:10]:
            lines.append(f"  [{a['date']}] {a['symbol']} — {a['headline']}  (matched: {a['matched']})")
    else:
        lines.append("No critical events detected for the watched basket.")
    return "\n".join(lines)
