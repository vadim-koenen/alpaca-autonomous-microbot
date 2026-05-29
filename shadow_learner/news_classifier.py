"""Deterministic news/theme classifier for advisory shadow learning."""

from __future__ import annotations

import re
from typing import Any

SUPPORTED_THEMES = {
    "etf_flow",
    "etf_launch",
    "tokenization",
    "stablecoin_payments",
    "regulatory",
    "institutional_adoption",
    "macro_risk",
    "chain_activity",
    "exchange_listing",
    "funding_or_outflows",
    "security_exploit",
    "market_downtrend",
    "asset_specific_catalyst",
    "unknown",
}

SYMBOL_ALIASES = {
    "BTC": ("btc", "bitcoin"),
    "ETH": ("eth", "ether", "ethereum"),
    "SOL": ("sol", "solana"),
    "XLM": ("xlm", "stellar"),
    "BNB": ("bnb",),
    "HYPE": ("hype", "hyperliquid"),
    "USDC": ("usdc",),
    "USDT": ("usdt", "tether"),
    "STABLECOINS": ("stablecoin", "stablecoins"),
}

POSITIVE_WORDS = {
    "adoption",
    "approval",
    "approved",
    "gain",
    "gains",
    "growth",
    "inflow",
    "inflows",
    "launch",
    "rally",
    "surge",
    "surges",
    "strength",
    "strong",
    "tokenization",
}

NEGATIVE_WORDS = {
    "below",
    "downtrend",
    "drop",
    "drops",
    "exploit",
    "fall",
    "falls",
    "hack",
    "outflow",
    "outflows",
    "risk",
    "selloff",
    "slips",
    "weakness",
}


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def extract_symbols(title: str, summary: str = "") -> list[str]:
    text = f"{title} {summary}".lower()
    symbols: list[str] = []
    for symbol, aliases in SYMBOL_ALIASES.items():
        for alias in aliases:
            pattern = rf"(?<![a-z0-9]){re.escape(alias.lower())}(?![a-z0-9])"
            if re.search(pattern, text):
                symbols.append(symbol)
                break
    return symbols


def classify_news(title: str, summary: str = "") -> dict[str, Any]:
    """Classify one news item with deterministic keyword rules."""
    text = f"{title} {summary}".lower()
    symbols = extract_symbols(title, summary)
    themes: set[str] = set()
    sectors: set[str] = set()

    if _contains_any(text, ("tokenization", "tokenized", "dtcc", "rwa", "real-world asset")):
        themes.add("tokenization")
        sectors.add("tokenization")
    if "etf" in text and _contains_any(text, ("inflow", "inflows", "flow", "flows", "outflow", "outflows")):
        themes.add("etf_flow")
        sectors.add("etf")
    if "etf" in text and _contains_any(text, ("launch", "launched", "filed", "files", "application", "debut", "vaneck")):
        themes.add("etf_launch")
        sectors.add("etf")
    if _contains_any(text, ("stablecoin", "stablecoins", "usdc", "usdt", "stripe", "tempo")) and _contains_any(
        text, ("payment", "payments", "transaction", "transactions", "settlement", "merchant")
    ):
        themes.add("stablecoin_payments")
        sectors.add("payments")
    if _contains_any(text, ("sec", "cftc", "regulator", "regulatory", "lawsuit", "court", "senate", "bill")):
        themes.add("regulatory")
    if _contains_any(text, ("institutional", "institution", "wall street", "bank", "blackrock", "fidelity", "dtcc", "vaneck")):
        themes.add("institutional_adoption")
        sectors.add("institutional")
    if _contains_any(text, ("fed", "rates", "inflation", "macro", "recession", "dollar", "below $", "below 75")):
        themes.add("macro_risk")
    if _contains_any(text, ("chain activity", "onchain", "on-chain", "transactions", "active addresses", "tvl", "network activity")):
        themes.add("chain_activity")
    if _contains_any(text, ("listing", "listed", "coinbase listing", "binance listing", "kraken listing")):
        themes.add("exchange_listing")
    if _contains_any(text, ("funding", "raises", "raised", "outflow", "outflows", "withdrawals")):
        themes.add("funding_or_outflows")
    if _contains_any(text, ("hack", "exploit", "exploited", "bridge attack", "drained", "phishing")):
        themes.add("security_exploit")
    if _contains_any(text, ("downtrend", "selloff", "below", "falls", "drops", "slips", "loses")):
        themes.add("market_downtrend")
    if symbols and _contains_any(
        text,
        ("surge", "surges", "rally", "gains", "catalyst", "strength", "divergent", "amid", "launch", "inflows"),
    ):
        themes.add("asset_specific_catalyst")

    if not themes:
        themes.add("unknown")

    words = re.findall(r"[a-z]+", text)
    positive = sum(1 for word in words if word in POSITIVE_WORDS)
    negative = sum(1 for word in words if word in NEGATIVE_WORDS)
    if "security_exploit" in themes:
        negative += 2
    if "market_downtrend" in themes:
        negative += 1
    if "tokenization" in themes or "institutional_adoption" in themes:
        positive += 1
    sentiment = _clamp((positive - negative) / max(3.0, positive + negative + 1.0), -1.0, 1.0)

    impact = 0.20
    impact += 0.10 * min(4, len(symbols))
    impact += 0.08 * min(5, len([theme for theme in themes if theme != "unknown"]))
    if any(theme in themes for theme in ("security_exploit", "etf_launch", "tokenization", "stablecoin_payments")):
        impact += 0.15
    if "unknown" in themes:
        impact = min(impact, 0.25)
    impact = _clamp(impact, 0.0, 1.0)

    if any(theme in themes for theme in ("tokenization", "stablecoin_payments", "institutional_adoption")):
        horizon = "structural"
    elif any(theme in themes for theme in ("etf_flow", "etf_launch", "asset_specific_catalyst", "regulatory")):
        horizon = "1w"
    elif any(theme in themes for theme in ("market_downtrend", "security_exploit", "macro_risk")):
        horizon = "intraday"
    else:
        horizon = "1d"

    if sentiment > 0.15:
        direction_hint = "positive"
    elif sentiment < -0.15:
        direction_hint = "negative"
    else:
        direction_hint = "neutral"

    return {
        "symbols": symbols,
        "sectors": sorted(sectors),
        "themes": sorted(themes),
        "sentiment_score": round(sentiment, 4),
        "impact_score": round(impact, 4),
        "time_horizon": horizon,
        "direction_hint": direction_hint,
        "confidence": round(_clamp(impact * 0.75 + abs(sentiment) * 0.25, 0.0, 1.0), 4),
    }
