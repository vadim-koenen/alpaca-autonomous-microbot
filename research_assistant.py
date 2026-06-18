#!/usr/bin/env python3
"""
research_assistant.py — P2-046U: honest, data-driven asset research (NOT a stock picker).

Given a ticker, it pulls real historical data and reports what the asset IS and how it would FIT
your portfolio: annualized return, volatility, max drawdown, and correlation to your current basket,
in plain English. It helps YOU decide what to add to your fixed basket — an allocation decision.

HARD RULE (the lesson of this whole project): it NEVER predicts returns, NEVER says buy/sell, NEVER
claims an edge. Retail directional prediction has no edge (proven here 3×). This module educates and
diagnoses; it does not forecast. Every output carries `is_recommendation=False` + a disclaimer.

GOVERNANCE: read-only research. No orders, no live authorization. Pure analytics are unit-tested.
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Dict, List, Optional

TRADING_DAYS = 252
DISCLAIMER = ("Educational only. Based on historical data — NOT a prediction, recommendation, or "
              "buy/sell signal. Past performance does not indicate future results.")


def returns_from_closes(closes: List[float]) -> List[float]:
    return [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes)) if closes[i - 1] > 0]


def annualized_return(closes: List[float]) -> float:
    if len(closes) < 2 or closes[0] <= 0:
        return 0.0
    years = len(closes) / TRADING_DAYS
    if years <= 0:
        return 0.0
    return round(((closes[-1] / closes[0]) ** (1 / years) - 1.0) * 100, 2)


def annualized_vol(closes: List[float]) -> float:
    r = returns_from_closes(closes)
    if len(r) < 2:
        return 0.0
    return round(statistics.pstdev(r) * math.sqrt(TRADING_DAYS) * 100, 2)


def max_drawdown(closes: List[float]) -> float:
    peak = float("-inf")
    mdd = 0.0
    for c in closes:
        peak = max(peak, c)
        if peak > 0:
            mdd = max(mdd, (peak - c) / peak)
    return round(mdd * 100, 2)


def pearson(a: List[float], b: List[float]) -> Optional[float]:
    n = min(len(a), len(b))
    if n < 2:
        return None
    a, b = a[:n], b[:n]
    ma, mb = statistics.fmean(a), statistics.fmean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    if da == 0 or db == 0:
        return None
    return round(num / (da * db), 3)


def aligned_returns(series_a: Dict[str, float], series_b: Dict[str, float]):
    """Daily returns for both series over their common, sorted dates."""
    common = sorted(set(series_a) & set(series_b))
    ca = [series_a[d] for d in common]
    cb = [series_b[d] for d in common]
    return returns_from_closes(ca), returns_from_closes(cb)


def _role(vol: float) -> str:
    if vol < 5:
        return "defensive (cash/bond-like — low volatility)"
    if vol < 18:
        return "core (broad equity / dividend income)"
    if vol < 40:
        return "growth (equity — higher swings)"
    return "high-risk (crypto/commodity — large swings)"


def _fit(corr: Optional[float]) -> str:
    if corr is None:
        return "Not enough overlapping history to assess fit with your basket."
    if corr < 0.4:
        return f"Low correlation ({corr}) to your basket — would ADD diversification."
    if corr < 0.7:
        return f"Moderate correlation ({corr}) to your basket — some overlap."
    return f"High correlation ({corr}) to your basket — similar to what you already hold."


def research_asset(symbol: str, name: str, asset_series: Dict[str, float],
                   basket_series: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Build an honest briefing from real price history. Pure (data injected)."""
    dates = sorted(asset_series)
    closes = [asset_series[d] for d in dates]
    if len(closes) < 30:
        return {"symbol": symbol, "name": name, "error": "insufficient_history",
                "is_recommendation": False, "disclaimer": DISCLAIMER}

    vol = annualized_vol(closes)
    corr = None
    if basket_series:
        ra, rb = aligned_returns(asset_series, basket_series)
        if len(ra) >= 30:
            corr = pearson(ra, rb)

    return {
        "symbol": symbol,
        "name": name,
        "n_days": len(closes),
        "from": dates[0], "to": dates[-1],
        "last_price": round(closes[-1], 2),
        "annualized_return_pct": annualized_return(closes),
        "annualized_volatility_pct": vol,
        "max_drawdown_pct": max_drawdown(closes),
        "correlation_to_basket": corr,
        "role": _role(vol),
        "fit": _fit(corr),
        "is_recommendation": False,
        "disclaimer": DISCLAIMER,
    }
