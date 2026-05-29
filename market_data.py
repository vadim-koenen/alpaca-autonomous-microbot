"""
market_data.py — Market data abstraction layer.

Fetches quotes and bars from Alpaca. Validates freshness.
All data returned includes the quote timestamp for staleness checks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd

from utils import data_is_stale, get_cfg, now_utc, safe_float

logger = logging.getLogger("market_data")


@dataclass
class Quote:
    symbol: str
    bid: float
    ask: float
    mid: float
    spread_pct: float
    timestamp: Optional[datetime]
    is_stale: bool = True

    @property
    def valid(self) -> bool:
        return (
            self.bid > 0
            and self.ask > 0
            and self.ask >= self.bid
            and not self.is_stale
        )


@dataclass
class Bar:
    t: datetime
    o: float
    h: float
    l: float
    c: float
    v: float


class MarketData:
    def __init__(self, broker) -> None:
        self._broker = broker

    # -----------------------------------------------------------------------
    # Quotes
    # -----------------------------------------------------------------------

    def get_crypto_quote(self, symbol: str) -> Quote:
        """Return a Quote. is_stale=True if data is old or missing."""
        max_sec = get_cfg("crypto", "stale_data_seconds", default=15)
        raw = self._broker.get_crypto_latest_quote(symbol)
        if raw is None:
            logger.warning(f"No quote for {symbol}")
            return Quote(symbol=symbol, bid=0, ask=0, mid=0, spread_pct=999, timestamp=None)

        bid = safe_float(getattr(raw, "bid_price", 0))
        ask = safe_float(getattr(raw, "ask_price", 0))
        ts = getattr(raw, "timestamp", None)

        # Normalise timezone
        if ts is not None and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        mid = (bid + ask) / 2.0 if bid > 0 and ask > 0 else 0.0
        sp = ((ask - bid) / mid * 100.0) if mid > 0 else 999.0
        stale = data_is_stale(ts, max_sec)

        return Quote(
            symbol=symbol,
            bid=bid,
            ask=ask,
            mid=mid,
            spread_pct=sp,
            timestamp=ts,
            is_stale=stale,
        )

    def get_equity_quote(self, symbol: str) -> Quote:
        max_sec = get_cfg("equities", "stale_data_seconds", default=15)
        raw = self._broker.get_stock_latest_quote(symbol)
        if raw is None:
            return Quote(symbol=symbol, bid=0, ask=0, mid=0, spread_pct=999, timestamp=None)

        bid = safe_float(getattr(raw, "bid_price", 0))
        ask = safe_float(getattr(raw, "ask_price", 0))
        ts = getattr(raw, "timestamp", None)
        if ts is not None and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        mid = (bid + ask) / 2.0 if bid > 0 and ask > 0 else 0.0
        sp = ((ask - bid) / mid * 100.0) if mid > 0 else 999.0
        stale = data_is_stale(ts, max_sec)

        return Quote(symbol=symbol, bid=bid, ask=ask, mid=mid, spread_pct=sp,
                     timestamp=ts, is_stale=stale)

    # -----------------------------------------------------------------------
    # Bars → DataFrame
    # -----------------------------------------------------------------------

    def get_crypto_bars_df(self, symbol: str, limit: int = 100) -> pd.DataFrame:
        """Return OHLCV DataFrame, index=datetime. Empty df on failure."""
        timeframe = get_cfg("strategy", "crypto_timeframe", default="5Min")
        bars = self._broker.get_crypto_bars(symbol, timeframe=timeframe, limit=limit)
        return _bars_to_df(bars)

    def get_equity_bars_df(self, symbol: str, timeframe: str = "5Min", limit: int = 50) -> pd.DataFrame:
        bars = self._broker.get_stock_bars(symbol, timeframe=timeframe, limit=limit)
        return _bars_to_df(bars)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bars_to_df(bars) -> pd.DataFrame:
    """Convert list of alpaca-py Bar objects to a clean DataFrame."""
    if not bars:
        return pd.DataFrame()
    rows = []
    for b in bars:
        try:
            rows.append({
                "t": getattr(b, "timestamp", None),
                "o": safe_float(getattr(b, "open", 0)),
                "h": safe_float(getattr(b, "high", 0)),
                "l": safe_float(getattr(b, "low", 0)),
                "c": safe_float(getattr(b, "close", 0)),
                "v": safe_float(getattr(b, "volume", 0)),
            })
        except Exception:
            continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["t"] = pd.to_datetime(df["t"], utc=True)
    df = df.set_index("t").sort_index()
    return df


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add common technical indicators to OHLCV dataframe.
    Returns df with added columns. Safe to call on small/empty dataframes.
    """
    if df.empty or len(df) < 5:
        return df

    df = df.copy()
    c = df["c"]

    # Simple moving averages
    df["sma_5"] = c.rolling(5).mean()
    df["sma_10"] = c.rolling(10).mean()
    df["sma_20"] = c.rolling(20, min_periods=5).mean()

    # EMA
    df["ema_9"] = c.ewm(span=9, adjust=False).mean()
    df["ema_21"] = c.ewm(span=21, adjust=False).mean()

    # Bollinger Bands (20-period)
    bb_window = min(20, len(df))
    df["bb_mid"] = c.rolling(bb_window).mean()
    df["bb_std"] = c.rolling(bb_window).std()
    df["bb_upper"] = df["bb_mid"] + 2 * df["bb_std"]
    df["bb_lower"] = df["bb_mid"] - 2 * df["bb_std"]
    df["bb_pct_b"] = (c - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"] + 1e-10)

    # RSI (14)
    df["rsi_14"] = _rsi(c, 14)

    # ATR (14) — for volatility sizing and dynamic exit calculation
    df["atr_14"] = _atr(df, 14)
    df["atr_pct"] = df["atr_14"] / (df["c"] + 1e-10)  # ATR as fraction of price

    # Volume SMA
    df["vol_sma_10"] = df["v"].rolling(10).mean()
    df["rel_volume"] = df["v"] / (df["vol_sma_10"] + 1e-10)

    # Price momentum
    df["mom_5"] = c.pct_change(5)
    df["mom_10"] = c.pct_change(10)

    return df


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    return 100.0 - (100.0 / (1.0 + rs))


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h = df["h"]
    l = df["l"]
    c = df["c"].shift(1)
    tr = pd.concat([h - l, (h - c).abs(), (l - c).abs()], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()
